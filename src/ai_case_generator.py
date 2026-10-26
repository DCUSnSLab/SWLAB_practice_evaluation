"""Instructor workflow: select slides -> Qwen cases -> reference oracle -> review/save."""
import json
import hashlib
import re
from pathlib import Path
from PyQt6.QtCore import QSettings, pyqtSignal, Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QComboBox, QSpinBox, QPushButton, QTextEdit, QPlainTextEdit, QFileDialog,
    QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QCheckBox, QCompleter, QDialog, QGridLayout)
from llm_cases import LLMClient, validate_bundle, verify_with_reference, verification_matches, save_bundle, provenance
from llm_config import llm_settings
from materials import build_catalog
from paths import case_path, lecture_name
from case_catalog import target_label
from slide_picker import SlidePicker
from reference_program import snapshot_reference


class AICaseMaker(QWidget):
    cases_saved = pyqtSignal(object)
    def __init__(self, class_name='system', chapter='', problem=''):
        super().__init__()
        self.setWindowTitle('Qwen 테스트 케이스 자동 생성')
        self.resize(1150, 820)
        self.job = None
        self.busy = False
        self.wrong_solutions = []
        self.reference_files = ()
        self.generated_metadata = {}
        self.setting_preview = False
        self.problem_source = '직접 입력'
        self.slide_selection = None
        self.settings = QSettings('SWLAB', 'PracticeEvaluation')
        self.decks = build_catalog()
        root = QVBoxLayout(self)
        server = QHBoxLayout()
        config_error = ''
        try:
            config = llm_settings(self.settings)
        except ValueError as error:
            config = {'url': '', 'model': ''}
            config_error = str(error)
        self.url = QLineEdit(config['url'])
        self.url.setPlaceholderText('LLM 서버 URL 입력')
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem(config['model'])
        self.model.lineEdit().setPlaceholderText('모델명 입력 또는 서버 연결 확인')
        self.connect_button = QPushButton('서버 연결 확인')
        self.connect_button.clicked.connect(self.connect_server)
        server.addWidget(QLabel('서버'))
        server.addWidget(self.url, 2)
        server.addWidget(QLabel('모델'))
        server.addWidget(self.model, 2)
        server.addWidget(self.connect_button)
        root.addLayout(server)
        root.addWidget(QLabel('선택한 문제 설명만 서버에 전송합니다. 교수자 기준 코드는 이 PC의 Docker에서 실행합니다.'))
        source = QHBoxLayout()
        self.load_button = QPushButton('슬라이드 목록에서 문제 선택…')
        self.load_button.clicked.connect(self.load_problem)
        self.source_summary = QLabel('직접 입력 또는 슬라이드 선택 · 여러 쪽을 클릭으로 선택할 수 있습니다.')
        self.source_summary.setWordWrap(True)
        source.addWidget(self.load_button); source.addWidget(self.source_summary, 1)
        root.addLayout(source)
        self.target_summary = QLabel()
        self.target_summary.setObjectName('verificationStatus')
        self.target_summary.setWordWrap(True)
        self.target_summary.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.target_summary)
        split = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel('문제 설명 / 입력·출력 조건'))
        self.problem_text = QTextEdit()
        self.problem_text.setPlaceholderText('문제를 입력하거나 위에서 PPT와 페이지를 선택하세요.')
        left_layout.addWidget(self.problem_text, 1)
        form = QGridLayout()
        self.course = QLineEdit(class_name or 'system')
        self.chapter = QLineEdit(chapter)
        self.problem = QLineEdit(problem)
        chapters = sorted({f"chap{d['chapter']}" for d in self.decks if d['chapter'] is not None})
        self.chapter.setCompleter(QCompleter(chapters, self.chapter))
        self.chapter.setPlaceholderText('예: chap3 또는 3')
        self.problem.setPlaceholderText('예: prob1 또는 1 (과제는 hw1)')
        self.count = QSpinBox()
        self.count.setRange(1, 10)
        self.count.setValue(8)
        form.addWidget(QLabel('과목 / 분반'), 0, 0); form.addWidget(self.course, 0, 1)
        form.addWidget(QLabel('케이스 수'), 0, 2); form.addWidget(self.count, 0, 3)
        form.addWidget(QLabel('장 폴더'), 1, 0); form.addWidget(self.chapter, 1, 1)
        form.addWidget(QLabel('문제 폴더'), 1, 2); form.addWidget(self.problem, 1, 3)
        form.setColumnStretch(1, 1); form.setColumnStretch(3, 1)
        left_layout.addLayout(form)
        reference = QHBoxLayout()
        self.reference = QLineEdit()
        self.reference.setReadOnly(True)
        self.reference.setPlaceholderText('교수자 기준 코드 파일들(선택)')
        self.reference_entry = QComboBox()
        self.reference_entry.setMinimumContentsLength(6)
        self.reference_entry.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.reference_entry.setToolTip('실행 기준 파일. C는 선택한 .c 파일들을 함께 컴파일하고, Python은 이 파일을 실행합니다. 한 프로그램의 소스·헤더를 함께 선택하세요.')
        self.reference_entry.currentIndexChanged.connect(self.reference_changed)
        self.reference_browse = QPushButton('파일 선택…')
        self.reference_browse.clicked.connect(self.browse_reference)
        self.reference_clear = QPushButton('해제')
        self.reference_clear.clicked.connect(lambda: self.set_reference_files([]))
        reference.addWidget(self.reference, 1)
        reference.addWidget(self.reference_entry)
        reference.addWidget(self.reference_browse)
        reference.addWidget(self.reference_clear)
        left_layout.addLayout(reference)
        wrong = QHBoxLayout()
        self.wrong_label = QLabel('오답 예제: 선택 안 됨 · 검사 범위 미검증')
        self.wrong_label.setWordWrap(True)
        self.wrong_button = QPushButton('오답 예제 선택')
        self.wrong_button.clicked.connect(self.browse_wrong_solutions)
        self.clear_wrong_button = QPushButton('해제')
        self.clear_wrong_button.clicked.connect(self.clear_wrong_solutions)
        wrong.addWidget(self.wrong_label, 1)
        wrong.addWidget(self.wrong_button)
        wrong.addWidget(self.clear_wrong_button)
        left_layout.addLayout(wrong)
        self.generate_button = QPushButton('Qwen으로 테스트 케이스 생성')
        self.generate_button.clicked.connect(self.generate)
        left_layout.addWidget(self.generate_button)
        self.reference_button = QPushButton('기준 코드로 정답·오답 탐지 검증')
        self.reference_button.clicked.connect(self.apply_reference)
        left_layout.addWidget(self.reference_button)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.quality = QLabel('기대값 미검증 · 생성 후 기준 코드로 검증하세요.')
        self.quality.setObjectName('verificationStatus')
        self.quality.setWordWrap(True)
        right_layout.addWidget(self.quality)
        self.tabs = QTabWidget()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['케이스', '검사 목적', '인자 / 입력', '기대 결과', '보조 파일'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemActivated.connect(lambda item: self.show_case_detail(item.row()))
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText('생성된 케이스를 여기서 확인·수정할 수 있습니다.')
        self.editor.textChanged.connect(self.preview_edited)
        self.tabs.addTab(self.table, '케이스 요약')
        self.tabs.addTab(self.editor, 'JSON 편집')
        self.tabs.currentChanged.connect(self.refresh_table)
        right_layout.addWidget(self.tabs, 1)
        self.detail_button = QPushButton('선택 케이스 상세 보기 (입력·출력·파일 전체)')
        self.detail_button.clicked.connect(lambda: self.show_case_detail(self.table.currentRow()))
        right_layout.addWidget(self.detail_button)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.tabs.addTab(self.notes, '검토 메모')
        self.manual_review = QCheckBox('기준 코드 없이 기대값을 직접 확인했습니다 (수동 검토)')
        self.manual_review.toggled.connect(lambda: self.update_quality())
        right_layout.addWidget(self.manual_review)
        save_row = QHBoxLayout()
        self.draft_button = QPushButton('초안 저장 · 채점 제외')
        self.save_button = QPushButton('검증 후 채점에 추가')
        self.draft_button.clicked.connect(lambda: self.save(False))
        self.save_button.clicked.connect(lambda: self.save(True))
        save_row.addWidget(self.draft_button)
        save_row.addWidget(self.save_button)
        right_layout.addLayout(save_row)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([450, 650])
        root.addWidget(split, 1)
        self.status = QLabel(config_error or '문제를 선택하고 생성하세요. 기준 코드가 없으면 Qwen이 제안한 기대값을 검토 후 사용합니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        for field in (self.course, self.chapter, self.problem):
            field.textChanged.connect(self.context_changed)
        self.chapter.editingFinished.connect(self.normalize_target)
        self.problem.editingFinished.connect(self.normalize_target)
        self.problem_text.textChanged.connect(self.context_changed)
        self.reference.textChanged.connect(self.reference_text_changed)
        self.context_changed()
        self.set_busy(False)

    def client(self, require_model=True):
        return LLMClient(self.url.text().strip(), self.model.currentText().strip(), require_model=require_model)

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.url, self.model, self.connect_button, self.reference_browse,
                       self.reference_entry, self.reference_clear,
                       self.load_button, self.problem_text, self.course, self.chapter, self.problem,
                       self.count, self.reference, self.generate_button, self.editor,
                       self.wrong_button, self.clear_wrong_button, self.manual_review):
            widget.setEnabled(not busy)
        has_preview = bool(self.editor.toPlainText().strip())
        for button in (self.reference_button, self.save_button, self.draft_button):
            button.setEnabled(not busy and has_preview)
        self.update_quality()

    def update_quality(self):
        try:
            bundle = self.read_preview()
            verified = self.verification_current(bundle)
            has_answers = all(c['expected'] is not None or c['files'] for c in bundle['cases'])
        except ValueError:
            self.save_button.setEnabled(False)
            self.draft_button.setEnabled(False)
            self.quality.setText('유효한 케이스가 없습니다. 생성하거나 JSON 내용을 확인하세요.')
            return
        stale = self.context_error()
        self.draft_button.setEnabled(not self.busy and not stale)
        failed = self.generated_metadata.get('verification_error')
        if stale:
            label = stale
        elif failed:
            label = '검증 실패 · 채점 추가 불가: ' + failed
        elif verified:
            evidence = self.generated_metadata['verification']
            detection = f"오답 예제 {len(evidence['wrong_programs'])}개 탐지" if evidence['wrong_programs'] else '오답 탐지 범위 미검증'
            label = f"기준 코드 2회 일치 · 기대값 {len(evidence['corrections'])}개 수정 · {detection}"
        elif self.generated_metadata.get('verification'):
            label = '기준 코드 파일 또는 케이스가 변경되었습니다. 다시 검증하세요.'
        else:
            label = '기대값 미검증 · AI 추정값입니다. 기준 코드로 검증하거나 직접 확인 후 수동 검토를 표시하세요.'
        self.quality.setText(label)
        self.save_button.setText('검증된 케이스 · 채점에 추가' if verified else '수동 검토 · 채점에 추가')
        self.save_button.setEnabled(not self.busy and has_answers and not failed and not stale and (verified or self.manual_review.isChecked()))

    def browse_wrong_solutions(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '검사할 오답 예제 (각 예제는 별도 폴더에 두세요)', '', 'Source (*.c *.py)')
        if paths:
            self.wrong_solutions = paths
            self.wrong_label.setText(f'오답 예제 {len(paths)}개 선택 · 기준 코드와 함께 검증합니다.')
            self.invalidate_verification()

    def clear_wrong_solutions(self):
        self.wrong_solutions = []
        self.wrong_label.setText('오답 예제: 선택 안 됨 · 검사 범위 미검증')
        self.invalidate_verification()

    def invalidate_verification(self):
        self.generated_metadata.pop('verification', None)
        self.generated_metadata.pop('verification_error', None)
        self.manual_review.setChecked(False)
        self.update_quality()

    def run_job(self, function, callback, status):
        if self.job and self.job.isRunning():
            return
        from gui import Job
        self.job = Job(function, self)
        self.set_busy(True)
        self.status.setText(status)
        self.job.result.connect(callback)
        self.job.failed.connect(lambda text: self.status.setText('오류: ' + text))
        self.job.progress.connect(lambda n: self.status.setText(f'기준 코드 검증: {n}개 완료'))
        self.job.finished.connect(lambda: self.set_busy(False))
        self.job.start()

    def connect_server(self):
        try:
            client = self.client(require_model=False)
        except ValueError as error:
            self.status.setText(str(error))
            return
        def connected(models):
            current = self.model.currentText()
            self.model.clear()
            self.model.addItems(models)
            if current in models:
                self.model.setCurrentText(current)
            self.status.setText('서버 연결 성공: ' + ', '.join(models))
            self.settings.setValue('llm_url', client.base_url)
            self.settings.setValue('llm_model', self.model.currentText())
        self.run_job(lambda progress: client.models(), connected, '모델 목록 조회 중…')

    def normalize_target(self):
        if self.chapter.text().strip().isdigit():
            self.chapter.setText('chap' + str(int(self.chapter.text().strip())))
        if self.problem.text().strip().isdigit():
            self.problem.setText('prob' + str(int(self.problem.text().strip())))

    def read_target(self):
        values = [field.text().strip() for field in (self.course, self.chapter, self.problem)]
        for name in values:
            if (not name or name in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                    or name.endswith((' ', '.')) or name.split('.')[0].upper() in
                    {'CON', 'PRN', 'AUX', 'NUL', *{f'COM{i}' for i in range(1, 10)}, *{f'LPT{i}' for i in range(1, 10)}}):
                raise ValueError('과목·장·문제 폴더명을 확인하세요. 예: system / chap3 / prob1')
        return dict(course=lecture_name(values[0]), chapter=values[1], problem=values[2])

    def context_error(self):
        try:
            target = self.read_target()
        except ValueError as error:
            return str(error)
        original = self.generated_metadata.get('target')
        if original and original != target:
            return '생성 후 저장 대상이 바뀌었습니다. 현재 장·문제로 다시 생성하세요.'
        digest = self.generated_metadata.get('problem_sha256')
        if digest and digest != hashlib.sha256(self.problem_text.toPlainText().encode('utf-8')).hexdigest():
            return '생성 후 문제 설명이 바뀌었습니다. 변경한 설명으로 다시 생성하세요.'
        if self.generated_metadata.get('source') and self.generated_metadata['source'] != self.source_label():
            return '생성 후 원본 슬라이드가 바뀌었습니다. 선택한 슬라이드로 다시 생성하세요.'
        return ''

    def source_target_error(self):
        selection = self.slide_selection
        if not selection:
            return ''
        target = self.read_target()
        if selection['chapter'] is not None and target['chapter'] != f"chap{selection['chapter']}":
            return '선택한 슬라이드의 장과 저장 대상 장이 다릅니다. 장을 확인하세요.'
        number = re.fullmatch(r'(?:prob|prod|hw)(\d+)', target['problem'])
        if selection['problem'] and number and int(number[1]) != selection['problem'][1]:
            return '선택한 슬라이드의 문제 번호와 저장 대상 번호가 다릅니다. 문제 번호를 확인하세요.'
        return ''

    def context_changed(self):
        label = target_label(self.chapter.text().strip(), self.problem.text().strip())
        try:
            target = self.read_target()
            destination = case_path(target['course'], target['chapter'], target['problem'])
            self.target_summary.setText(f"생성·저장 대상: {self.course.text().strip()} · {label}\n저장 폴더: {destination}")
            mismatch = self.source_target_error()
            if mismatch:
                self.target_summary.setText(self.target_summary.text() + '\n' + mismatch)
        except ValueError:
            self.target_summary.setText(f'생성·저장 대상: {label} · 과목·장·문제를 먼저 지정하세요.')
        if self.generated_metadata:
            self.manual_review.setChecked(False)
        self.update_quality()

    def reference_changed(self):
        if self.generated_metadata.get('verification') or self.generated_metadata.get('verification_error'):
            self.invalidate_verification()

    def reference_text_changed(self):
        self.reference_files = ()
        self.reference_entry.blockSignals(True)
        self.reference_entry.clear()
        self.reference_entry.blockSignals(False)
        self.reference_changed()

    def set_reference_files(self, paths):
        try:
            program = snapshot_reference(paths) if paths else None
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        self.reference_files = tuple(str(program.root / file.name) for file in program.files) if program else ()
        self.reference.blockSignals(True)
        self.reference_entry.blockSignals(True)
        self.reference_entry.clear()
        if program:
            for file in program.files:
                if file.name.endswith(('.c', '.py')):
                    self.reference_entry.addItem(file.name, file.name)
            self.reference_entry.setCurrentIndex(self.reference_entry.findData(program.entry))
            self.reference.setText(f'{len(program.files)}개 파일 · ' + ', '.join(file.name for file in program.files))
            self.reference.setCursorPosition(0)
        else:
            self.reference.clear()
        self.reference.setToolTip('\n'.join(self.reference_files))
        self.reference.blockSignals(False)
        self.reference_entry.blockSignals(False)
        self.invalidate_verification()

    def selected_reference(self):
        if self.reference_files:
            return snapshot_reference(self.reference_files, self.reference_entry.currentData())
        path = self.reference.text().strip()
        return snapshot_reference(path) if path else None

    def verification_current(self, bundle):
        try:
            reference = self.selected_reference()
        except (OSError, ValueError):
            return False
        return verification_matches(bundle, self.generated_metadata, reference)

    def load_problem(self):
        picker = SlidePicker(self.decks, self.chapter.text().strip(), self.problem.text().strip(),
                             self.slide_selection, self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.apply_slide_selection(picker.selection)

    def apply_slide_selection(self, selection):
        old_chapter = self.chapter.text().strip()
        self.slide_selection = selection
        if selection['chapter'] is not None:
            self.chapter.setText(f"chap{selection['chapter']}")
        suggestion = selection['problem']
        if suggestion:
            kind, number = suggestion
            current = re.fullmatch(r'(prob|prod|hw)(\d+)', self.problem.text().strip())
            # Preserve the existing submission folder alias (e.g. prod1).
            if not (old_chapter == self.chapter.text().strip() and current and int(current[2]) == number
                    and (current[1] == 'hw') == (kind == 'hw')):
                self.problem.setText(f'{kind}{number}')
        elif old_chapter != self.chapter.text().strip():
            self.problem.clear()
        self.problem_source = selection['source'] + ':' + ','.join(map(str, selection['pages']))
        self.problem_text.setPlainText(selection['text'])
        warning = ' · 이미지 내용은 원본에서 확인하세요' if selection['has_images'] else ''
        if not suggestion:
            warning += ' · 문제 번호 미표기: 저장 대상 문제 번호를 직접 확인하세요'
        self.source_summary.setText(f"{selection['title']} · {', '.join(map(str, selection['pages']))}쪽{warning}")
        self.status.setText('슬라이드를 불러왔습니다. 위 생성·저장 대상의 장과 문제 번호를 확인하세요.')
        self.context_changed()

    def browse_reference(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '한 프로그램의 교수자 기준 소스·헤더를 함께 선택', '', 'Source (*.c *.h *.py)')
        if paths:
            self.set_reference_files(paths)

    def source_label(self):
        return self.problem_source

    def generate(self):
        try:
            self.normalize_target()
            target = self.read_target()
            if self.source_target_error():
                raise ValueError(self.source_target_error())
            client = self.client()
            problem = self.problem_text.toPlainText()
            if not problem.strip():
                raise ValueError('문제 설명을 입력하세요.')
            reference = self.selected_reference()
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        count = self.count.value()
        wrong_solutions = tuple(self.wrong_solutions)
        metadata = provenance(client, problem, self.source_label())
        metadata['target'] = target
        metadata['slide_selection'] = {k: v for k, v in (self.slide_selection or {}).items() if k != 'text'}
        def work(progress):
            bundle = client.generate(problem, count)
            if reference:
                try:
                    bundle, metadata['verification'] = verify_with_reference(bundle, reference, wrong_solutions, progress)
                    metadata['expected_origin'] = 'instructor_reference'
                except (OSError, ValueError) as error:
                    # Preserve the generated draft even when a reference program fails.
                    bundle['review_notes'].append('기준 코드 검증 실패: ' + str(error))
                    metadata['verification_error'] = str(error)
            return bundle, metadata
        self.run_job(work, self.show_result, 'Qwen이 정상·경계·예외 케이스를 생성 중입니다…')

    def show_result(self, result):
        bundle, metadata = result
        self.generated_metadata = dict(metadata)
        if 'target' not in self.generated_metadata:
            try: self.generated_metadata['target'] = self.read_target()
            except ValueError: pass
        self.generated_metadata.setdefault('problem_sha256', hashlib.sha256(self.problem_text.toPlainText().encode('utf-8')).hexdigest())
        self.setting_preview = True
        self.editor.setPlainText(json.dumps(bundle, ensure_ascii=False, indent=2))
        self.setting_preview = False
        self.manual_review.setChecked(False)
        self.refresh_table()
        verified = self.verification_current(self.read_preview())
        label = '기준 코드로 검증한 기대값' if verified else '미검증 기대값'
        if self.generated_metadata.get('verification_error'):
            label = '검증 실패 · 오류를 수정하고 다시 검증하세요'
        self.status.setText(f'{len(bundle["cases"])}개 · {label}')
        self.update_quality()

    def preview_edited(self):
        if not self.setting_preview:
            self.generated_metadata['expected_origin'] = 'edited_by_instructor'
            self.invalidate_verification()
            self.set_busy(False)

    def read_preview(self):
        return validate_bundle(json.loads(self.editor.toPlainText()))

    def refresh_table(self, *args):
        try:
            bundle = self.read_preview()
        except ValueError:
            return
        self.table.setRowCount(len(bundle['cases']))
        for row, case in enumerate(bundle['cases']):
            expected = ('표준출력: ' + repr(case['expected']) if case['expected'] is not None else '표준출력 검사 없음')
            if case['files']:
                expected += '\n파일: ' + json.dumps(case['files'], ensure_ascii=False)
            if case['expected'] is None and not case['files']:
                expected = '검토 필요: 기대 결과 없음'
            for column, value in enumerate([case['name'], case['description'],
                    json.dumps(case['args'], ensure_ascii=False) + '\n' + case['input'], expected,
                    ', '.join(case['fixtures']) or '없음']):
                item = QTableWidgetItem(value[:500])
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
        self.notes.setPlainText(bundle['summary'] + '\n\n' + '\n'.join(bundle['review_notes']))
        self.update_quality()

    def show_case_detail(self, row):
        try:
            bundle = self.read_preview()
        except ValueError:
            return
        if not 0 <= row < len(bundle['cases']):
            self.status.setText('요약 표에서 확인할 케이스를 먼저 선택하세요.'); return
        self.detail_dialog = QDialog(self)
        self.detail_dialog.setWindowTitle('케이스 전체 내용 · ' + bundle['cases'][row]['name'])
        self.detail_dialog.resize(850, 650)
        layout = QVBoxLayout(self.detail_dialog)
        detail = QPlainTextEdit(); detail.setReadOnly(True)
        detail.setPlainText(json.dumps(bundle['cases'][row], ensure_ascii=False, indent=2))
        layout.addWidget(detail)
        self.detail_dialog.show()

    def apply_reference(self):
        try:
            if self.context_error():
                raise ValueError(self.context_error())
            bundle = self.read_preview()
            solution = self.selected_reference()
            if not solution:
                raise ValueError('교수자 기준 코드 파일을 선택하세요.')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        metadata = dict(self.generated_metadata, expected_origin='instructor_reference')
        metadata.pop('verification', None)
        metadata.pop('verification_error', None)
        wrong_solutions = tuple(self.wrong_solutions)
        def work(progress):
            try:
                verified, metadata['verification'] = verify_with_reference(bundle, solution, wrong_solutions, progress)
                return verified, metadata
            except (OSError, ValueError) as error:
                metadata['verification_error'] = str(error)
                return bundle, metadata
        self.run_job(work,
                     self.show_result, '교수자 기준 코드에서 기대 결과를 계산 중…')

    def save(self, enabled):
        try:
            self.normalize_target()
            if self.context_error():
                raise ValueError(self.context_error())
            bundle = self.read_preview()
            if enabled:
                if self.generated_metadata.get('verification_error'):
                    raise ValueError('기준 코드 검증에 실패했습니다. 수정 후 다시 검증하세요.')
                if not self.verification_current(bundle) and not self.manual_review.isChecked():
                    raise ValueError('기준 코드로 검증하거나 기대값을 직접 확인하고 수동 검토를 표시하세요.')
            for field in (self.course, self.chapter, self.problem):
                name = field.text().strip()
                if not name or Path(name).name != name or '/' in name or '\\' in name or name in ('.', '..'):
                    raise ValueError('과목·장·문제 폴더명을 입력하세요.')
            destination = case_path(self.course.text().strip(), self.chapter.text().strip(), self.problem.text().strip())
            metadata = dict(self.generated_metadata)
            if enabled and not self.verification_current(bundle):
                metadata['expected_origin'] = 'manually_reviewed'
                metadata.pop('verification', None)
            existing = set(destination.glob('*/case.json')) if destination.exists() else set()
            paths = save_bundle(bundle, destination, enabled, metadata)
            reused = sum((p / 'case.json') in existing for p in paths)
            self.cases_saved.emit({'destination': str(destination), 'enabled': enabled, 'count': len(paths),
                                  'class_name': self.course.text().strip(), 'chapter': self.chapter.text().strip(),
                                  'problem': self.problem.text().strip()})
            message = '메인 화면에서 대상 학생 수를 확인하고 ‘일괄 채점’ 버튼을 누르세요.' if enabled else '초안은 채점에서 제외됩니다.'
            self.status.setText(f'{len(paths)}개 {"활성 케이스" if enabled else "비활성 초안"} 저장 (기존 동일 케이스 {reused}개 재사용): {destination}\n{message}')
        except (OSError, ValueError) as error:
            self.status.setText('저장 실패: ' + str(error))

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            self.status.setText('생성 작업이 끝난 후 닫을 수 있습니다.')
            event.ignore()
        else:
            event.accept()
