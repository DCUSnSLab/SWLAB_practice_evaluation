import csv
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import yaml
from core.manifest import load_problem
from core.record import load_run, override_score
from core.resolver import load_layout, resolve_submission, save_override
from core.service import run_batch, tree_hash
from core.roster import roster_submissions
from grader import Grader
from paths import ROOT


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'assignments/demo/sum', self.root / 'problem')
        self.manifest = self.root / 'problem/problem.yaml'
        self.data = yaml.safe_load(self.manifest.read_text(encoding='utf-8'))
        shutil.copytree(ROOT / 'examples/manifest_students', self.root / 'students')
        self.students = [{'student_id': p.name, 'path': str(p)} for p in sorted((self.root / 'students').iterdir())]

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        self.manifest.write_text(yaml.safe_dump(self.data, allow_unicode=True), encoding='utf-8')

    def run_batch(self, **kwargs):
        return run_batch(self.manifest, self.students, records_dir=self.root / 'records',
                         mode='windows' if os.name == 'nt' else 'linux', **kwargs)

    def test_weighted_grading_records_and_source_preservation(self):
        before = tree_hash(self.root / 'students')
        archive, run = self.run_batch()
        rows = {r['student_id']: r for r in run['results']}
        self.assertEqual(rows['demo_good']['auto_score'], 10)
        self.assertEqual(rows['demo_partial']['auto_score'], 6)
        self.assertIsNone(rows['demo_missing']['auto_score'])
        self.assertEqual(rows['demo_missing']['status'], 'unresolved')
        self.assertEqual(run['state'], 'completed')
        self.assertEqual(tree_hash(self.root / 'students'), before)
        self.assertEqual(load_run(archive)['results'], run['results'])
        self.assertTrue((archive.parent / 'inputs/problem.yaml').is_file())
        self.assertEqual(run['inputs_sha256'], tree_hash(archive.parent / 'inputs'))
        saved_source = archive.parent / rows['demo_good']['submission']['snapshot']
        self.assertEqual(tree_hash(saved_source), rows['demo_good']['submission']['sha256'])
        with archive.with_name('summary.csv').open(encoding='utf-8-sig') as stream:
            csv_rows = {r['student_id']: r for r in csv.DictReader(stream)}
        self.assertEqual(csv_rows['demo_missing']['final_score'], '')
        _, second = self.run_batch()
        self.assertEqual([r['auto_score'] for r in run['results']], [r['auto_score'] for r in second['results']])

    def test_invalid_contracts_fail_before_execution(self):
        original = deepcopy(self.data)
        for change in (
            lambda d: d['scoring'].update(total=11),
            lambda d: d['submit'].update(files=['../main.py']),
            lambda d: d['run'].update(compare='typo'),
            lambda d: d['scoring']['cases'].update(missing=0),
            lambda d: d.update(due='2026-10-15T23:59:00'),
            lambda d: d['scoring']['cases'].update(positive=float('nan')),
            lambda d: d['run'].update(timeout_sec=0),
        ):
            with self.subTest(change=change):
                self.data = deepcopy(original); change(self.data); self.write_manifest()
                with self.assertRaises(ValueError):
                    load_problem(self.manifest)
        self.manifest.write_text('version: 1\nversion: 1', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_problem(self.manifest)

    def test_missing_assertion_and_invalid_case_are_rejected(self):
        expected = self.root / 'problem/cases/positive/expected.txt'
        expected.unlink()
        with self.assertRaises(ValueError): load_problem(self.manifest)
        (expected.parent / 'case.yaml').write_text('expected: 5', encoding='utf-8')
        with self.assertRaises(ValueError): load_problem(self.manifest)

    def test_fixture_cannot_replace_student_source(self):
        fixture = self.root / 'problem/cases/positive/files'
        fixture.mkdir(); (fixture / 'main.py').write_text("print('5')")
        with self.assertRaises(ValueError): load_problem(self.manifest)

    def test_mapping_persists_and_invalid_override_does_not_fall_back(self):
        problem = load_problem(self.manifest)
        student = self.root / 'students/demo_good'
        (student / 'chap1/sum').rename(student / 'custom')
        self.assertEqual(resolve_submission(student, 'demo_good', problem)['status'], 'unresolved')
        save_override(problem.layout_path, 'demo_good', problem, 'custom')
        layout = load_layout(problem.layout_path)
        result = resolve_submission(student, 'demo_good', problem, layout)
        self.assertEqual(result['matched_file'], 'answer.py')
        save_override(problem.layout_path, 'demo_good', problem, 'missing')
        self.assertEqual(resolve_submission(student, 'demo_good', problem, load_layout(problem.layout_path))['status'], 'unresolved')
        with self.assertRaises(ValueError): save_override(problem.layout_path, 'demo_good', problem, '../outside')

    def test_manual_score_history_and_csv_regeneration(self):
        archive, _ = self.run_batch()
        with self.assertRaises(ValueError): override_score(archive, 'demo_partial', 11, 'TA', 'reason')
        with self.assertRaises(ValueError): override_score(archive, 'demo_partial', 8, 'TA', '')
        override_score(archive, 'demo_partial', 8, 'TA', '부분 인정')
        revised = override_score(archive, 'demo_partial', 7, 'TA2', '재검토')
        row = next(r for r in revised['results'] if r['student_id'] == 'demo_partial')
        self.assertEqual(row['auto_score'], 6)
        self.assertEqual(row['final_score'], 7)
        self.assertEqual(len(row['overrides']), 2)
        self.assertEqual(row['overrides'][1]['previous_score'], 8)
        self.data['scoring']['manual_override'] = 'forbidden'; self.write_manifest()
        archive, _ = self.run_batch()
        with self.assertRaises(ValueError): override_score(archive, 'demo_good', 8, 'TA', 'reason')

    def test_cancellation_saves_completed_student_and_marks_remaining(self):
        completed = []
        def progress(index, row, archive):
            self.assertEqual(load_run(archive)['results'][index - 1], row)
            completed.append(row)
        archive, run = self.run_batch(progress=progress, cancelled=lambda: bool(completed))
        self.assertEqual(run['state'], 'cancelled')
        self.assertEqual(run['results'][0]['auto_score'], 10)
        self.assertTrue(all(r['status'] == 'not_run' and r['auto_score'] is None for r in run['results'][1:]))

    def test_environment_failure_does_not_create_zero_scores(self):
        with patch('core.service.environment', side_effect=ValueError('Docker not running')):
            with self.assertRaises(ValueError): self.run_batch()
        self.assertFalse((self.root / 'records').exists())

    def test_records_cannot_be_inside_a_submission(self):
        with self.assertRaises(ValueError):
            run_batch(self.manifest, self.students, records_dir=self.students[0]['path'],
                      mode='windows' if os.name == 'nt' else 'linux')

    def test_runner_setup_error_is_ungraded(self):
        error = dict(stdout='', stderr='compiler unavailable', returncode=None, timed_out=False, output_limit=False)
        with patch.object(Grader, 'execute', return_value=error):
            _, run = self.run_batch()
        self.assertEqual(run['results'][0]['status'], 'error')
        self.assertIsNone(run['results'][0]['auto_score'])

    def test_roster_keeps_students_with_no_repository(self):
        roster = self.root / 'class.csv'
        roster.write_text('학번,이름,github\n1001,Test,https://github.com/example/one\n1002,Test2,https://github.com/example/two\n', encoding='utf-8-sig')
        submissions = roster_submissions(roster, self.root / 'students')
        self.assertEqual([s['student_id'] for s in submissions], ['1001', '1002'])
        _, run = run_batch(self.manifest, submissions, records_dir=self.root / 'records', mode='windows' if os.name == 'nt' else 'linux')
        self.assertTrue(all(r['status'] == 'unresolved' and r['final_score'] is None for r in run['results']))

    def test_student_failure_does_not_abort_batch(self):
        original = Grader.grade_student
        calls = []
        def fail_once(grader, *args):
            calls.append(True)
            if len(calls) == 1: raise OSError('Cannot read source')
            return original(grader, *args)
        with patch.object(Grader, 'grade_student', fail_once):
            _, run = self.run_batch()
        self.assertEqual(run['results'][0]['status'], 'error')
        self.assertIsNone(run['results'][0]['auto_score'])
        self.assertEqual(run['results'][-1]['auto_score'], 6)

    def test_numeric_comparison_rejects_nonfinite_and_length_mismatch(self):
        grader = Grader()
        self.assertTrue(grader.check_result('1.0000001 2', '1 2', 'numeric', 1e-6))
        for actual in ('nan 2', 'inf 2', '1', '1 2 3', '1.01 2', 'text'):
            self.assertFalse(grader.check_result(actual, '1 2', 'numeric', 1e-6))

    def test_input_snapshot_is_used_even_if_original_changes(self):
        def progress(index, row, archive):
            (self.root / 'problem/cases/negative/expected.txt').write_text('5')
        _, run = self.run_batch(progress=progress)
        self.assertEqual(run['results'][-1]['auto_score'], 6)

    def test_cli_manifest_exit_status_and_autosave(self):
        result = subprocess.run([sys.executable, str(ROOT / 'src/cli.py'), str(self.root / 'students'), '--batch',
            '--manifest', str(self.manifest), '--mode', 'windows' if os.name == 'nt' else 'linux',
            '--records', str(self.root / 'cli-records')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('demo_partial: graded 6.0/10', result.stdout)
        self.assertEqual(len(list((self.root / 'cli-records').rglob('run.json'))), 1)


@unittest.skipUnless(os.environ.get('SWLAB_TEST_DOCKER') == '1', 'Docker integration disabled')
class ManifestDockerTests(unittest.TestCase):
    def test_migrated_copy_problem(self):
        with tempfile.TemporaryDirectory() as temp:
            _, run = run_batch(ROOT / 'assignments/system/2026/chap4/prob2/problem.yaml',
                [{'student_id': 'synthetic-copy', 'path': str(ROOT / 'examples/copy')}], records_dir=temp)
            self.assertEqual(run['results'][0]['auto_score'], 10, run['results'])
            self.assertTrue(run['environment']['image_id'].startswith('sha256:'))


if __name__ == '__main__':
    unittest.main()
