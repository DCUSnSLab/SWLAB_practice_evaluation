import csv
from copy import deepcopy
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QLineEdit, QDoubleSpinBox, QPushButton
import db
from gui import Gui
from latest_gradebook import LatestGradebook
from midterm import load_suite
from midterm_scoring import settings


class LatestGradebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        support.isolate(self)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = dict(class_name='system_3_2026', chapter='midterm', problem='__all__')
        self.windows = []
        self.addCleanup(self.close_windows)
        for target, value in [('paths.ORIGIN', self.root / 'origin'), ('paths.TESTCASES', self.root / 'cases')]:
            mock = patch(target, value); mock.start(); self.addCleanup(mock.stop)

    def close_windows(self):
        for window in self.windows:
            window.close()
        self.app.processEvents()

    def save(self, name, day, problem='__all__', students=('101', '102'), passed=True, state='completed',
             overrides=None, bundle=None):
        bundle = bundle or load_suite(problem)
        context = dict(self.scope, problem=problem, students=list(students), midterm_suite=bundle,
                       midterm_scoring=settings(), case_count=len(bundle['cases']))
        rows = [dict(student=s, student_name=f'학생{s}', case=f'{c["target_file"]} / {c["name"]}',
                     target_file=c['target_file'], passed=passed, status='passed' if passed else 'wrong_answer')
                for s in students for c in bundle['cases']]
        db.save_run(name, context, rows, state, overrides=overrides,
                    created_at=f'2026-10-{day:02}T00:00:00+00:00', directory=self.root / name)
        return context, rows

    def book(self, scope=None):
        return LatestGradebook(scope or self.scope, ['101', '102', '103'])

    def window(self):
        with patch.object(Gui, 'refreshYearList'):
            window = Gui()
        self.windows.append(window)
        window.eval.get_student_list = lambda *args: ['101', '102', '103']
        window.eval.get_student_chapters = lambda *args: ['midterm']
        window.eval.get_student_problems = lambda *args: []
        window.eval.get_student_files = lambda *args: []
        window.comboClass.addItem('테스트 분반', 'system_3_2026')
        return window

    def test_per_student_problem_results_and_independent_latest_adjustments_are_combined(self):
        context, rows = self.save('whole', 20)
        self.save('retry_one_student_one_file', 21, 'copy.c', ('101',), False)
        overrides = {'101': {'copy.c': [dict(previous_score=10, score=9, reviewer='teacher', reason='파일 확인',
                                          at='2026-10-22T00:00:00+00:00')]},
                     '102': {'bookquery.c': [dict(previous_score=10, score=8, reviewer='teacher', reason='조회 확인',
                                                at='2026-10-22T00:00:00+00:00')]}}
        # Updating an older run must update its manual marks, not its execution age.
        db.save_run('whole', context, rows, 'completed', overrides=overrides)
        book = self.book()
        scores = {r['student']: r for r in book.scores()}
        self.assertEqual((scores['101']['auto_score'], scores['101']['final_score']), (65, 74))
        self.assertEqual((scores['102']['auto_score'], scores['102']['final_score']), (75, 73))
        self.assertEqual(book.sources['101', 'copy.c']['record']['id'], 'retry_one_student_one_file')
        self.assertEqual(book.sources['102', 'copy.c']['record']['id'], 'whole')
        self.assertIsNone(scores['103']['final_score'])
        self.assertIn('파일 확인', scores['101']['reason'])
        self.assertEqual(book.overrides['101']['copy.c'][-1]['source_run'], 'whole')

    def test_cancelled_or_empty_batch_keeps_students_it_did_not_process(self):
        self.save('whole', 20)
        context, rows = self.save('cancelled', 21, students=('101', '102'), passed=False, state='cancelled')
        db.save_run('cancelled', context, [r for r in rows if r['student'] == '101'], 'cancelled')
        self.save('never_processed', 22, students=(), state='running')
        scores = {r['student']: r for r in self.book().scores()}
        self.assertEqual(scores['101']['final_score'], 0)
        self.assertEqual(scores['102']['final_score'], 75)

    def test_each_students_original_suite_is_used_instead_of_blending_cases(self):
        old = deepcopy(load_suite('copy.c'))
        old['cases'] = [dict(old['cases'][0], name='old-case')]
        self.save('old_suite', 20, 'copy.c', ('101',), bundle=old)
        self.save('new_suite', 21, 'copy.c', ('102',))
        book = self.book(dict(self.scope, problem='copy.c'))
        scores = {r['student']: r for r in book.scores()}
        self.assertEqual(scores['101']['final_score'], 10)
        self.assertEqual(scores['101']['total_cases'], 1)
        self.assertEqual(scores['102']['final_score'], 10)
        self.assertEqual(scores['102']['total_cases'], 5)
        self.assertEqual(scores['101']['problems']['copy.c']['required_cases'], 1)

    def test_regular_problems_use_each_students_latest_complete_evidence_and_exact_scope(self):
        scope = dict(class_name='system_3_2026', chapter='chap1', problem='p1')
        context = dict(scope, students=['101', '102'], case_count=2)
        rows = [dict(student=s, case=str(i), passed=True, status='passed') for s in ('101', '102') for i in range(2)]
        db.save_run('old', context, rows, 'completed', created_at='2026-10-20T00:00:00+00:00')
        db.save_run('new', dict(context, students=['101'], case_count=1),
                    [dict(student='101', case='new', passed=False, status='wrong_answer')], 'completed',
                    created_at='2026-10-21T00:00:00+00:00')
        for key, value in [('class_name', 'other_class'), ('chapter', 'chap2'), ('problem', 'p2')]:
            db.save_run('other_' + key, dict(context, **{key: value}), rows, 'completed',
                        created_at='2026-10-22T00:00:00+00:00')
        summaries = {r['student']: r for r in self.book(scope).summaries()}
        self.assertEqual((summaries['101']['passed_cases'], summaries['101']['total_cases']), (0, 1))
        self.assertEqual((summaries['102']['passed_cases'], summaries['102']['total_cases']), (2, 2))
        self.assertEqual(summaries['103']['status'], 'not_run')
        flat = dict(scope, problem=None)
        db.save_run('flat', dict(context, problem=None), rows, 'completed')
        self.assertEqual({r['source_run'] for r in self.book(flat).rows}, {'flat'})

    def test_live_gradebook_reads_beyond_the_historical_pickers_limit(self):
        self.save('old_student', 20, 'copy.c', ('101',))
        for number in range(101):
            self.save(f'new_student_{number:03}', 21, 'copy.c', ('102',))
        self.assertEqual(len(db.list_runs('system_3_2026', 'midterm')), 100)
        scores = {r['student']: r for r in self.book(dict(self.scope, problem='copy.c')).scores()}
        self.assertEqual(scores['101']['final_score'], 10)

    def test_startup_displays_latest_table_history_is_optional_and_refresh_returns_to_live_data(self):
        self.save('whole', 20)
        self.save('retry', 21, 'copy.c', ('101',), False)
        review = dict(self.scope, problem='copy.c', student='101', status='confirmed', overall=80,
                      suggested_score=7, max_score=10, final_score=8, summary='파일 자원 검토',
                      reviewer_note='확인', created_at='2026-10-21T00:00:00+00:00', criteria=[])
        db.save_qualitative('review', {'submissions': [review]}, [review])
        window = self.window()
        table = window.resultTable
        self.assertIsNone(window.case_report)
        self.assertTrue(window.latest_view)
        self.assertIsNone(window.comboRuns.currentData())
        self.assertEqual(table.item(0, 3).text(), '65 / 75')
        self.assertEqual(table.item(1, 3).text(), '75 / 75')
        self.assertEqual(table.item(0, 13).text(), '8')
        window.comboRuns.setCurrentIndex(window.comboRuns.findData('whole')); window.loadSavedRun()
        self.assertFalse(window.latest_view)
        self.assertEqual(table.item(0, 3).text(), '75 / 75')
        self.assertIn('과거 실행 조회', window.resultHeadline.text())
        window.comboRuns.setCurrentIndex(0); window.loadSavedRun()
        self.assertTrue(window.latest_view)
        self.assertEqual(table.item(0, 3).text(), '65 / 75')
        window.resultTable.selectRow(0)
        self.assertIn('실행 기록: retry', window.resultDetail.toPlainText())
        self.assertIn('파일 자원 검토', window.resultDetail.toPlainText())
        self.save('latest_external', 22, 'copy.c', ('101',))
        window.btnReloadReviews.click()
        self.assertEqual(table.item(0, 3).text(), '75 / 75')

    def test_adjusting_from_the_default_table_persists_to_the_correct_source_and_survives_restart(self):
        self.save('whole', 20)
        self.save('retry', 21, 'copy.c', ('101',), False)
        window = self.window()
        window.resultTable.selectRow(0)
        def adjust():
            dialog = self.app.activeModalWidget()
            dialog.findChild(QDoubleSpinBox, 'midtermFinalScore').setValue(6)
            dialog.findChild(QLineEdit, 'midtermReviewer').setText('teacher')
            dialog.findChild(QLineEdit, 'midtermReason').setText('기본 표에서 점수 조정')
            dialog.findChild(QPushButton, 'saveMidtermScore').click()
        QTimer.singleShot(0, adjust)
        window.adjustMidtermScore()
        self.assertEqual(window.resultTable.item(0, 3).text(), '71 / 75')
        self.assertEqual(db.load_run('retry')['score_overrides']['101']['copy.c'][-1]['score'], 6)
        self.assertEqual(db.load_run('whole')['score_overrides'], {})
        self.assertEqual(self.window().resultTable.item(0, 3).text(), '71 / 75')
        self.assertIsNone(window.comboRuns.currentData())

    def test_exports_from_a_fresh_window_use_the_live_gradebook(self):
        self.save('whole', 20)
        self.save('retry', 21, 'copy.c', ('101',), False)
        window = self.window()
        for extension in ('json', 'csv'):
            path = self.root / f'latest.{extension}'
            with patch('gui.QFileDialog.getSaveFileName', return_value=(str(path), '')):
                window.exportResults()
        document = json.loads((self.root / 'latest.json').read_text(encoding='utf-8'))
        self.assertEqual(document['kind'], 'latest_gradebook')
        self.assertEqual({r['source_run'] for r in document['results']}, {'whole', 'retry'})
        with (self.root / 'latest.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['final_score'], '65.0')
        self.assertEqual(rows[1]['final_score'], '75.0')
        self.assertEqual(len(rows), 3)

    def test_csv_combines_latest_problem_marks_reviews_and_adjustments_even_during_history_view(self):
        context, original = self.save('whole', 20)
        window = self.window()
        from reports import CaseReport
        report, document = CaseReport.load('whole'); window.showSavedRun(report, document)
        context, rows = self.save('retry', 21, 'copy.c', ('101',), False)
        db.save_run('retry', context, rows, 'completed', overrides={'101': {'copy.c': [
            dict(previous_score=0, score=6, reviewer='teacher', reason='원본 확인\n파일 확인',
                 at='2026-10-22T00:00:00+00:00')]}})
        review = dict(self.scope, student='101', student_name='첫 학생', problem='copy.c', status='confirmed',
                      overall=80, suggested_score=7, max_score=10, final_score=8, resource_score=6,
                      summary='정성평가 총평\r\n두 번째 줄', reviewer_note='검토\n확정',
                      created_at='2026-10-21T00:00:00+00:00', criteria=[
                          dict(id='correctness', score=8, applicable=True),
                          dict(id='resource_files', score=6, applicable=True),
                          dict(id='resource_memory', score=None, applicable=False)])
        db.save_qualitative('copy_review', {'submissions': [review]}, [review])
        ai = dict(review, problem='bookquery.c', status='ai_proposed', final_score=None, suggested_score=9)
        db.save_qualitative('query_review', {'submissions': [ai]}, [ai])
        exam = dict(review, problem='__all__', suggested_score=60, max_score=75, final_score=61)
        db.save_qualitative('exam_review', {'submissions': [exam]}, [exam])
        path = self.root / 'latest_with_reviews.csv'
        with patch('gui.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            window.exportResults()
        self.assertFalse(window.latest_view)
        self.assertEqual(window.resultTable.item(0, 3).text(), '75 / 75')
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertEqual(len(path.read_text(encoding='utf-8-sig').splitlines()), 4)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            exported = {r['student']: r for r in csv.DictReader(stream)}
        first = exported['101']
        self.assertEqual((first['auto_score'], first['final_score']), ('65.0', '71.0'))
        self.assertEqual((first['copy.c_auto'], first['copy.c_adjusted'], first['copy.c_final']), ('0.0', '6.0', '6.0'))
        self.assertEqual(first['copy.c_adjustment_reason'], '원본 확인 파일 확인')
        self.assertEqual(first['copy.c_qualitative_overall'], '80')
        self.assertEqual(first['copy.c_qualitative_suggested_score'], '7')
        self.assertEqual(first['copy.c_qualitative_final_score'], '8')
        self.assertEqual(first['1번 정성 점수'], '8')
        self.assertEqual(first['1번 정성 사유'], '확정')
        self.assertEqual(first['2-(2) 정성 점수'], '9')
        self.assertEqual(first['2-(2) 정성 사유'], 'AI 제안')
        self.assertEqual(first['전체 정성 점수'], '61')
        self.assertEqual((first['정성 총점'], first['정성 총점 만점']), ('17', '20'))  # 1번 확정 8 + 2-(2) 제안 9; 전체 평가는 제외
        self.assertEqual(first['bookquery.c_qualitative_status'], 'ai_proposed')
        self.assertEqual(first['bookquery.c_qualitative_final_score'], '')
        self.assertEqual(first['exam_qualitative_final_score'], '61')
        self.assertEqual(first['copy.c_qualitative_resource_memory_score'], '')
        self.assertEqual(first['copy.c_qualitative_resource_memory_applicable'], 'False')
        self.assertEqual(first['copy.c_qualitative_correctness_score'], '8')
        self.assertEqual(exported['102']['final_score'], '75.0')
        self.assertEqual(exported['103']['final_score'], '')
        self.assertEqual(exported['103']['copy.c_qualitative_status'], 'not_reviewed')

    def test_qualitative_only_csv_keeps_roster_missing_scores_zero_and_review_only_student(self):
        zero = dict(self.scope, student='101', student_name='=1+1', problem='copy.c', status='ai_proposed',
                    overall=0, suggested_score=0, max_score=10, final_score=None, summary='\t=SUM(A1:A3)', criteria=[])
        error = dict(zero, student='102', student_name='둘째 학생', status='error', suggested_score=None,
                     overall=None, message='서버\n연결 실패')
        extra = dict(zero, student='00104', student_name='추가 학생', status='confirmed', final_score=0)
        db.save_qualitative('reviews', {'submissions': [zero]}, [zero, error, extra])
        window = self.window()
        self.assertIsNone(window.gradebook)
        self.assertEqual(window.display_rows, [])
        path = self.root / 'only_reviews.csv'
        with patch('gui.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            window.exportResults()
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = {r['student']: r for r in csv.DictReader(stream)}
        self.assertEqual(set(rows), {'101', '102', '103', '00104'})
        self.assertEqual(len(path.read_text(encoding='utf-8-sig').splitlines()), 5)
        self.assertEqual(rows['101']['student_name'], "'=1+1")
        self.assertEqual(rows['101']['copy.c_qualitative_summary'], "'=SUM(A1:A3)")
        self.assertEqual(rows['101']['copy.c_qualitative_suggested_score'], '0')
        self.assertEqual(rows['101']['1번 정성 점수'], '0')
        self.assertEqual(rows['102']['1번 정성 점수'], '')
        self.assertEqual(rows['103']['1번 정성 상태'], '미평가')
        self.assertEqual(rows['101']['copy.c_qualitative_final_score'], '')
        self.assertEqual(rows['00104']['copy.c_qualitative_final_score'], '0')
        self.assertEqual(rows['00104']['student_name'], '추가 학생')
        self.assertEqual(rows['102']['copy.c_qualitative_status'], 'error')
        self.assertEqual(rows['102']['copy.c_qualitative_message'], '서버 연결 실패')
        self.assertEqual(rows['102']['copy.c_qualitative_suggested_score'], '')
        self.assertTrue(all(row['final_score'] == '' for row in rows.values()))

    def test_csv_single_file_exports_only_selected_scope_and_preserves_zero_adjustment(self):
        context, rows = self.save('copy', 20, 'copy.c')
        db.save_run('copy', context, rows, 'completed', overrides={'101': {'copy.c': [
            dict(previous_score=10, score=0, reviewer='teacher', reason='0점 확인', at='2026-10-21T00:00:00+00:00')]}})
        window = self.window()
        window.comboProblem.setCurrentIndex(window.comboProblem.findData('copy.c'))
        path = self.root / 'one_file.csv'
        with patch('gui.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            window.exportResults()
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream); rows = list(reader)
            self.assertFalse(any(column.startswith('bookquery.c_') for column in reader.fieldnames))
        self.assertEqual(rows[0]['copy.c_adjusted'], '0.0')
        self.assertEqual(rows[0]['final_score'], '0.0')
        self.assertEqual(rows[0]['max_score'], '10')

    def test_chapter_export_stacks_only_the_picked_chapters_in_one_csv(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QDialog
        self.save('whole', 20)
        for chapter, problem in [('chap1', 'p1'), ('chap1', 'p2'), ('chap2', 'p1')]:
            scope = dict(class_name='system_3_2026', chapter=chapter, problem=problem)
            db.save_run(f'{chapter}_{problem}', dict(scope, students=['101'], case_count=1),
                        [dict(student='101', case='1', passed=True, status='passed')], 'completed')
        window = self.window()
        shown = {}
        def pick(picker):
            items = [picker.chapters.item(i) for i in range(picker.chapters.count())]
            shown.update({item.data(Qt.ItemDataRole.UserRole): item.checkState() for item in items})
            picker.check_all(Qt.CheckState.Unchecked)
            self.assertFalse(picker.ok_button.isEnabled())
            for item in items:
                if item.data(Qt.ItemDataRole.UserRole) in ('midterm', 'chap1'):
                    item.setCheckState(Qt.CheckState.Checked)
            return QDialog.DialogCode.Accepted
        path = self.root / 'chapters.csv'
        with patch('chapter_picker.ChapterPicker.exec', pick),                 patch('gui.QFileDialog.getSaveFileName', return_value=(str(path), '')) as save:
            window.exportChapters()
        # Only chapters with saved records are offered, and the one on screen starts checked.
        self.assertEqual(shown, {'chap1': Qt.CheckState.Unchecked, 'chap2': Qt.CheckState.Unchecked,
                                 'midterm': Qt.CheckState.Checked})
        self.assertEqual(save.call_args.args[2], 'latest_gradebook_chap1_midterm.csv')
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream); rows = list(reader)
        self.assertEqual([(r['chapter'], r['problem']) for r in rows][::3],
                         [('chap1', 'p1'), ('chap1', 'p2'), ('midterm', '__all__')])
        self.assertEqual(len(rows), 9)
        self.assertIn('copy.c_final', reader.fieldnames)
        self.assertEqual([r['passed_cases'] for r in rows if r['chapter'] == 'chap1' and r['student'] == '101'], ['1', '1'])

    def test_regular_problem_csv_is_also_one_row_per_student_without_invented_points(self):
        from gradebook_csv import export_latest_csv
        scope = dict(class_name='system_3_2026', chapter='chap1', problem='p1')
        context = dict(scope, students=['101', '102'], case_count=2)
        cases = [dict(student=s, case=str(i), passed=True, status='passed') for s in ('101', '102') for i in range(2)]
        db.save_run('regular', context, cases, 'completed')
        review = dict(scope, student='103', student_name='정성만', status='confirmed', overall=70,
                      suggested_score=6, max_score=10, final_score=7, criteria=[])
        db.save_qualitative('regular_review', {'submissions': [review]}, [review])
        path = self.root / 'regular.csv'
        self.assertEqual(export_latest_csv(path, scope, ['101', '102', '103']), 3)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['passed_cases'], '2')
        self.assertEqual(rows[0]['total_cases'], '2')
        self.assertEqual(rows[0]['auto_score'], '')
        self.assertEqual(rows[2]['student_name'], '정성만')
        self.assertEqual(rows[2]['p1_qualitative_final_score'], '7')

    def test_returning_from_other_problem_history_never_reuses_its_rows_in_an_empty_scope(self):
        context, rows = self.save('whole', 20)
        window = self.window()
        # The history picker lists the chapter's runs, including other problems.
        for combo in (window.comboChapter, window.comboProblem):
            combo.blockSignals(True)
        window.comboChapter.addItem('chap2'); window.comboChapter.setCurrentText('chap2')
        window.comboProblem.clear(); window.comboProblem.addItem('p2', 'p2')
        for combo in (window.comboChapter, window.comboProblem):
            combo.blockSignals(False)
        from reports import CaseReport
        report, document = CaseReport.load('whole')
        window.showSavedRun(report, document)
        self.assertEqual(window.resultTable.item(0, 3).text(), '75 / 75')
        window.showLatestResults()
        self.assertEqual(window.selectedResultScope()['chapter'], 'chap2')
        self.assertIsNone(window.case_report)
        self.assertIsNone(window.gradebook)
        self.assertEqual(window.display_rows, [])
        self.assertEqual(window.resultTable.item(0, 2).text(), '미실행')
        self.assertEqual(window.result_reviews, {})


if __name__ == '__main__':
    unittest.main()
