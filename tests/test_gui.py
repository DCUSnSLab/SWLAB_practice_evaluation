import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import time
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont
from gui import Gui, LoadWorker
from case_generator import TestMaker
from materials import MaterialsWindow


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.name == 'nt' and os.environ.get('WINDIR'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts/malgun.ttf'))
            cls.app.setFont(QFont('Malgun Gothic', 9))

    def setUp(self):
        config = patch.dict(os.environ, {'SWLAB_LLM_URL': 'https://example.invalid/v1',
            'SWLAB_LLM_MODEL': 'test-model', 'SWLAB_CONFIG': str(Path(tempfile.gettempdir()) / 'swlab-unused-settings.json')})
        config.start()
        self.addCleanup(config.stop)

    def test_windows_and_shutdown(self):
        window = Gui()
        maker = TestMaker()
        with patch('materials.build_catalog', return_value=[]):
            materials = MaterialsWindow()
        self.assertEqual(materials.selector.count(), 0)
        self.assertIn('PPTX', materials.content.toPlainText())
        self.assertTrue(maker.comboClass.isEditable())
        window.gradingDone([{'student': 'demo', 'case': 'example', 'status': 'passed',
                             'passed': True, 'actual': '<b>literal output</b>'}])
        self.assertIn('<b>literal output</b>', window.log_output.toPlainText())
        maker.close()
        materials.close()
        window.close()
        self.app.processEvents()
        self.assertFalse(window.worker_thread.isRunning())

    def test_job_completes_without_blocking_gui(self):
        window = Gui()
        received = []
        def work(progress):
            time.sleep(.1)
            progress(1)
            return ['finished']
        window.startJob(work, received.extend)
        self.assertFalse(window.btnGrade.isEnabled())
        deadline = time.monotonic() + 5
        while window.job.isRunning() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertEqual(received, ['finished'])
        self.assertTrue(window.btnGrade.isEnabled())
        window.close()

    def test_result_symbols_distinguish_partial_answers_and_ungraded_students(self):
        from types import SimpleNamespace
        with patch.object(Gui, 'refreshYearList'):
            window = Gui()
        try:
            students = ['all', 'partial', 'wrong', 'compile', 'missing', 'manual', 'waiting']
            window.case_report = SimpleNamespace(context={'students': students, 'case_count': 2}, state='running')
            window.results = []
            for student, outcomes in [('all', [True, True]), ('partial', [True, False]), ('wrong', [False, False])]:
                for index, passed in enumerate(outcomes):
                    window.results.append({'student': student, 'case': str(index),
                        'status': 'passed' if passed else 'wrong_answer', 'passed': passed})
            window.results.extend([
                {'student': 'compile', 'case': 'build', 'status': 'compile_error', 'passed': False},
                {'student': 'missing', 'case': 'setup', 'status': 'missing', 'passed': False},
                {'student': 'manual', 'case': 'review', 'status': 'manual_passed', 'passed': True}])
            window.refreshResultsTable()
            self.assertEqual(window.resultTable.horizontalHeaderItem(1).text(), '판정')
            self.assertEqual(window.resultTable.horizontalHeaderItem(2).text(), '기호')
            self.assertEqual([window.resultTable.item(i, 2).text() for i in range(7)],
                             ['O', '△', 'X', 'X', '—', '—', '—'])
            self.assertEqual(window.resultTable.item(1, 3).text(), '1 / 2')
            self.assertEqual(window.resultTable.item(1, 4).text(), '1')
            self.assertIn('일부', window.resultTable.item(1, 2).toolTip())
            window.case_report.state = 'cancelled'
            window.refreshResultsTable()
            self.assertEqual(window.resultTable.item(6, 1).text(), '미실행')
            self.assertEqual(window.resultTable.item(6, 2).text(), '—')
        finally:
            window.close()
            self.app.processEvents()

    def test_class_defaults_to_all_students_and_selection_keeps_problem(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp, patch.object(Gui, 'refreshYearList'), patch('paths.TESTCASES', Path(temp)):
            window = Gui()
            window.eval.get_student_list = lambda name: ['101', '102', '103']
            window.eval.get_student_chapters = lambda name, student: [] if student == '101' else ['chap4']
            window.eval.get_student_problems = lambda *args: ['prob2']
            window.eval.get_student_files = lambda *args: []
            window.comboClass.addItem('테스트 분반', 'system_3_2026')
            self.assertEqual(len(window.listStudents.selectedItems()), 3)
            self.assertEqual(window.btnGrade.text(), '선택 3명 일괄 채점')
            self.assertEqual(window.comboChapter.currentText(), 'chap4')
            self.assertEqual(window.selectedProblem(), 'prob2')
            window.btnClearSelection.click()
            self.assertEqual(len(window.listStudents.selectedItems()), 0)
            self.assertEqual(window.selectedProblem(), 'prob2')
            window.listStudents.item(1).setSelected(True)
            self.assertEqual(window.btnGrade.text(), '선택 1명 일괄 채점')
            window.btnSelectAll.click()
            self.assertEqual(window.selectionCount.text(), '선택 3명 / 전체 3명')
            window.close()

    def test_large_font_keeps_controls_on_screen(self):
        from ui_theme import apply_theme
        with patch.object(Gui, 'refreshYearList'):
            window = Gui()
            apply_theme(16)
            window.resize(1280, 800)
            self.app.processEvents()
            self.assertEqual(self.app.font().pointSize(), 16)
            self.assertLessEqual(window.width(), 1280)
            self.assertLessEqual(window.height(), 800)
            self.assertTrue(window.btnGrade.isVisible())
            window.close()
            apply_theme(12)

    def test_stop_batch_keeps_completed_student_and_marks_remaining(self):
        import tempfile
        from PyQt6.QtCore import QTimer
        from threading import Event
        from grader import Grader
        from reports import CaseReport
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for student in ('101', '102'):
                folder = root / 'origin/system_3_2026' / student / 'chap1/prob1'
                folder.mkdir(parents=True)
                (folder / 'main.py').write_text("print('ok')")
            cases = root / 'testcase/system/chap1/prob1'
            cases.mkdir(parents=True); (cases / 'output.txt').write_text('ok')
            with patch.object(Gui, 'refreshYearList'), patch('paths.ORIGIN', root / 'origin'), patch('paths.TESTCASES', root / 'testcase'), patch('reports.ROOT', root):
                window = Gui()
                window.eval.get_student_list = lambda *args: ['101', '102']
                window.eval.get_student_chapters = lambda *args: ['chap1']
                window.eval.get_student_problems = lambda *args: ['prob1']
                window.eval.get_student_files = lambda *args: ['main.py']
                window.comboClass.addItem('테스트 분반', 'system_3_2026')
                (window.radioWin if os.name == 'nt' else window.radioLinux).setChecked(True)
                entered, released = Event(), Event()
                original_grade = Grader.grade_student
                def controlled_grade(grader, *args, **kwargs):
                    entered.set()
                    if not released.wait(10):
                        raise RuntimeError('Test did not release the running student')
                    return original_grade(grader, *args, **kwargs)
                timer = QTimer(window)
                def stop_running_student():
                    if entered.is_set():
                        window.btnStop.click(); released.set(); timer.stop()
                timer.timeout.connect(stop_running_student)
                try:
                    with patch.object(Grader, 'grade_student', controlled_grade):
                        window.gradeSelected(); timer.start(10)
                        deadline = time.monotonic() + 15
                        while window.job.isRunning() and time.monotonic() < deadline:
                            self.app.processEvents(); time.sleep(.01)
                        self.app.processEvents()
                    _, saved = CaseReport.open(window.case_report.directory / 'run.json')
                    self.assertEqual(saved['state'], 'cancelled')
                    self.assertEqual(len(saved['results']), 1)
                    self.assertTrue(saved['results'][0]['passed'])
                    self.assertEqual(window.resultTable.item(1, 1).text(), '미실행')
                    window.resultTable.selectRow(0)
                    self.assertIn('기대 출력', window.resultDetail.toPlainText())
                    self.assertIn('중지됨', window.resultHeadline.text())
                finally:
                    timer.stop(); released.set()
                    if window.job: window.job.wait(15000)
                    self.app.processEvents(); window.close()

    def test_ai_generation_and_save_workflow(self):
        import tempfile
        from ai_case_generator import AICaseMaker
        from grader import Grader
        window = AICaseMaker('system', 'chap4', 'prob1')
        window.problem_text.setPlainText('Echo standard input.')
        bundle = {'summary': 'echo', 'review_notes': [], 'cases': [
            {'name': 'one', 'input': 'hello', 'expected': 'hello', 'args': [], 'fixtures': {}, 'files': {},
             'description': 'echo', 'comparison': 'exact', 'exit_code': 0}]}
        with patch('llm_cases.LLMClient.generate', return_value=bundle):
            window.generate()
            deadline = time.monotonic() + 5
            while window.job.isRunning() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.app.processEvents()
        self.assertEqual(window.table.rowCount(), 1)
        self.assertFalse(window.save_button.isEnabled())
        window.manual_review.setChecked(True)
        self.assertTrue(window.save_button.isEnabled())
        with tempfile.TemporaryDirectory() as temp, patch('ai_case_generator.case_path', return_value=Path(temp)):
            window.save(True)
            self.assertEqual(len(Grader().load_test_cases(temp)), 1)
            window.save(True)
            self.assertEqual(len(Grader().load_test_cases(temp)), 1)
            self.assertIn('재사용', window.status.text())
        window.close()

    def test_ai_verification_blocks_failures_and_becomes_stale_after_edit(self):
        from ai_case_generator import AICaseMaker
        from llm_cases import bundle_digest
        window = AICaseMaker('system', 'chap1', 'prob1')
        bundle = {'cases': [{'name': 'one', 'input': 'hello', 'expected': 'hello'}]}
        evidence = {'bundle_sha256': bundle_digest(bundle), 'repeated_runs': 2,
                    'corrections': [], 'wrong_programs': []}
        window.show_result((bundle, {'verification': evidence}))
        window.set_busy(False)
        self.assertTrue(window.save_button.isEnabled())
        self.assertIn('오답 탐지 범위 미검증', window.quality.text())
        window.editor.setPlainText(window.editor.toPlainText().replace('hello', 'changed'))
        self.assertFalse(window.save_button.isEnabled())
        window.show_result((bundle, {'verification_error': '오답이 모든 케이스 통과'}))
        window.manual_review.setChecked(True)
        self.assertFalse(window.save_button.isEnabled())
        window.save(True)
        self.assertIn('저장 실패', window.status.text())
        window.close()

    def test_light_theme_overrides_native_dark_palette_for_windows_and_popups(self):
        from PyQt6.QtGui import QPalette, QColor
        from PyQt6.QtWidgets import QWidget, QComboBox
        from ui_theme import apply_theme
        dark = QPalette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button):
                dark.setColor(group, role, QColor('#202020'))
        self.app.setPalette(dark)
        apply_theme(12, mode='light')
        window = QWidget()
        combo = QComboBox(window)
        combo.addItems(['항목 1', '항목 2'])
        combo.ensurePolished()
        combo.view().ensurePolished()
        for widget in (window, combo, combo.view()):
            for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
                palette = widget.palette()
                self.assertGreater(palette.color(group, QPalette.ColorRole.Base).lightness(), 220)
                self.assertLess(palette.color(group, QPalette.ColorRole.Text).lightness(), 130)
        self.assertGreater(window.palette().color(QPalette.ColorRole.Window).lightness(), 220)
        window.close()

    def test_reviewed_ai_cases_grade_and_autosave_from_main_window(self):
        import json
        import tempfile
        from grader import Grader
        from reports import CaseReport
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            origin = root / 'origin'
            for student, source in [('101', 'print(input())'), ('102', "print('wrong')")]:
                folder = origin / 'system_3_2026' / student / 'chap1' / 'prob1'
                folder.mkdir(parents=True)
                (folder / 'main.py').write_text(source)
            with patch.object(Gui, 'refreshYearList'), patch('paths.ORIGIN', origin), patch('paths.TESTCASES', root / 'testcase'), patch('reports.ROOT', root):
                window = Gui()
                for widget in (window.comboClass, window.comboChapter, window.comboProblem, window.listStudents):
                    widget.blockSignals(True)
                window.comboClass.addItem('system_3', 'system_3_2026')
                window.comboChapter.addItem('chap1')
                window.comboProblem.addItem('prob1')
                window.comboProblem.show()
                window.listStudents.addItems(['101', '102'])
                window.listStudents.selectAll()
                for widget in (window.comboClass, window.comboChapter, window.comboProblem, window.listStudents):
                    widget.blockSignals(False)
                window.radioWin.setChecked(os.name == 'nt')
                window.radioLinux.setChecked(os.name != 'nt')
                window.openAIMaker()
                maker = window.ai_maker
                bundle = {'summary': 'echo', 'review_notes': [], 'cases': [
                    {'name': 'echo', 'input': 'hello', 'expected': 'hello', 'args': [], 'fixtures': {}, 'files': {},
                     'description': 'echo', 'comparison': 'trim', 'exit_code': 0}]}
                maker.show_result((bundle, {}))
                maker.save(False)
                maker.manual_review.setChecked(True)
                maker.save(True)
                self.assertEqual(len(Grader().load_test_cases(window.txtTestCasePath.text())), 1)
                self.assertIn('활성 케이스 1개', window.case_info.text())
                self.assertIn('일괄 채점', maker.status.text())
                window.gradeSelected()
                deadline = time.monotonic() + 10
                while window.job.isRunning() and time.monotonic() < deadline:
                    self.app.processEvents(); time.sleep(.01)
                self.app.processEvents()
                self.assertFalse(window.job.isRunning())
                archive = window.case_report.directory / 'run.json'
                _, saved = CaseReport.open(archive)
                self.assertEqual(saved['state'], 'completed', saved.get('error'))
                self.assertEqual([r['passed'] for r in saved['results']], [True, False])
                self.assertTrue(archive.with_name('cases.csv').is_file())
                self.assertTrue(archive.with_name('summary.csv').is_file())
                self.assertIn(str(archive.parent), window.report_location.text())
                window.results = []
                with patch('gui.QFileDialog.getOpenFileName', return_value=(str(archive), '')):
                    window.readCaseReport()
                self.assertEqual(len(window.results), 2)
                if os.environ.get('SWLAB_TEST_DOCKER') == '1':
                    window.radioDocker.setChecked(True)
                    window.gradeSelected()
                    deadline = time.monotonic() + 30
                    while window.job.isRunning() and time.monotonic() < deadline:
                        self.app.processEvents(); time.sleep(.01)
                    self.app.processEvents()
                    self.assertFalse(window.job.isRunning())
                    _, docker_saved = CaseReport.open(window.case_report.directory / 'run.json')
                    self.assertEqual(docker_saved['state'], 'completed', docker_saved.get('error'))
                    self.assertEqual([r['passed'] for r in docker_saved['results']], [True, False])
                maker.close(); window.close()

    def test_qualitative_batch_autosave_and_confirm(self):
        import tempfile
        from copy import deepcopy
        from qualitative_gui import QualitativeWindow
        from qualitative import DEFAULT_RUBRIC,validate_review,load_reviews
        raw={'summary':'총평','strengths':[],'improvements':[],'uncertainties':[],
             'criteria':[{'id':r['id'],'score':r['max_score']/2,'reason':'근거',
                          'evidence':[{'file':'main.c','line':1}]} for r in DEFAULT_RUBRIC]}
        result=validate_review(raw,DEFAULT_RUBRIC,{'main.c':'int main(){}'})
        result.update(status='ai_proposed',final_score=None,reviewer_note='')
        with tempfile.TemporaryDirectory() as temp, patch('qualitative_gui.ROOT',Path(temp)):
            Path(temp,'main.c').write_text('int main(){}')
            window=QualitativeWindow([{'student':'demo','path':temp,'chapter':'chap4','problem':'prob2'}])
            window.problem_text.setPlainText('파일을 복사한다.')
            with patch('qualitative.review_sources',return_value=deepcopy(result)):
                window.start()
                deadline=time.monotonic()+5
                while window.worker.isRunning() and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.01)
                self.app.processEvents()
            self.assertEqual(len(window.rows),1)
            self.assertTrue(window.archive.is_file())
            self.assertIsNone(load_reviews(window.archive)['results'][0]['final_score'])
            window.table.selectRow(0);self.app.processEvents()
            window.final_score.setValue(75);window.note.setPlainText('검토 완료 후 조정');window.confirm()
            saved=load_reviews(window.archive)['results'][0]
            self.assertEqual(saved['suggested_score'],50)
            self.assertEqual(saved['final_score'],75)
            self.assertEqual(saved['status'],'confirmed')
            window.close()

    def test_import_failure_still_completes(self):
        worker = LoadWorker()
        done, errors = [], []
        worker.done_message.connect(lambda: done.append(True))
        worker.log_message.connect(errors.append)
        worker.do_work('invalid-name.csv')
        self.assertEqual(done, [True])
        self.assertTrue(any('Error:' in message for message in errors))

    def test_invalid_llm_config_shows_error_without_closing_windows(self):
        from ai_case_generator import AICaseMaker
        from qualitative_gui import QualitativeWindow
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'settings.local.json'
            config.write_text('invalid json', encoding='utf-8')
            with patch.dict(os.environ, {'SWLAB_CONFIG': str(config)}):
                for constructor in (AICaseMaker, lambda: QualitativeWindow([])):
                    window = constructor()
                    try:
                        self.assertIn('로컬 설정 파일', window.status.text())
                        self.assertEqual(window.url.text(), '')
                    finally:
                        window.close()

    def test_manifest_grading_review_and_reopen(self):
        import tempfile
        from grading_window import GradingWindow
        from core.record import load_run
        from paths import ROOT
        submissions = [{'student_id': p.name, 'path': str(p)} for p in sorted((ROOT / 'examples/manifest_students').iterdir())]
        with tempfile.TemporaryDirectory() as temp, patch('core.service.ROOT', Path(temp)):
            window = GradingWindow(submissions)
            window.mode.setCurrentText('windows' if os.name == 'nt' else 'linux')
            self.assertEqual(window.table.rowCount(), 3)
            window.start()
            self.assertFalse(window.start_button.isEnabled())
            deadline = time.monotonic() + 15
            while window.worker.isRunning() and time.monotonic() < deadline:
                self.app.processEvents(); time.sleep(.01)
            self.app.processEvents()
            self.assertFalse(window.worker.isRunning())
            self.assertIsNotNone(window.archive, window.status.text())
            self.assertEqual(window.rows[2]['auto_score'], 6)
            window.table.selectRow(2); self.app.processEvents()
            self.assertIn('negative', window.detail.toPlainText())
            window.score.setValue(8)
            window.reviewer.setText('TA'); window.reason.setText('검토 후 부분 인정')
            window.adjust()
            saved = load_run(window.archive)
            self.assertEqual(saved['results'][2]['auto_score'], 6)
            self.assertEqual(saved['results'][2]['final_score'], 8)
            archive = str(window.archive)
            window.preview()
            with patch('grading_window.QFileDialog.getOpenFileName', return_value=(archive, 'JSON')):
                window.open_record()
            self.assertEqual(window.rows[2]['final_score'], 8)
            self.assertIn('부분 인정', window.detail.toPlainText())
            window.close()


if __name__ == '__main__':
    unittest.main()
