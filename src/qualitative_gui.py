"""Batch qualitative evaluation and instructor confirmation UI."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import uuid
from PyQt6.QtCore import QThread, pyqtSignal, QSettings, Qt, QSignalBlocker, QItemSelectionModel
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,
    QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTableWidget,QTableWidgetItem,
    QHeaderView,QTabWidget,QFileDialog,QSplitter,QProgressBar,QAbstractItemView,QDialog,QTableWidgetSelectionRange)
from llm_cases import LLMClient
from llm_config import llm_settings
from materials import build_catalog
from slide_picker import SlidePicker
from paths import ROOT
from qualitative import DEFAULT_RUBRIC,validate_rubric,review_batch,confirm_review,confirm_reviews,save_reviews,load_reviews
from qualitative_rubric import (SCORING_VERSION, RESOURCE_IDS, resource_scope,
    validate_dcucode_rubric)


class ReviewWorker(QThread):
    row_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    def __init__(self,client,problem,rubric,submissions,parent=None,options=None):
        super().__init__(parent)
        self.arguments = client,problem,rubric,submissions
        self.options = options or {}
    def run(self):
        try:
            for row in review_batch(*self.arguments,cancelled=self.isInterruptionRequested,**self.options):
                self.row_ready.emit(row)
        except Exception as error:
            self.failed.emit(str(error))


class QualitativeWindow(QWidget):
    def __init__(self,submissions,preset=None):
        """`preset` (title, problem, rubric, summary) prefills an exam such as the midterm; the instructor can still edit."""
        super().__init__()
        self.preset = preset or {}
        self.setWindowTitle('Qwen 정성평가'+(' · '+self.preset['title'] if self.preset.get('title') else ''))
        self.resize(1200,850)
        self.submissions = submissions
        self.rows = []
        self.context = {}
        self.worker = None
        self.archive = None
        self.decks = build_catalog()
        self.rubric = deepcopy(self.preset.get('rubric') or DEFAULT_RUBRIC)
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
        patterns=next((s['sources'] for s in submissions if s.get('sources')),None)
        scope=f'지정 파일({", ".join(patterns)})과' if patterns else '선택 문제의 소스와'
        root.addWidget(QLabel(f'선택 학생 {len(submissions)}명 · {scope} 요구사항·평가기준을 위 서버에 전송합니다. 학번 매핑은 로컬에 보관합니다.'))
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
        self.populate_rubric()
        if self.preset.get('problem'):
            self.problem_text.setPlainText(self.preset['problem'])
            self.source_summary.setText(self.preset.get('summary') or self.preset.get('title') or '')
        config.addTab(self.problem_text,'문제 요구사항');config.addTab(self.rubric_table,'평가 기준 / 배점')
        resource_panel=QWidget();resource_layout=QVBoxLayout(resource_panel)
        points_layout=QHBoxLayout();points_layout.addWidget(QLabel('문제 배점 (제안 부분점수 만점)'))
        self.problem_points=QSpinBox();self.problem_points.setRange(1,10000)
        self.problem_points.setValue(int(self.preset.get('points',100)))
        points_layout.addWidget(self.problem_points);points_layout.addStretch();resource_layout.addLayout(points_layout)
        self.resource_modes={}
        for kind,label in [('files','파일 열기·닫기'),('memory','동적 메모리 할당·해제'),('processes','프로세스 생성·종료·자식 회수')]:
            line=QHBoxLayout();line.addWidget(QLabel(label))
            combo=QComboBox()
            for text,value in [('자동 (문제 요구·실제 사용 기준)','auto'),('평가에 포함','include'),('평가에서 제외','exclude')]:
                combo.addItem(text,value)
            combo.currentIndexChanged.connect(self.refresh_resource_info)
            self.resource_modes[kind]=combo;line.addWidget(combo);resource_layout.addLayout(line)
        self.resource_info=QLabel();self.resource_info.setWordWrap(True);resource_layout.addWidget(self.resource_info)
        formula=QLabel('DCUCode 기본 4축은 각각 0–10점입니다.\n'
            '자원 관리는 적용되는 문항만 평균 내어 0–10점으로 환산합니다.\n'
            '종합 품질: 기본 4축 + 자원 관리(적용 시)를 100점으로 환산.\n'
            '시험 제안 부분점수: 문제 배점 × (정확성 + 문제 이해도 + 적용 자원 관리) ÷ (20 또는 30).\n'
            '제외 문항은 0점이나 만점으로 처리하지 않고 계산에서 뺍니다.\n'
            '필요한 자원을 학생이 구현하지 않은 경우에는 제외하지 않습니다.')
        formula.setWordWrap(True);resource_layout.addWidget(formula)
        self.reset_rubric_button=QPushButton('DCUCode 기준으로 복원')
        self.reset_rubric_button.clicked.connect(self.reset_rubric);resource_layout.addWidget(self.reset_rubric_button)
        resource_layout.addStretch();config.addTab(resource_panel,'문제 배점 / 자원 적용')
        self.problem_text.textChanged.connect(self.refresh_resource_info)
        self.problem_points.valueChanged.connect(self.refresh_resource_info)
        self.refresh_resource_info()
        split.addWidget(config)
        panel=QWidget();layout=QVBoxLayout(panel)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['학생','상태','종합 품질 / 100','제안 부분점수','교수자 확정'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        selection=QHBoxLayout()
        self.select_all_button=QPushButton('전체 선택');self.select_all_button.clicked.connect(self.table.selectAll)
        self.clear_selection_button=QPushButton('선택 해제');self.clear_selection_button.clicked.connect(self.table.clearSelection)
        selection.addWidget(self.select_all_button);selection.addWidget(self.clear_selection_button)
        self.selection_info=QLabel();selection.addWidget(self.selection_info,1);layout.addLayout(selection)
        layout.addWidget(self.table,1)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);layout.addWidget(self.detail,2)
        final=QHBoxLayout();self.final_score=QDoubleSpinBox();self.final_score.setDecimals(2)
        final.addWidget(QLabel('교수자 확정 점수'));final.addWidget(self.final_score)
        self.confirm_button=QPushButton('현재 학생 점수 확정');self.confirm_button.clicked.connect(self.confirm)
        final.addWidget(self.confirm_button);layout.addLayout(final)
        self.note=QPlainTextEdit();self.note.setPlaceholderText('점수 유지 또는 조정에 대한 교수자 검토 의견');self.note.setMaximumHeight(75)
        layout.addWidget(self.note)
        batch=QHBoxLayout()
        self.batch_note=QLineEdit('교수자 일괄 승인: AI 제안 점수 유지')
        self.batch_note.setToolTip('일괄 승인 대상 학생 모두에게 저장할 검토 의견')
        self.batch_confirm_button=QPushButton('선택 학생 일괄 승인 (0명)')
        self.batch_confirm_button.setToolTip('선택한 미확정 학생의 AI 제안 점수를 각각 확정합니다. 이미 확정한 점수와 평가 실패는 건너뜁니다.')
        self.batch_confirm_button.clicked.connect(self.confirm_selected)
        batch.addWidget(self.batch_note,1);batch.addWidget(self.batch_confirm_button);layout.addLayout(batch)
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
        for widget in (self.start_button,self.problem_text,self.rubric_table,self.load_problem_button,self.url,self.model,self.open_button,self.note,self.final_score,
                       self.problem_points,self.reset_rubric_button,self.batch_note,self.select_all_button,self.clear_selection_button,
                       *self.resource_modes.values()):widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.update_approval_controls(busy)

    def selected_indices(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows() if index.row()<len(self.rows))

    def update_approval_controls(self,busy=None):
        if busy is None:busy=bool(self.worker and self.worker.isRunning())
        indices=self.selected_indices()
        pending=sum(self.rows[i]['status']=='ai_proposed' for i in indices)
        self.selection_info.setText(f'전체 {len(self.rows)}명 · 선택 {len(indices)}명 · 미확정 {pending}명')
        self.batch_confirm_button.setText(f'선택 학생 일괄 승인 ({pending}명)')
        self.batch_confirm_button.setEnabled(not busy and pending>0)
        current=self.table.currentRow()
        self.confirm_button.setEnabled(not busy and current in indices and self.rows[current]['status'] in ('ai_proposed','confirmed'))

    def selection_changed(self):
        indices=self.selected_indices()
        if indices:
            if self.table.currentRow() not in indices:
                self.table.setCurrentCell(indices[0],0,QItemSelectionModel.SelectionFlag.NoUpdate)
            self.show_selected()
        else:self.detail.clear()
        self.update_approval_controls()

    def populate_rubric(self):
        self.rubric_table.setRowCount(len(self.rubric))
        for row,rule in enumerate(self.rubric):
            for column,key in enumerate(('name','max_score','description')):
                item=QTableWidgetItem(str(rule[key]))
                if column == 1:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.rubric_table.setItem(row,column,item)

    def reset_rubric(self):
        self.rubric=deepcopy(DEFAULT_RUBRIC);self.populate_rubric()

    def resource_policy(self):
        return {kind:combo.currentData() for kind,combo in self.resource_modes.items()}

    def refresh_resource_info(self):
        if not hasattr(self,'resource_info'):return
        scope=resource_scope(self.problem_text.toPlainText(),{},self.resource_policy())
        labels={'files':'파일','memory':'동적 메모리','processes':'프로세스'}
        text=' / '.join(f'{labels[k]}: {"평가" if v["applicable"] else "제외"}' for k,v in scope.items())
        self.resource_info.setText(f'문제 기준 예상: {text}\n자동 모드는 제출 코드에서 실제로 사용한 자원도 평가합니다. 명시적으로 포함/제외를 선택해 보정할 수 있습니다.')

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
            validate_dcucode_rubric(rules)
            if not problem.strip() or len(problem)>30000:raise ValueError('문제 요구사항을 1–30,000자로 입력하세요.')
            if not self.submissions:raise ValueError('메인 화면에서 평가할 학생을 선택하세요.')
            client=LLMClient(self.url.text().strip(),self.model.text().strip())
        except (ValueError,AttributeError) as error:
            self.status.setText(str(error));return
        self.rows=[];self.table.setRowCount(0);self.detail.clear();self.note.clear()
        self.archive=ROOT/'reports'/f'qualitative_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.json'
        self.context={'problem':problem,'rubric':rules,'submissions':[{k:v for k,v in s.items() if k!='path'} for s in self.submissions],
                      'model':client.model,'endpoint':client.base_url,'run_state':'running',
                      'scoring_version':SCORING_VERSION,'problem_points':self.problem_points.value(),
                      'resource_policy':self.resource_policy()}
        self.context['slide_selection']={k:v for k,v in (self.slide_selection or {}).items() if k!='text'}
        if self.preset.get('title'):self.context['preset']={k:self.preset[k] for k in ('title','points') if k in self.preset}
        try:save_reviews(self.archive,self.rows,self.context)
        except OSError as error:self.status.setText(f'자동 저장 실패: {error}');return
        self.progress.setRange(0,len(self.submissions));self.progress.setValue(0)
        self.worker=ReviewWorker(client,problem,rules,self.submissions,self,
            options=dict(total_score=self.problem_points.value(),resource_policy=self.resource_policy()))
        self.worker.row_ready.connect(self.add_row)
        self.worker.failed.connect(self.worker_error)
        self.worker.finished.connect(self.finished)
        self.set_busy(True);self.status.setText('Qwen 평가 중 · 학생별 완료 결과를 자동 저장합니다.')
        self.worker.start()

    def add_row(self,row):
        self.rows.append(row);self.refresh_rows();self.progress.setValue(len(self.rows))
        self.persist()

    def refresh_rows(self):
        selected=self.selected_indices();current=self.table.currentRow();old_count=self.table.rowCount()
        labels={'ai_proposed':'AI 제안','confirmed':'교수자 확정','error':'평가 실패'}
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(self.rows))
            for i,row in enumerate(self.rows):
                for column,value in enumerate([row.get('student',''),labels.get(row['status'],row['status']),
                    '' if row.get('overall') is None else f"{row['overall']}/100",
                    '' if row.get('suggested_score') is None else f"{row['suggested_score']}/{row['max_score']}",row.get('final_score')]):
                    self.table.setItem(i,column,QTableWidgetItem('' if value is None else str(value)))
            self.table.clearSelection()
            if old_count==0 and self.rows:selected=[0]
            for i in selected:
                self.table.setRangeSelected(QTableWidgetSelectionRange(i,0,i,self.table.columnCount()-1),True)
            if self.rows:self.table.setCurrentCell(current if 0<=current<len(self.rows) else 0,0,QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selection_changed()

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
        if row.get('scoring_version') == SCORING_VERSION:
            parts.extend([f'종합 품질: {row["overall"]}/100 · 제안 부분점수: {row["suggested_score"]}/{row["max_score"]}',
                f'자원 관리: {row["resource_score"] if row["resource_score"] is not None else "비적용"} · 종합 분모 {row["overall_denominator"]}, 부분점수 분모 {row["partial_denominator"]}'])
        for item in row['criteria']:
            mark='제외 (계산에 반영하지 않음)' if item.get('applicable') is False else f"{item['score']}/{item['max_score']}"
            parts.append(f"\n{item['name']}: {mark}\n{item['reason']}")
            for ref in item['evidence']:parts.append(f"  {ref['file']}:{ref['line']}  {ref['code']}")
        for key,title in [('strengths','강점'),('improvements','개선 의견'),('uncertainties','불확실한 부분')]:
            parts.append('\n'+title+'\n'+'\n'.join(row[key]))
        self.detail.setPlainText('\n'.join(parts));self.final_score.setMaximum(row['max_score'])
        self.final_score.setValue(row['final_score'] if row.get('final_score') is not None else row['suggested_score'])
        self.note.setPlainText(row.get('reviewer_note',''))
        self.confirm_button.setEnabled(not (self.worker and self.worker.isRunning()))

    def confirm(self):
        if self.worker and self.worker.isRunning():return
        index=self.table.currentRow()
        if index not in self.selected_indices():return
        try:confirm_review(self.rows[index],self.final_score.value(),self.note.toPlainText())
        except ValueError as error:self.status.setText(str(error));return
        self.refresh_rows();self.persist()

    def confirm_selected(self):
        if self.worker and self.worker.isRunning():return
        selected=[self.rows[i] for i in self.selected_indices()]
        try:count=confirm_reviews(selected,self.batch_note.text())
        except ValueError as error:self.status.setText(str(error));return
        if not count:self.status.setText('선택한 학생 중 승인할 AI 제안이 없습니다.');return
        self.refresh_rows();self.persist()
        self.status.setText(f'{count}명 일괄 승인 완료 · 기존 확정·평가 실패 {len(selected)-count}명 제외 · {self.status.text()}')

    def export(self):
        if not self.rows:self.status.setText('저장할 평가 결과가 없습니다.');return
        path,kind=QFileDialog.getSaveFileName(self,'정성평가 저장','qualitative.csv',
            '학생별 요약 CSV (*.csv);;항목별 상세 CSV (*.csv);;JSON (*.json)')
        if path:
            try:save_reviews(path,self.rows,self.context,csv_detail=kind.startswith('항목별 상세'));self.status.setText('저장 완료: '+path)
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
            self.populate_rubric()
            self.problem_points.setValue(int(self.context.get('problem_points',100)))
            for kind,combo in self.resource_modes.items():
                combo.setCurrentIndex(combo.findData(self.context.get('resource_policy',{}).get(kind,'auto')))
            self.refresh_resource_info()
            self.refresh_rows();self.set_busy(False);self.status.setText('평가 기록을 불러왔습니다. 검토 후 확정할 수 있습니다.')
        except (OSError,ValueError,TypeError) as error:self.status.setText('불러오기 실패: '+str(error))

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.cancel();event.ignore()
        else:event.accept()
