import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401  isolates the SQLite store
import db
from reports import CaseReport


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        support.isolate(self)
        self.context = {'class_name': 'system_1_2026', 'chapter': 'chap3', 'problem': 'p1', 'mode': 'docker',
                        'students': ['101', '102'], 'student_names': {'101': '첫 학생'}, 'case_count': 2}
        self.rows = [dict(student='101', student_name='첫 학생', case='one', passed=True, status='passed', actual='x'),
                     dict(student='101', student_name='첫 학생', case='two', passed=False, status='wrong_answer', trace=[{'a': 1}]),
                     dict(student='102', student_name='', case='one', passed=False, status='missing')]

    def test_roster_names_persist_per_class_and_update_in_place(self):
        db.save_roster('system_1_2026', [dict(student_id='101', name='첫 학생'), dict(student_id='102', name='둘째')])
        db.save_roster('system_1_2026', [dict(student_id='102', name='둘째 학생'), dict(student_id='103', name=' ')])
        db.save_roster('system_2_2026', [dict(student_id='101', name='다른 분반')])
        self.assertEqual(db.roster_names('system_1_2026'), {'101': '첫 학생', '102': '둘째 학생'})
        self.assertEqual(db.roster_names('system_2_2026'), {'101': '다른 분반'})
        self.assertEqual(db.roster_names('python_1_2026'), {})

    def test_case_report_saves_every_state_to_the_database(self):
        report = CaseReport(self.context, root=self.root / 'reports')
        run_id = report.directory.name
        self.assertEqual(db.load_run(run_id)['state'], 'running')
        report.save(self.rows[:2], 'running')
        report.save(self.rows, 'completed')
        document = db.load_run(run_id)
        self.assertEqual(document['results'], self.rows)
        self.assertEqual(document['context'], self.context)
        self.assertEqual(document['state'], 'completed')
        self.assertIsNone(document['error'])
        runs = db.list_runs('system_1_2026', 'chap3')
        self.assertEqual([(r['id'], r['student_count'], r['result_count'], r['scored']) for r in runs], [(run_id, 2, 3, False)])
        self.assertEqual(db.list_runs('system_1_2026', 'chap4'), [])
        loaded, saved = CaseReport.load(run_id)
        self.assertEqual((loaded.directory, loaded.state, saved['results']), (report.directory, 'completed', self.rows))
        with self.assertRaises(ValueError):
            CaseReport.load('missing')
        # The database is authoritative even after the export folder disappears.
        for path in report.directory.iterdir(): path.unlink()
        report.directory.rmdir()
        self.assertEqual(report.saved()['results'], self.rows)

    def test_midterm_overrides_round_trip_and_survive_without_run_json(self):
        from midterm_scoring import settings
        from midterm import load_suite
        context = dict(self.context, chapter='midterm', problem='copy.c', midterm_suite=load_suite('copy.c'), midterm_scoring=settings())
        rows = [dict(student='101', case=f'copy.c / {case["name"]}', target_file='copy.c', passed=True, status='passed')
                for case in context['midterm_suite']['cases']]
        report = CaseReport(context, root=self.root / 'reports')
        report.save(rows, 'completed')
        (report.directory / 'run.json').unlink()
        report.override_midterm_score('101', 'copy.c', 7.5, 'teacher', 'format reviewed')
        document = db.load_run(report.directory.name)
        self.assertEqual(document['score_overrides']['101']['copy.c'][0]['score'], 7.5)
        self.assertEqual(document['scores'][0]['final_score'], 7.5)
        self.assertEqual(db.list_runs()[0]['scored'], True)

    def test_import_reports_loads_each_run_json_once(self):
        folder = self.root / 'reports' / 'case-grading'
        for run_id, state in [('20260101_000000_aaaaaaaa', 'completed'), ('20260102_000000_bbbbbbbb', 'cancelled')]:
            (folder / run_id).mkdir(parents=True)
            (folder / run_id / 'run.json').write_text(json.dumps({'kind': 'case_grading', 'created_at': '2026-01-01T00:00:00+00:00',
                'state': state, 'context': self.context, 'results': self.rows, 'error': None}), encoding='utf-8')
        (folder / 'junk').mkdir(); (folder / 'junk' / 'run.json').write_text('{"kind": "other"}', encoding='utf-8')
        self.assertEqual(db.import_reports(folder), ['20260101_000000_aaaaaaaa', '20260102_000000_bbbbbbbb'])
        self.assertEqual(db.import_reports(folder), [])
        self.assertEqual(db.import_reports(self.root / 'nowhere'), [])
        self.assertEqual(db.load_run('20260102_000000_bbbbbbbb')['state'], 'cancelled')
        self.assertEqual(db.load_run('20260102_000000_bbbbbbbb')['results'], self.rows)
        self.assertEqual([r['id'] for r in db.list_runs()], ['20260102_000000_bbbbbbbb', '20260101_000000_aaaaaaaa'])

    def test_results_are_written_from_a_worker_thread_and_read_from_the_main_thread(self):
        import threading
        report = CaseReport(self.context, root=self.root / 'reports')
        errors = []
        def work():
            try:
                report.save(self.rows, 'completed')
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=work); thread.start(); thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(db.load_run(report.directory.name)['results'], self.rows)


if __name__ == '__main__':
    unittest.main()
