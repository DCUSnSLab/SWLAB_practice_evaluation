import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
import db
from gui import Gui
from qualitative import DEFAULT_RUBRIC, validate_review


class ResultReviewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        support.isolate(self)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, value in [('paths.ORIGIN', self.root / 'origin'), ('paths.TESTCASES', self.root / 'testcase'),
                              ('qualitative_gui.ROOT', self.root)]:
            mock = patch(target, value); mock.start(); self.addCleanup(mock.stop)
        self.windows = []
        self.addCleanup(self.close_windows)

    def close_windows(self):
        for window in reversed(self.windows):
            if getattr(window, 'qualitative_window', None):
                window.qualitative_window.close()
            window.close()
        self.app.processEvents()

    def row(self, student='101', problem='p1', chapter='chap1', score=50, **changes):
        row = dict(class_name='system_3_2026', student=student, student_name='테스트 학생',
                   chapter=chapter, problem=problem, status='ai_proposed', overall=70,
                   suggested_score=score, max_score=100, final_score=None, criteria=[],
                   summary='정성 평가 근거', created_at='2026-10-27T00:00:00+00:00')
        row.update(changes)
        return row

    def save(self, run_id, rows):
        db.save_qualitative(run_id, {'submissions': rows, 'run_state': 'finished'}, rows)

    def window(self, chapter='chap1', problems=('p1', 'p2')):
        with patch.object(Gui, 'refreshYearList'):
            window = Gui()
        self.windows.append(window)
        window.eval.get_student_list = lambda *args: ['101', '102']
        window.eval.get_student_chapters = lambda *args: [chapter]
        window.eval.get_student_problems = lambda *args: list(problems)
        window.eval.get_student_files = lambda *args: []
        window.comboClass.addItem('테스트 분반', 'system_3_2026')
        return window

    def by_id(self, window, student):
        return next(i for i in range(window.resultTable.rowCount()) if window.resultStudent(i) == student)

    def test_selection_restores_db_only_reviews_without_executing_or_opening_json(self):
        self.save('saved', [self.row(score=0, status='confirmed', final_score=0, reviewer_note='0점 확인')])
        window = self.window()
        table = window.resultTable
        index = self.by_id(window, '101')
        self.assertEqual(table.columnCount(), 10)
        self.assertEqual([table.item(index, col).text() for col in (1, 2, 6, 7, 8, 9)],
                         ['테스트 학생', '미실행', '교수자 확정', '70', '0 / 100', '0 / 100'])
        self.assertEqual(table.item(self.by_id(window, '102'), 8).text(), '—')
        table.selectRow(index)
        self.assertIn('정성 평가 근거', window.resultDetail.toPlainText())
        self.assertIn('0점 확인', window.resultDetail.toPlainText())
        self.assertIsNone(window.case_report)
        self.assertEqual(window.results, [])
        self.assertFalse((self.root / 'reports').exists())

    def test_latest_student_rows_ignore_failed_retry_and_copied_older_assessments(self):
        old = self.row(score=20)
        current = self.row(score=80, created_at='2026-10-28T01:00:00+00:00')
        self.save('old', [old])
        self.save('current', [current])
        self.save('new_batch_carrying_old_row', [old, self.row('102')])
        self.save('failed_retry', [self.row(status='error', suggested_score=None,
            created_at='2026-10-28T02:00:00+00:00', message='서버 연결 실패')])
        self.save('other_problem', [self.row(problem='p2', score=99)])
        self.save('other_class', [self.row(class_name='python_1_2026', score=99)])
        self.save('other_chapter', [self.row(chapter='chap2', score=99)])
        rows = db.latest_qualitative_reviews('system_3_2026', 'chap1', ['p1'])
        self.assertEqual({r['student']: r['suggested_score'] for r in rows}, {'101': 80, '102': 50})
        self.assertEqual(next(r for r in rows if r['student'] == '101')['run_id'], 'current')
        self.assertEqual(db.latest_qualitative_reviews(None, 'chap1', ['p1']), [])
        self.save('flat', [self.row(problem=None)])
        self.assertEqual(db.latest_qualitative_reviews('system_3_2026', 'chap1', [None])[0]['run_id'], 'flat')

    def test_case_scores_stay_separate_and_numeric_sort_and_selection_survive_refresh(self):
        self.save('saved', [self.row(score=2), self.row('102', score=10)])
        window = self.window()
        window.case_report = SimpleNamespace(context=dict(class_name='system_3_2026', chapter='chap1', problem='p1',
            students=['101', '102'], case_count=1), state='completed', directory=self.root / 'run')
        window.results = [dict(student=s, case='one', status='passed', passed=True) for s in ('101', '102')]
        window.refreshResultsTable()
        table = window.resultTable
        table.selectRow(self.by_id(window, '101'))
        table.sortItems(8, Qt.SortOrder.DescendingOrder)
        self.assertEqual([window.resultStudent(i) for i in range(2)], ['102', '101'])
        window.btnReloadReviews.click()
        self.assertEqual(window.resultStudent(table.currentRow()), '101')
        self.assertEqual(table.horizontalHeader().sortIndicatorSection(), 8)
        self.assertEqual(table.item(self.by_id(window, '101'), 4).text(), '1 / 1')
        window.comboProblem.setCurrentIndex(window.comboProblem.findData('p2'))
        self.assertIsNone(window.case_report)
        self.assertEqual(window.results, [])
        self.assertEqual(table.columnCount(), 6)
        self.assertLess(table.horizontalHeader().sortIndicatorSection(), 6)
        self.assertNotIn('정성 평가 근거', window.resultDetail.toPlainText())

    def test_midterm_all_shows_file_scores_and_execution_totals_remain_unchanged(self):
        from midterm import load_suite
        from midterm_scoring import settings
        self.save('copy', [self.row(problem='copy.c', chapter='midterm', score=7, max_score=10)])
        self.save('query', [self.row(problem='bookquery.c', chapter='midterm', score=9, max_score=10)])
        window = self.window('midterm', ())
        table = window.resultTable
        self.assertEqual(window.selectedProblem(), '__all__')
        self.assertIn('copy.c: 7 / 10', table.item(self.by_id(window, '101'), 8).text())
        self.assertIn('bookquery.c: 9 / 10', table.item(self.by_id(window, '101'), 8).text())
        context = dict(class_name='system_3_2026', chapter='midterm', problem='__all__', students=['101'],
                       midterm_scoring=settings(), midterm_suite=load_suite('__all__'))
        window.case_report = SimpleNamespace(context=context, state='completed', score_overrides={}, directory=self.root / 'run')
        window.results = [dict(student='101', target_file=c['target_file'], case=f'{c["target_file"]} / {c["name"]}', passed=True, status='passed')
                          for c in context['midterm_suite']['cases']]
        window.refreshResultsTable()
        self.assertEqual(table.columnCount(), 17)
        self.assertEqual(table.item(0, 3).text(), '75 / 75')
        self.assertIn('copy.c: 7 / 10', table.item(0, 15).text())
        window.comboProblem.setCurrentIndex(window.comboProblem.findData('copy.c'))
        self.assertEqual(table.item(self.by_id(window, '101'), 8).text(), '7 / 10')
        self.assertNotIn('bookquery.c', table.item(self.by_id(window, '101'), 8).toolTip())

    def test_qualitative_save_and_batch_confirmation_refresh_main_table_immediately(self):
        window = self.window()
        with patch('qualitative_gui.build_catalog', return_value=[]):
            window.openQualitative()
        qualitative = window.qualitative_window
        raw = dict(summary='실시간 갱신', strengths=[], improvements=[], uncertainties=[], criteria=[
            dict(id=r['id'], score=5, assessment='코드 확인', suggestion='요구사항 확인', evidence=[])
            for r in DEFAULT_RUBRIC])
        row = validate_review(raw, DEFAULT_RUBRIC, {'main.c': 'int main(){}'})
        row.update({k: v for k, v in qualitative.submissions[0].items() if k != 'path'})
        row.update(status='ai_proposed', final_score=None, created_at='2026-10-28T00:00:00+00:00')
        qualitative.rows[0] = row
        qualitative.context = dict(submissions=qualitative.submissions, rubric=DEFAULT_RUBRIC, problem='정수를 출력한다.')
        qualitative.archive = self.root / 'reports' / 'qualitative_saved.json'
        qualitative.refresh_rows(); qualitative.persist()
        index = self.by_id(window, '101')
        self.assertEqual(window.resultTable.item(index, 6).text(), 'AI 제안')
        self.assertEqual(window.resultTable.item(index, 9).text(), '—')
        qualitative.batch_note.setText('일괄 검토 확인')
        qualitative.confirm_selected()
        index = self.by_id(window, '101')
        self.assertEqual(window.resultTable.item(index, 6).text(), '교수자 확정')
        self.assertEqual(window.resultTable.item(index, 9).text(), '50 / 100')
        qualitative.archive.unlink()
        reopened = self.window()
        self.assertEqual(reopened.resultTable.item(self.by_id(reopened, '101'), 9).text(), '50 / 100')


if __name__ == '__main__':
    unittest.main()
