import csv
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401
import db
from gradebook_csv import export_latest_csv
from qualitative import (DEFAULT_RUBRIC, review_batch, review_sources, validate_report, archive_reviews,
                         load_saved_reviews, confirm_review)
from submission_state import source_is_blank


class SubmissionZeroTests(unittest.TestCase):
    def setUp(self):
        support.isolate(self)
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.client = Mock(model='test', base_url='https://example.invalid/v1')

    def submission(self, student, kind):
        folder = self.root / student
        if kind != 'missing_folder':
            folder.mkdir()
        if kind == 'missing_file':
            (folder / 'book.h').write_text('struct book { int id; };')
            (folder / 'Copy.c').write_text('int main(){}')
        if kind in ('empty', 'whitespace'):
            (folder / 'copy.c').write_bytes(b'' if kind == 'empty' else b'\xef\xbb\xbf \r\n\t')
            (folder / 'book.h').write_text('struct book { int id; };')
        if kind == 'present':
            (folder / 'copy.c').write_text('int main(){}')
            (folder / 'empty.h').touch()
        return dict(class_name='system_3_2026', chapter='midterm', problem='copy.c',
                    student=student, path=str(folder), sources=['copy.c', '*.h'])

    def run_reviews(self, submissions):
        return list(review_batch(self.client, '파일을 복사한다.', DEFAULT_RUBRIC, submissions, total_score=10))

    def test_absent_and_empty_submissions_get_final_zero_without_model_calls_or_fake_evidence(self):
        submissions = [self.submission(str(i), kind) for i, kind in enumerate(
            ('missing_folder', 'missing_file', 'empty', 'whitespace'))]
        rows = self.run_reviews(submissions)
        self.client._request.assert_not_called()
        self.assertEqual([r['submission_issue'] for r in rows], ['missing_folder','missing_file','empty_file','empty_file'])
        for row in rows:
            self.assertEqual((row['status'], row['overall'], row['suggested_score'], row['final_score']),
                             ('submission_zero', 0, 0, 0))
            self.assertEqual(row['max_score'], 10)
            self.assertEqual(row['resource_score'], 0)
            self.assertTrue(all(not c['evidence'] for c in row['criteria']))
            self.assertEqual([c['score'] for c in row['criteria'][-3:]], [0, None, None])
        self.assertEqual(validate_report(dict(version=2, context={}, results=rows))['results'], rows)

    def test_direct_empty_sources_are_zero_and_blank_auxiliary_files_are_not_sent(self):
        result = review_sources(None, '정수를 출력한다.', DEFAULT_RUBRIC, {'main.c': ''}, total_score=5)
        self.assertEqual(result['final_score'], 0)
        self.assertIsNone(result['resource_score'])
        submission = self.submission('present', 'present')
        self.client._request.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(
            dict(summary='평가', strengths=[], improvements=[], uncertainties=[], criteria=[
                dict(id=r['id'], score=5, assessment='코드 확인', suggestion='확인',
                     evidence=[dict(file='copy.c', line=1)]) for r in DEFAULT_RUBRIC]))}}]}
        rows = self.run_reviews([submission])
        self.assertEqual(rows[0]['status'], 'ai_proposed')
        body = json.loads(self.client._request.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(set(body['source_files']), {'copy.c'})

    def test_partial_multi_problem_submission_is_not_given_a_blanket_zero(self):
        submission = self.submission('partial', 'present')
        (Path(submission['path']) / 'bookquery.c').touch()
        submission['sources'] = ['copy.c', 'bookquery.c', '*.h']
        with patch('qualitative.review_sources', return_value=dict(status='ai_proposed', suggested_score=5)) as review:
            rows = self.run_reviews([submission])
        self.assertEqual(rows[0]['status'], 'ai_proposed')
        self.assertEqual(set(review.call_args.args[3]), {'copy.c'})

    def test_actual_model_failures_keep_unknown_scores_and_batch_continues(self):
        submissions = [self.submission(str(i), 'present') for i in range(4)]
        invalid_line = dict(summary='평가', criteria=[dict(id=r['id'], score=5, assessment='확인', suggestion='확인',
            evidence=[dict(file='copy.c', line=2)]) for r in DEFAULT_RUBRIC])
        self.client._request.side_effect = [ValueError('Cannot reach LLM server'),
            {'choices':[{'finish_reason':'stop','message':{'content':'{"summary":"unfinished'}}]},
            {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(invalid_line)}}]},
            ValueError('LLM response was truncated')]
        rows = self.run_reviews(submissions)
        self.assertEqual(self.client._request.call_count, 4)
        self.assertTrue(all(r['status'] == 'error' and r['suggested_score'] is None and r['final_score'] is None for r in rows))
        self.assertIn('줄 번호', rows[2]['message'])
        self.assertNotIn('submission_issue', rows[2])

    def test_read_permission_encoding_and_configuration_errors_are_not_zero_marks(self):
        submission = self.submission('present', 'present')
        with patch('qualitative.collect_sources', side_effect=PermissionError('permission denied')):
            row = self.run_reviews([submission])[0]
        self.assertEqual(row['status'], 'error')
        self.assertIsNone(row['final_score'])
        (Path(submission['path']) / 'copy.c').write_bytes(b'\xff\xfeinvalid')
        row = self.run_reviews([submission])[0]
        self.assertEqual(row['status'], 'error')
        submission['sources'] = []
        self.assertEqual(self.run_reviews([submission])[0]['status'], 'error')
        self.client._request.assert_not_called()

    def test_zero_archive_database_latest_view_and_csv_preserve_zero_and_reason(self):
        row = self.run_reviews([self.submission('101', 'empty')])[0]
        context = dict(problem='파일을 복사한다.', submissions=[row], rubric=DEFAULT_RUBRIC)
        old = dict(row, status='confirmed', final_score=8, suggested_score=0, created_at='2026-01-01T00:00:00+00:00',
                   reviewed_at='2026-01-01T01:00:00+00:00')
        db.save_qualitative('old', context, [old])
        archive = self.root / 'qualitative_zero.json'; archive_reviews(archive, [row], context)
        archive.unlink()
        self.assertEqual(load_saved_reviews('qualitative_zero')['results'][0], row)
        selected = db.latest_qualitative_reviews('system_3_2026', 'midterm', ['copy.c'])
        self.assertEqual(selected[0]['status'], 'submission_zero')
        self.assertEqual(selected[0]['final_score'], 0)
        self.assertEqual(db.list_qualitative()[0]['zeroed'], 1)
        db.save_qualitative('server_failed', context, [dict(row, status='error', suggested_score=None, final_score=None)])
        self.assertEqual(db.latest_qualitative_reviews('system_3_2026', 'midterm', ['copy.c'])[0]['status'], 'submission_zero')
        path = self.root / 'scores.csv'
        export_latest_csv(path, dict(class_name='system_3_2026', chapter='midterm', problem='copy.c'))
        with path.open(encoding='utf-8-sig', newline='') as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]['copy.c_qualitative_final_score'], '0')
        self.assertEqual(exported[0]['copy.c_qualitative_submission_issue'], 'empty_file')
        self.assertIn('비어', exported[0]['copy.c_qualitative_summary'])

    def test_zero_validation_and_instructor_override(self):
        row = self.run_reviews([self.submission('101', 'missing_folder')])[0]
        for changes in (dict(final_score=1), dict(final_score=False), dict(submission_issue='unknown')):
            invalid = dict(row, **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_report(dict(version=2, context={}, results=[invalid]))
        confirm_review(row, 3, '제출 여부 재검토 후 수동 조정')
        self.assertEqual((row['status'], row['suggested_score'], row['final_score']), ('confirmed', 0, 3))
        validate_report(dict(version=2, context={}, results=[row]))

    def test_midterm_missing_folder_or_empty_file_is_graded_zero_without_running(self):
        from midterm import load_suite, grade_suite
        from midterm_scoring import score_students, settings
        for kind, problem in [('missing_folder', '__all__'), ('empty', 'copy.c'), ('whitespace', 'copy.c')]:
            submission = self.submission(kind, kind)
            bundle = load_suite(problem)
            with patch('midterm.Grader.grade_student') as execute:
                rows = grade_suite(submission['path'], bundle)
            execute.assert_not_called()
            rows = [dict(r, student='101') for r in rows]
            score = score_students(rows, dict(students=['101'], midterm_suite=bundle, midterm_scoring=settings()))[0]
            self.assertEqual(score['status'], 'graded')
            self.assertEqual((score['auto_score'], score['final_score']), (0, 0))
            self.assertEqual(len(rows), len(bundle['cases']))
        path = self.root / 'legacy.c'; path.write_bytes(b'// \xb0\xa1\xb3\xaa')
        self.assertFalse(source_is_blank(path))


class SubmissionZeroGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_zero_results_save_reload_display_and_are_excluded_from_failed_selection_without_llm_setup(self):
        support.isolate(self)
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        with patch.dict(os.environ, {'SWLAB_LLM_URL':'', 'SWLAB_LLM_MODEL':'', 'SWLAB_CONFIG': str(root/'none.json')}), \
             patch('qualitative_gui.ROOT', root), patch('qualitative_gui.build_catalog', return_value=[]):
            from qualitative_gui import QualitativeWindow
            from result_reviews import cells
            folder = root / '101'; folder.mkdir(); (folder / 'copy.c').touch()
            submissions = [dict(class_name='system_3_2026', chapter='midterm', problem='copy.c', student='101',
                                path=str(folder), sources=['copy.c', '*.h'])]
            window = QualitativeWindow(submissions)
            self.addCleanup(window.close)
            window.problem_text.setPlainText('파일을 복사한다.'); window.problem_points.setValue(10)
            window.url.clear(); window.model.clear()
            with patch('llm_cases.LLMClient._request') as request:
                window.start()
                self.assertIsNotNone(window.worker, window.status.text())
                deadline = time.monotonic() + 5
                while window.worker.isRunning() and time.monotonic() < deadline:
                    self.app.processEvents(); time.sleep(.01)
                self.app.processEvents()
                request.assert_not_called()
            self.assertEqual(window.rows[0]['status'], 'submission_zero')
            self.assertEqual(window.table.item(0, 2).text(), '제출 상태 0점')
            self.assertEqual(window.table.item(0, 5).text(), '0')
            self.assertIn('비어', window.detail.toPlainText())
            self.assertEqual(cells(window.rows)[3][0], '0 / 10')
            self.assertEqual(load_saved_reviews(window.archive.stem)['results'][0]['final_score'], 0)
            window.select_without_proposals()
            self.assertEqual(window.selected_indices(), [])
            self.assertFalse(window.batch_confirm_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
