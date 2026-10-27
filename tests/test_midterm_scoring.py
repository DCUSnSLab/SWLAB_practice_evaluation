import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from midterm import load_suite, grade_suite, library_case
from midterm_scoring import score_students, settings, POINTS, export_scores
from reports import CaseReport
from core.record import atomic_text


class MidtermScoringTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_suite()
        self.context = dict(midterm_suite=self.bundle, midterm_scoring=settings(), students=['101'])
        self.rows = [dict(student='101', target_file=c['target_file'], case=c['target_file'] + ' / ' + c['name'],
                          status='passed', passed=True) for c in self.bundle['cases']]

    def scores(self):
        return score_students(self.rows, self.context)[0]

    def test_maximum_matches_paper_and_problem_ratios_not_global_ratio(self):
        self.assertEqual(self.scores()['final_score'], 75)
        # Fail one of two required 20-point year-sort cases: lose 10, not 75/36.
        row = next(r for r in self.rows if r['case'] == 'sortedbookcreate.c / store_year_descending')
        row.update(status='wrong_answer', passed=False)
        result = self.scores()
        self.assertEqual(result['final_score'], 65)
        self.assertEqual(result['problems']['sortedbookcreate.c']['auto_score'], 10)
        self.assertEqual(result['problems']['copy.c']['auto_score'], 10)
        self.assertIn('3-(3)', result['reason'])
        self.assertIn('필수 1/2 통과', result['reason'])

    def test_extra_failures_and_extra_unavailable_evidence_do_not_change_points(self):
        extra = {c['target_file'] + ' / ' + c['name'] for c in self.bundle['cases'] if c.get('category') == 'extra'}
        for row in self.rows:
            if row['case'] in extra:
                row.update(status='needs_review', passed=False)
        self.assertEqual(self.scores()['final_score'], 75)
        self.assertEqual(self.scores()['status'], 'graded')
        self.assertEqual(self.scores()['passed_cases'], 28)
        self.assertIn('추가 8건 미통과·점수 제외', self.scores()['reason'])

    def test_rounding_is_per_problem_and_empty_scores_are_not_zero(self):
        self.rows[0].update(status='wrong_answer', passed=False)
        score = self.scores()
        self.assertEqual(score['problems']['copy.c']['final_score'], 8)
        self.assertEqual(score['final_score'], 73)
        self.rows[0].update(status='needs_review')
        score = self.scores()
        self.assertIsNone(score['final_score'])
        self.assertIsNone(score['problems']['copy.c']['auto_score'])
        self.assertEqual(score['known_score'], 65)

    def test_missing_duplicate_and_contradictory_results_need_review(self):
        self.rows.pop(0)
        self.assertIsNone(self.scores()['final_score'])
        self.rows = self.rows + [self.rows[0]]
        self.assertIsNone(self.scores()['problems']['copy.c']['auto_score'])
        self.rows = [dict(student='101', case=c['target_file'] + ' / ' + c['name'], status='passed', passed=False)
                     for c in self.bundle['cases']]
        self.assertIsNone(self.scores()['final_score'])

    def test_missing_required_filename_is_zero_but_missing_repository_is_unresolved(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = load_suite('bookupdate.c')
            rows = grade_suite(temp, bundle)
            context = dict(self.context, midterm_suite=bundle)
            scored = score_students([dict(r, student='101') for r in rows], context)[0]
            self.assertEqual(scored['final_score'], 0)
            self.assertEqual(scored['max_score'], 10)
            rows = grade_suite(Path(temp) / 'missing', bundle)
            self.assertIsNone(score_students([dict(r, student='101') for r in rows], context)[0]['final_score'])

    def test_own_compile_error_is_failure_dependency_compile_error_needs_review(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'bookcreate.c').touch()
            (folder / 'bookupdate.c').touch()
            failed = dict(stdout='', stderr='bad C', returncode=1, compile_error=True, timed_out=False, output_limit=False)
            with patch('midterm.Grader.execute', return_value=failed):
                own = next(c for c in self.bundle['cases'] if c['target_file'] == 'bookcreate.c')
                dependent = next(c for c in self.bundle['cases'] if c['target_file'] == 'bookupdate.c')
                self.assertEqual(library_case(folder, own, self.bundle['datasets'], self.bundle['profile'], {})['status'], 'compile_error')
                self.assertEqual(library_case(folder, dependent, self.bundle['datasets'], self.bundle['profile'], {})['status'], 'needs_review')

    def test_file_only_run_denominator_and_pending_cancelled_students(self):
        context = dict(self.context, midterm_suite=load_suite('bookcreate.c'), students=['101', '102'])
        rows = [r for r in self.rows if r['target_file'] == 'bookcreate.c']
        scored = score_students(rows, context, 'cancelled')
        self.assertEqual(scored[0]['final_score'], 5)
        self.assertEqual(scored[0]['max_score'], 5)
        self.assertEqual(scored[1]['status'], 'not_run')
        self.assertIsNone(scored[1]['final_score'])

    def test_report_csv_manual_adjustments_and_reopen_preserve_automatic_evidence(self):
        self.rows[0].update(status='wrong_answer', passed=False)
        with tempfile.TemporaryDirectory() as temp:
            report = CaseReport(self.context, root=temp)
            report.save(self.rows, 'completed')
            with self.assertRaises(ValueError):
                report.override_midterm_score('101', 'copy.c', 10, '', 'reason')
            with self.assertRaises(ValueError):
                report.override_midterm_score('101', 'copy.c', 10.01, 'teacher', 'reason')
            report.override_midterm_score('101', 'copy.c', 9.8, 'teacher', 'output format reviewed')
            report, saved = CaseReport.open(report.directory / 'run.json')
            score = saved['scores'][0]
            self.assertEqual(score['auto_score'], 73)
            self.assertEqual(score['final_score'], 74.8)
            self.assertFalse(saved['results'][0]['passed'])
            self.assertEqual(score['problems']['copy.c']['overrides'][0]['previous_score'], 8)
            report.override_midterm_score('101', 'copy.c', 10, 'teacher', 'second review')
            _, saved = CaseReport.open(report.directory / 'run.json')
            self.assertEqual(len(saved['score_overrides']['101']['copy.c']), 2)
            with (report.directory / 'summary.csv').open(encoding='utf-8-sig', newline='') as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row['final_score'], '75.0')
            self.assertEqual(row['copy.c_auto'], '8.0')
            self.assertEqual(row['copy.c_final'], '10.0')
            self.assertIn('second review', row['reason'])

    def test_unresolved_csv_remains_blank_and_identifier_is_safe(self):
        self.rows[0].update(status='needs_review', passed=False)
        context = dict(self.context, students=['=unsafe'])
        rows = [dict(r, student='=unsafe') for r in self.rows]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'scores.csv'
            export_scores(path, score_students(rows, context))
            with path.open(encoding='utf-8-sig', newline='') as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row['student'], "'=unsafe")
            self.assertEqual(row['final_score'], '')
            self.assertEqual(row['copy.c_final'], '')
            self.assertEqual(row['bookcreate.c_final'], '5.0')

    def test_windows_progress_reader_lock_retries_atomic_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'run.json'
            import os
            replace = os.replace
            calls = []
            def busy_once(source, destination):
                calls.append(1)
                if len(calls) == 1:
                    raise PermissionError('Windows report reader holds the file')
                return replace(source, destination)
            with patch('core.record.os.name', 'nt'), patch('core.record.os.replace', side_effect=busy_once), patch('core.record.time.sleep'):
                atomic_text(path, 'new report')
            self.assertEqual(path.read_text(encoding='utf-8'), 'new report')
            self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
