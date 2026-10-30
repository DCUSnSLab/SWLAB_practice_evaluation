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

    @support.needs_midterm_suite
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

    def review_rows(self):
        from qualitative import DEFAULT_RUBRIC
        criteria = [dict(id=r['id'], name=r['name'], score=5, max_score=10, reason='확인', evidence=[]) for r in DEFAULT_RUBRIC]
        proposed = dict(class_name='system_1_2026', student='101', student_name='첫 학생', chapter='chap3', problem='p1',
                        status='ai_proposed', summary='요약', strengths=[], improvements=[], uncertainties=[], criteria=criteria,
                        suggested_score=35, max_score=70, final_score=None, reviewer_note='', created_at='2026-10-27T07:03:30+00:00')
        confirmed = dict(proposed, student='102', student_name='', status='confirmed', final_score=30, reviewer_note='확정')
        failed = dict(class_name='system_1_2026', student='103', chapter='chap3', problem='p1', status='error',
                      message='파일 없음', suggested_score=None, final_score=None)
        return [proposed, confirmed, failed]

    def test_qualitative_batches_round_trip_and_list_with_counts(self):
        rows = self.review_rows()
        context = {'problem': '정수 출력', 'rubric': [], 'submissions': [dict(class_name='system_1_2026', student='101', chapter='chap3', problem='p1')],
                   'model': 'qwen', 'run_state': 'running'}
        db.save_qualitative('qualitative_20261027_160320_5b98c4', context, rows[:1], 1, self.root / 'a.json', '2026-10-27T07:00:00+00:00')
        context['run_state'] = 'finished'
        db.save_qualitative('qualitative_20261027_160320_5b98c4', context, rows, 1, self.root / 'a.json')
        document = db.load_qualitative('qualitative_20261027_160320_5b98c4')
        self.assertEqual((document['version'], document['results'], document['context']['run_state']), (1, rows, 'finished'))
        self.assertEqual(document['archive'], str(self.root / 'a.json'))
        self.assertIsNone(db.load_qualitative('missing'))
        db.save_qualitative('qualitative_20261028_000000_aaaaaa', {'submissions': [dict(class_name='system_1_2026', chapter='chap3', problem='p2')]}, [], 2)
        listed = db.list_qualitative('system_1_2026', 'chap3', 'p1')
        self.assertEqual([(r['id'], r['student_count'], r['confirmed'], r['proposed'], r['failed'], r['state']) for r in listed],
                         [('qualitative_20261027_160320_5b98c4', 3, 1, 1, 1, 'finished')])
        self.assertEqual([r['id'] for r in db.list_qualitative()], ['qualitative_20261028_000000_aaaaaa', 'qualitative_20261027_160320_5b98c4'])
        self.assertEqual(db.list_qualitative('python_1_2026'), [])

    def test_archive_reviews_writes_the_database_and_the_json_export(self):
        from qualitative import archive_reviews, load_saved_reviews, load_reviews, DEFAULT_RUBRIC
        rows = self.review_rows()
        path = self.root / 'reports' / 'qualitative_20261027_174410_169c90.json'
        archive_reviews(path, rows, {'rubric': DEFAULT_RUBRIC, 'submissions': [dict(class_name='system_1_2026', student='101', chapter='chap3', problem='p1')]})
        self.assertEqual(load_reviews(path)['results'], rows)
        path.unlink()
        self.assertEqual(load_saved_reviews('qualitative_20261027_174410_169c90')['results'], rows)
        with self.assertRaises(ValueError):
            load_saved_reviews('missing')
        rows[0]['status'] = 'bogus'
        db.save_qualitative('qualitative_20261027_174410_169c90', {}, rows)
        with self.assertRaises(ValueError):
            load_saved_reviews('qualitative_20261027_174410_169c90')

    def test_rescore_moves_legacy_rows_to_ceiling_and_follows_unchanged_confirmations(self):
        from qualitative import DEFAULT_RUBRIC, archive_reviews, load_reviews, load_saved_reviews, validate_review
        from qualitative_rubric import LEGACY_SCORING_VERSION, SCORING_VERSION, compute_scores, resource_scope
        def legacy_row(student, status, final=None):
            raw = {'summary': '요약', 'strengths': [], 'improvements': [], 'uncertainties': [], 'criteria': [
                dict(id=r['id'], score={'correctness': 8, 'problem_understanding': 7, 'resource_files': 7}.get(r['id'], 5),
                     assessment='확인', suggestion='보완', evidence=[]) for r in DEFAULT_RUBRIC]}
            row = validate_review(raw, DEFAULT_RUBRIC, {'main.c': 'line'}, total_score=10,
                                  resource_scope=resource_scope('파일을 읽는다.', {}))
            row.update(compute_scores(row['criteria'], 10, LEGACY_SCORING_VERSION))
            row.update(class_name='system_1_2026', chapter='midterm', problem='copy.c', student=student,
                       status=status, final_score=final, reviewer_note='확인' if final is not None else '')
            return row
        rows = [legacy_row('101', 'confirmed', 7), legacy_row('102', 'confirmed', 9), legacy_row('103', 'ai_proposed')]
        self.assertEqual(rows[0]['suggested_score'], 7)
        path = self.root / 'reports' / 'qualitative_20261028_201942_ca041d.json'
        archive_reviews(path, rows, {'rubric': DEFAULT_RUBRIC, 'scoring_version': LEGACY_SCORING_VERSION,
                                     'submissions': [dict(class_name='system_1_2026', chapter='midterm', problem='copy.c')]})
        planned = db.rescore_qualitative(dry_run=True)
        self.assertEqual([(c['student'], c['suggested_score'], c['final_score']) for c in planned],
                         [('101', 8, 8), ('102', 8, 9), ('103', 8, None)])
        self.assertEqual(db.load_qualitative(path.stem)['results'][0]['suggested_score'], 7)
        self.assertEqual(db.rescore_qualitative(), planned)
        for document in (load_saved_reviews(path.stem), load_reviews(path)):
            results = document['results']
            self.assertEqual([(r['suggested_score'], r['final_score'], r['scoring_version']) for r in results],
                             [(8, 8, SCORING_VERSION), (8, 9, SCORING_VERSION), (8, None, SCORING_VERSION)])
            self.assertEqual((results[0]['score_migration']['previous_suggested_score'],
                              results[0]['score_migration']['previous_final_score']), (7, 7))
            self.assertEqual(document['context']['scoring_version'], SCORING_VERSION)
        self.assertEqual(db.latest_qualitative_reviews('system_1_2026', 'midterm', ['copy.c'])[0]['final_score'], 8)
        self.assertEqual(db.rescore_qualitative(), [])

    def test_import_qualitative_loads_each_archive_once(self):
        folder = self.root / 'reports'; folder.mkdir()
        rows = self.review_rows()
        for name, version in [('qualitative_20261026_103843_af3803', 1), ('qualitative_20261027_160320_5b98c4', 2)]:
            (folder / f'{name}.json').write_text(json.dumps({'version': version, 'context': {'run_state': 'finished'}, 'results': rows}), encoding='utf-8')
        (folder / 'qualitative_bad.json').write_text('{"version": 9}', encoding='utf-8')
        (folder / 'other.json').write_text('{}', encoding='utf-8')
        self.assertEqual(db.import_qualitative(folder), ['qualitative_20261026_103843_af3803', 'qualitative_20261027_160320_5b98c4'])
        self.assertEqual(db.import_qualitative(folder), [])
        (folder / 'live.json').write_text(json.dumps({'version': 2, 'context': {'run_state': 'running'}, 'results': rows[:1]}), encoding='utf-8')
        (folder / 'live.json').rename(folder / 'qualitative_20261028_115134_94b9b3.json')
        self.assertEqual(db.import_qualitative(folder), ['qualitative_20261028_115134_94b9b3'])
        self.assertEqual(db.import_qualitative(folder), ['qualitative_20261028_115134_94b9b3'])
        self.assertEqual(db.import_qualitative(self.root / 'nowhere'), [])
        document = db.load_qualitative('qualitative_20261027_160320_5b98c4')
        self.assertEqual((document['version'], document['results'], document['created_at']), (2, rows, '2026-10-27T07:03:30+00:00'))
        self.assertEqual(db.list_qualitative()[0]['class_name'], 'system_1_2026')
        self.assertEqual(db.main(['import', '--root', str(self.root / 'nowhere')]), None)

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
