"""Manifest-based grading, saved runs and score review."""
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPlainTextEdit, QLineEdit, QDoubleSpinBox, QProgressBar, QSplitter)

from core.manifest import load_problem
from core.resolver import load_layout, resolve_submission, save_override
from core.record import load_run, override_score, export_summary
from core.service import run_batch
from paths import ROOT, natural_key


class GradingWorker(QThread):
    progress = pyqtSignal(int, object, object)
    completed = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, arguments, parent=None):
        super().__init__(parent)
        self.arguments = arguments

    def run(self):
        try:
            archive, run = run_batch(**self.arguments, progress=self.progress.emit,
                                     cancelled=self.isInterruptionRequested)
            self.completed.emit(archive, run)
        except Exception as exc:
            self.failed.emit(str(exc))


class GradingWindow(QWidget):
    def __init__(self, submissions=None):
        super().__init__()
        self.setWindowTitle('문제 기반 채점 · 성적 기록')
        self.resize(1120, 800)
        self.submissions = submissions or []
        self.rows = []
        self.worker = None
        self.archive = None
        self.run_record = None
        self.problem = None
        root = QVBoxLayout(self)
        choices = QHBoxLayout()
        self.selector = QComboBox()
        for path in sorted((ROOT / 'assignments').rglob('problem.yaml')):
            self.selector.addItem(str(path.relative_to(ROOT / 'assignments')), str(path))
        self.browse_button = QPushButton('문제 파일 열기')
        self.browse_button.clicked.connect(self.browse_problem)
        self.students_button = QPushButton('분반 폴더 선택')
        self.students_button.clicked.connect(self.choose_students)
        self.roster_button = QPushButton('명단 기준 대상 선택')
        self.roster_button.clicked.connect(self.choose_roster)
        self.preview_button = QPushButton('명세 검증 · 제출물 확인')
        self.preview_button.clicked.connect(self.preview)
        choices.addWidget(QLabel('문제')); choices.addWidget(self.selector, 1)
        for button in (self.browse_button, self.students_button, self.roster_button, self.preview_button):
            choices.addWidget(button)
        root.addLayout(choices)
        self.statement = QPlainTextEdit()
        self.statement.setReadOnly(True)
        self.statement.setMaximumHeight(120)
        root.addWidget(self.statement)
        split = QSplitter()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['학생', '상태', '자동 점수', '최종 점수', '제출 경로'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        split.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.detail)
        root.addWidget(split, 1)
        adjustment = QHBoxLayout()
        self.mapping_button = QPushButton('선택 학생 제출 경로 지정')
        self.mapping_button.clicked.connect(self.map_student)
        self.score = QDoubleSpinBox(); self.score.setRange(0, 1_000_000); self.score.setDecimals(4)
        self.reviewer = QLineEdit(); self.reviewer.setPlaceholderText('검토자')
        self.reason = QLineEdit(); self.reason.setPlaceholderText('점수 조정 이유 (필수)')
        self.override_button = QPushButton('최종 점수 저장')
        self.override_button.clicked.connect(self.adjust)
        adjustment.addWidget(self.mapping_button)
        adjustment.addWidget(QLabel('최종 점수')); adjustment.addWidget(self.score)
        adjustment.addWidget(self.reviewer); adjustment.addWidget(self.reason, 1)
        adjustment.addWidget(self.override_button)
        root.addLayout(adjustment)
        controls = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(['docker', 'windows', 'linux', 'wsl'])
        self.start_button = QPushButton('배점 채점 시작')
        self.start_button.clicked.connect(self.start)
        self.cancel_button = QPushButton('현재 학생 완료 후 중지')
        self.cancel_button.clicked.connect(self.cancel)
        self.open_button = QPushButton('기록 다시 열기'); self.open_button.clicked.connect(self.open_record)
        self.export_button = QPushButton('성적표 CSV 저장'); self.export_button.clicked.connect(self.export)
        self.progress_bar = QProgressBar()
        for widget in (self.mode, self.start_button, self.cancel_button, self.open_button, self.export_button, self.progress_bar):
            controls.addWidget(widget)
        root.addLayout(controls)
        self.status = QLabel('문제를 선택하고 제출물을 확인하세요. 결과는 학생별로 자동 저장됩니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.selector.currentIndexChanged.connect(self.preview)
        self.set_busy(False)
        if self.selector.count():
            self.preview()

    def set_busy(self, busy):
        for widget in (self.selector, self.browse_button, self.students_button, self.roster_button, self.preview_button,
                       self.mode, self.start_button, self.mapping_button, self.open_button,
                       self.score, self.reviewer, self.reason):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.override_button.setEnabled(not busy and self.archive is not None)
        self.export_button.setEnabled(not busy and self.archive is not None)

    def browse_problem(self):
        path, _ = QFileDialog.getOpenFileName(self, '문제 명세', str(ROOT / 'assignments'), 'YAML (*.yaml *.yml)')
        if path:
            self.selector.addItem(path, path)
            self.selector.setCurrentIndex(self.selector.count() - 1)

    def choose_students(self):
        path = QFileDialog.getExistingDirectory(self, '학번별 폴더가 있는 분반 폴더')
        if path:
            self.submissions = [{'student_id': p.name, 'path': str(p)} for p in
                sorted(Path(path).iterdir(), key=lambda p: natural_key(p.name))
                if p.is_dir() and not p.name.startswith('.')]
            self.preview()

    def preview(self):
        try:
            path = self.selector.currentData()
            if not path:
                raise ValueError('문제 파일을 선택하세요.')
            problem = load_problem(path)
            layout = load_layout(problem.layout_path)
            rows = []
            for student in self.submissions:
                resolved = resolve_submission(student['path'], student['student_id'], problem, layout)
                rows.append({'student_id': student['student_id'], 'status': resolved['status'],
                             'submission': resolved, 'max_score': problem.total})
            self.problem = problem
            self.archive = self.run_record = None
            self.rows = rows
            self.statement.setPlainText(f"{problem.data['title']} · 총 {problem.total}점 · {len(problem.cases)}개 케이스\n{problem.data['statement']}")
            self.refresh()
            self.set_busy(False)
            found = sum(r['status'] == 'resolved' for r in rows)
            self.status.setText(f'명세 검증 완료 · 제출물 확인 {found}/{len(rows)}명. 미확정은 경로 지정 후 다시 채점할 수 있습니다.')
            return True
        except (OSError, ValueError) as exc:
            self.problem = None
            self.status.setText(str(exc))
            return False

    def choose_roster(self):
        from core.roster import roster_submissions
        path, _ = QFileDialog.getOpenFileName(self, '학생 명단 선택', str(ROOT / 'testdata'), 'CSV (*.csv)')
        if not path:
            return
        directory = QFileDialog.getExistingDirectory(self, '명단 학생의 저장소가 있는 분반 폴더')
        if directory:
            try:
                self.submissions = roster_submissions(path, directory)
                self.preview()
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))

    def refresh(self):
        selected = self.table.currentRow()
        self.table.setRowCount(len(self.rows))
        labels = {'resolved': '제출 확인', 'unresolved': '미확정', 'pending': '대기',
                  'graded': '채점 완료', 'error': '채점 오류', 'not_run': '미실행'}
        for i, row in enumerate(self.rows):
            state = labels.get(row['status'], row['status'])
            if row.get('review_state') == 'adjusted':
                state += ' · 수동 조정'
            values = [row['student_id'], state, row.get('auto_score'), row.get('final_score'), row.get('submission', {}).get('resolved_path', '')]
            for col, value in enumerate(values):
                self.table.setItem(i, col, QTableWidgetItem('—' if value is None else str(value)))
        if 0 <= selected < len(self.rows):
            self.table.selectRow(selected)
            self.show_selected()

    def show_selected(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        self.score.setMaximum(row['max_score'])
        self.score.setValue(row.get('final_score') or 0)
        self.reason.clear()
        self.detail.setPlainText(format_details(row))

    def map_student(self):
        index = self.table.currentRow()
        if self.archive or self.problem is None or not 0 <= index < len(self.submissions):
            self.status.setText('명세 검증 · 제출물 확인 후 학생을 선택하세요.')
            return
        student = self.submissions[index]
        root = Path(student['path']).resolve()
        chosen = QFileDialog.getExistingDirectory(self, '제출 폴더 지정', str(root))
        if not chosen:
            return
        try:
            relative = Path(chosen).resolve().relative_to(root).as_posix()
            trial = {'overrides': {student['student_id']: {self.problem.id: relative}}}
            result = resolve_submission(root, student['student_id'], self.problem, trial)
            if result['status'] != 'resolved':
                raise ValueError(result['message'])
            save_override(self.problem.layout_path, student['student_id'], self.problem, relative)
            self.preview()
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.preview():
            return
        if not self.submissions:
            self.status.setText('메인 화면에서 학생을 선택하거나 분반 폴더를 선택하세요.')
            return
        self.progress_bar.setRange(0, len(self.submissions)); self.progress_bar.setValue(0)
        self.worker = GradingWorker({'problem_path': self.problem.path, 'submissions': self.submissions,
            'mode': self.mode.currentText()}, self)
        self.worker.progress.connect(self.row_ready)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.set_busy(True)
        self.status.setText('실행 환경 확인 및 채점 중 · 결과를 자동 저장합니다.')
        self.worker.start()

    def row_ready(self, index, row, archive):
        self.archive = Path(archive)
        self.rows[index - 1] = row
        self.refresh(); self.progress_bar.setValue(index)
        self.status.setText(f'{index}/{len(self.submissions)}명 저장 완료 · {archive}')

    def completed(self, archive, run):
        self.archive, self.run_record = Path(archive), run
        self.rows = run['results']; self.refresh()
        self.status.setText(f"{'중지됨' if run['state'] == 'cancelled' else '채점 완료'} · {archive}")

    def failed(self, message):
        self.status.setText('채점 오류: ' + message)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText('현재 학생을 저장한 뒤 중지합니다.')

    def open_record(self):
        path, _ = QFileDialog.getOpenFileName(self, '채점 기록 열기', str(ROOT / 'records'), 'JSON (*.json)')
        if path:
            try:
                run = load_run(path)
                self.archive, self.run_record = Path(path), run
                self.rows = run['results']; self.refresh()
                self.statement.setPlainText(f"{run['problem']['title']}\n{run['problem']['statement']}")
                self.set_busy(False)
                self.status.setText(f"기록 불러옴 · {run['state']} · {path}")
            except (OSError, ValueError, KeyError) as exc:
                self.status.setText(str(exc))

    def adjust(self):
        index = self.table.currentRow()
        if self.archive is None or not 0 <= index < len(self.rows):
            return
        try:
            self.run_record = override_score(self.archive, self.rows[index]['student_id'], self.score.value(), self.reviewer.text(), self.reason.text())
            self.rows = self.run_record['results']; self.refresh()
            self.status.setText('최종 점수와 조정 이력, 성적표를 저장했습니다.')
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def export(self):
        if not self.archive:
            return
        path, _ = QFileDialog.getSaveFileName(self, '성적표 저장', 'summary.csv', 'CSV (*.csv)')
        if path:
            try:
                export_summary(path, load_run(self.archive))
                self.status.setText(f'성적표 저장 완료 · {path}')
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.cancel()
            event.ignore()
        else:
            event.accept()


def format_details(row):
    submission = row.get('submission', {})
    lines = [f"학생: {row['student_id']}", f"총 배점: {row['max_score']}",
             f"제출 경로: {submission.get('resolved_path', '미확정')}",
             f"실행 파일: {submission.get('matched_file', '미확정')}"]
    if row.get('message') or submission.get('message'):
        lines.append(row.get('message') or submission['message'])
    for case in row.get('cases', []):
        lines.extend(['', f"[{case['case']}] {case['status']} · {case.get('points', 0)}/{case.get('max_score', 0)}점 · {case.get('duration_ms', 0)}ms"])
        if case.get('message'):
            lines.append(case['message'])
        if case.get('expected') is not None:
            lines.extend(['기대 출력:', case['expected'], '실제 출력:', case.get('actual', '')])
        if case.get('stderr'):
            lines.extend(['오류 출력:', case['stderr']])
        if case.get('expected_stderr') is not None:
            lines.extend(['기대 오류 출력:', case['expected_stderr']])
        lines.append(f"종료 코드: {case.get('returncode')} (기대 {case.get('expected_returncode', 0)})")
        for name, result in case.get('file_results', {}).items():
            lines.extend([f"파일 {name}: {'통과' if result['passed'] else '미통과'}",
                          '기대 내용:', result['expected'], '실제 내용:', result['actual'] if result['actual'] is not None else '(없음 또는 크기 초과)'])
    for change in row.get('overrides', []):
        lines.extend(['', f"점수 조정: {change['previous_score']} → {change['score']} · {change['by']}", change['reason'], change['at']])
    if submission.get('sha256'):
        lines.extend(['', '제출물 SHA-256: ' + submission['sha256']])
    return '\n'.join(lines)
