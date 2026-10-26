"""Batch qualitative evaluation and instructor confirmation UI."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import uuid
from PyQt6.QtCore import QThread, pyqtSignal, QSettings
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,
    QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTableWidget,QTableWidgetItem,
    QHeaderView,QTabWidget,QFileDialog,QSplitter,QProgressBar,QAbstractItemView,QDialog)
from llm_cases import LLMClient
from llm_config import llm_settings
from materials import build_catalog
from slide_picker import SlidePicker
from paths import ROOT
from qualitative import DEFAULT_RUBRIC,validate_rubric,review_batch,confirm_review,save_reviews,load_reviews


class ReviewWorker(QThread):
    row_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    def __init__(self,client,problem,rubric,submissions,parent=None):
        super().__init__(parent)
        self.arguments = client,problem,rubric,submissions
    def run(self):
        try:
            for row in review_batch(*self.arguments,cancelled=self.isInterruptionRequested):
                self.row_ready.emit(row)
        except Exception as error:
            self.failed.emit(str(error))


class QualitativeWindow(QWidget):
    def __init__(self,submissions):
        super().__init__()
        self.setWindowTitle('Qwen 정성평가')
        self.resize(1200,850)
        self.submissions = submissions
        self.rows = []
        self.context = {}
        self.worker = None
        self.archive = None
        self.decks = build_catalog()
        self.rubric = deepcopy(DEFAULT_RUBRIC)
        root = QVBoxLayout(self)
        server = QHBoxLayout()
        settings=QSettings('SWLAB','PracticeEvaluation')
        config_error=''
        try:
            config=llm_settings(settings)
        except ValueError as error:
            config={'url':'','model':''};config_error=str(error)
        self.url=QLineEdit(config['url']);self.url.setPlaceholderText('LLM 서버 URL 입력')
        self.model=QLineEdit(config['model']);self.model.setPlaceholderText('모델명 입력')
        server.addWidget(QLabel('Qwen 서버'));server.addWidget(self.url,2)
        server.addWidget(QLabel('모델'));server.addWidget(self.model,2)
        root.addLayout(server)
        root.addWidget(QLabel(f'선택 학생 {len(submissions)}명 · 선택 문제의 소스와 요구사항·평가기준을 위 서버에 전송합니다. 학번 매핑은 로컬에 보관합니다.'))
        material=QHBoxLayout()
        self.slide_selection=None
        self.load_problem_button=QPushButton('슬라이드 목록에서 문제 선택…');self.load_problem_button.clicked.connect(self.load_problem)
        self.source_summary=QLabel('직접 입력 또는 슬라이드 선택');self.source_summary.setWordWrap(True)
        material.addWidget(self.load_problem_button);material.addWidget(self.source_summary,1)
        root.addLayout(material)
        split=QSplitter()
        config=QTabWidget()
        self.problem_text=QPlainTextEdit();self.problem_text.setPlaceholderText('평가할 문제의 요구사항을 입력하거나 PPT 페이지에서 불러오세요.')
        self.rubric_table=QTableWidget(len(self.rubric),3)
        self.rubric_table.setHorizontalHeaderLabels(['평가 항목','배점','판정 기준'])
        self.rubric_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        for row,rule in enumerate(self.rubric):
            for column,key in enumerate(('name','max_score','description')):
                self.rubric_table.setItem(row,column,QTableWidgetItem(str(rule[key])))
        config.addTab(self.problem_text,'문제 요구사항');config.addTab(self.rubric_table,'평가 기준 / 배점')
        split.addWidget(config)
        panel=QWidget();layout=QVBoxLayout(panel)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['학생','상태','AI 제안','교수자 확정'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.table,1)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);layout.addWidget(self.detail,2)
        final=QHBoxLayout();self.final_score=QDoubleSpinBox();self.final_score.setDecimals(2)
        final.addWidget(QLabel('교수자 확정 점수'));final.addWidget(self.final_score)
        self.confirm_button=QPushButton('검토 후 확정');self.confirm_button.clicked.connect(self.confirm)
        final.addWidget(self.confirm_button);layout.addLayout(final)
        self.note=QPlainTextEdit();self.note.setPlaceholderText('점수 유지 또는 조정에 대한 교수자 검토 의견');self.note.setMaximumHeight(75)
        layout.addWidget(self.note)
        split.addWidget(panel);split.setSizes([430,770]);root.addWidget(split,1)
        actions=QHBoxLayout()
        self.start_button=QPushButton('선택 학생 일괄 정성평가');self.start_button.clicked.connect(self.start)
        self.cancel_button=QPushButton('현재 학생 완료 후 중지');self.cancel_button.clicked.connect(self.cancel)
        self.export_button=QPushButton('CSV / JSON 저장');self.export_button.clicked.connect(self.export)
        self.open_button=QPushButton('저장된 평가 열기');self.open_button.clicked.connect(self.open_report)
        for button in (self.start_button,self.cancel_button,self.export_button,self.open_button):actions.addWidget(button)
        self.progress=QProgressBar();actions.addWidget(self.progress);root.addLayout(actions)
        self.status=QLabel(config_error or 'AI 평가를 제안으로 저장합니다. 학생을 선택해 근거를 검토하고 최종 점수를 확정하세요.');self.status.setWordWrap(True);root.addWidget(self.status)
        self.set_busy(False)

    def set_busy(self,busy):
        for widget in (self.start_button,self.problem_text,self.rubric_table,self.load_problem_button,self.url,self.model,self.open_button,self.note,self.final_score):widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.confirm_button.setEnabled(not busy and bool(self.rows))

    def load_problem(self):
        target=self.submissions[0] if self.submissions else {}
        picker=SlidePicker(self.decks,target.get('chapter') or '',target.get('problem') or '',self.slide_selection,self)
        if picker.exec()==QDialog.DialogCode.Accepted:
            self.slide_selection=picker.selection
            self.problem_text.setPlainText(picker.selection['text'])
            self.source_summary.setText(picker.selection['title']+' · '+', '.join(map(str,picker.selection['pages']))+'쪽')

    def read_rubric(self):
        rules=deepcopy(self.rubric)
        for i,rule in enumerate(rules):
            rule.update(name=self.rubric_table.item(i,0).text(),max_score=float(self.rubric_table.item(i,1).text()),description=self.rubric_table.item(i,2).text())
        return validate_rubric(rules)

    def start(self):
        try:
            rules=self.read_rubric();problem=self.problem_text.toPlainText()
            if not problem.strip() or len(problem)>30000:raise ValueError('문제 요구사항을 1–30,000자로 입력하세요.')
            if not self.submissions:raise ValueError('메인 화면에서 평가할 학생을 선택하세요.')
            client=LLMClient(self.url.text().strip(),self.model.text().strip())
        except (ValueError,AttributeError) as error:
            self.status.setText(str(error));return
        self.rows=[];self.table.setRowCount(0);self.detail.clear();self.note.clear()
        self.archive=ROOT/'reports'/f'qualitative_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.json'
        self.context={'problem':problem,'rubric':rules,'submissions':[{k:v for k,v in s.items() if k!='path'} for s in self.submissions],
                      'model':client.model,'endpoint':client.base_url,'run_state':'running'}
        self.context['slide_selection']={k:v for k,v in (self.slide_selection or {}).items() if k!='text'}
        try:save_reviews(self.archive,self.rows,self.context)
        except OSError as error:self.status.setText(f'자동 저장 실패: {error}');return
        self.progress.setRange(0,len(self.submissions));self.progress.setValue(0)
        self.worker=ReviewWorker(client,problem,rules,self.submissions,self)
        self.worker.row_ready.connect(self.add_row)
        self.worker.failed.connect(self.worker_error)
        self.worker.finished.connect(self.finished)
        self.set_busy(True);self.status.setText('Qwen 평가 중 · 학생별 완료 결과를 자동 저장합니다.')
        self.worker.start()

    def add_row(self,row):
        self.rows.append(row);self.refresh_rows();self.progress.setValue(len(self.rows))
        self.persist()

    def refresh_rows(self):
        selected=self.table.currentRow()
        self.table.setRowCount(len(self.rows))
        labels={'ai_proposed':'AI 제안','confirmed':'교수자 확정','error':'평가 실패'}
        for i,row in enumerate(self.rows):
            for column,value in enumerate([row.get('student',''),labels.get(row['status'],row['status']),
                    '' if row.get('suggested_score') is None else f"{row['suggested_score']}/{row['max_score']}",row.get('final_score')]):
                self.table.setItem(i,column,QTableWidgetItem('' if value is None else str(value)))
        if selected>=0:self.table.selectRow(selected)
        elif self.rows:self.table.selectRow(0)

    def persist(self):
        try:
            save_reviews(self.archive,self.rows,self.context)
            self.status.setText(f'{len(self.rows)}명 평가 기록 · 자동 저장: {self.archive}')
        except OSError as error:self.status.setText(f'자동 저장 실패(화면 결과는 유지): {error}')

    def finished(self):
        self.context['run_state']='error' if self.context.get('error') else ('cancelled' if self.worker.isInterruptionRequested() else 'finished')
        self.set_busy(False);self.persist()

    def worker_error(self,text):
        self.context['error']=text
        self.status.setText('평가 오류: '+text)

    def cancel(self):
        if self.worker:self.worker.requestInterruption();self.status.setText('현재 학생의 응답을 받은 후 중지합니다.')

    def show_selected(self):
        index=self.table.currentRow()
        if not 0<=index<len(self.rows):return
        row=self.rows[index]
        if row['status']=='error':self.detail.setPlainText(row.get('message',''));self.confirm_button.setEnabled(False);return
        parts=[row['summary']]
        for item in row['criteria']:
            parts.append(f"\n{item['name']}: {item['score']}/{item['max_score']}\n{item['reason']}")
            for ref in item['evidence']:parts.append(f"  {ref['file']}:{ref['line']}  {ref['code']}")
        for key,title in [('strengths','강점'),('improvements','개선 의견'),('uncertainties','불확실한 부분')]:
            parts.append('\n'+title+'\n'+'\n'.join(row[key]))
        self.detail.setPlainText('\n'.join(parts));self.final_score.setMaximum(row['max_score'])
        self.final_score.setValue(row['final_score'] if row.get('final_score') is not None else row['suggested_score'])
        self.note.setPlainText(row.get('reviewer_note',''))
        self.confirm_button.setEnabled(not (self.worker and self.worker.isRunning()))

    def confirm(self):
        index=self.table.currentRow()
        if not 0<=index<len(self.rows):return
        try:confirm_review(self.rows[index],self.final_score.value(),self.note.toPlainText())
        except ValueError as error:self.status.setText(str(error));return
        self.refresh_rows();self.persist()

    def export(self):
        if not self.rows:self.status.setText('저장할 평가 결과가 없습니다.');return
        path,_=QFileDialog.getSaveFileName(self,'정성평가 저장','qualitative.csv','CSV (*.csv);;JSON (*.json)')
        if path:
            try:save_reviews(path,self.rows,self.context);self.status.setText('저장 완료: '+path)
            except OSError as error:self.status.setText('저장 실패: '+str(error))

    def open_report(self):
        path,_=QFileDialog.getOpenFileName(self,'저장된 정성평가 열기',str(ROOT/'reports'),'JSON (*.json)')
        if not path:return
        try:
            data=load_reviews(path)
            rules=validate_rubric(data['context'].get('rubric',deepcopy(DEFAULT_RUBRIC)))
            self.rows=data['results'];self.context=data['context'];self.archive=Path(path)
            self.problem_text.setPlainText(str(self.context.get('problem','')))
            self.rubric=deepcopy(rules)
            self.rubric_table.setRowCount(len(rules))
            for i,rule in enumerate(rules):
                for column,key in enumerate(('name','max_score','description')):
                    self.rubric_table.setItem(i,column,QTableWidgetItem(str(rule[key])))
            self.refresh_rows();self.set_busy(False);self.status.setText('평가 기록을 불러왔습니다. 검토 후 확정할 수 있습니다.')
        except (OSError,ValueError,TypeError) as error:self.status.setText('불러오기 실패: '+str(error))

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.cancel();event.ignore()
        else:event.accept()
