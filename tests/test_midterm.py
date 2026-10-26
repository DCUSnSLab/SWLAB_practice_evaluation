import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from grader import Grader
from midterm import (SUITE, COPY_CASES, ROW, parse_records, compare_records,
                     registration_input, library_case, copy_error_case, main)


class MidtermTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = json.loads((SUITE / 'scenarios.json').read_text(encoding='utf-8'))
        cls.profile = json.loads((SUITE / 'profile.json').read_text(encoding='utf-8'))

    def test_parse_numeric_title_prompts_and_boolean_representations(self):
        text = 'option > id bookName author year numofborrow borrow\n1 1984 George 1949 7 False\n2 Luster Raven 2020 3 1\n'
        self.assertEqual(parse_records(text, self.profile), [tuple(r) for r in self.suite['datasets']['exam'][:2]])
        self.assertEqual(parse_records('no books found', self.profile), [])

    def test_records_detect_wrong_count_missing_duplicate_and_case(self):
        records = self.suite['datasets']['exam']
        self.assertTrue(compare_records(records, records))
        self.assertFalse(compare_records(records[:-1], records))
        self.assertFalse(compare_records(records + [records[0]], records))
        changed = [list(r) for r in records]; changed[2][4] += 1
        self.assertFalse(compare_records(changed, records))
        changed = [list(r) for r in records]; changed[1][1] = 'luster'
        self.assertFalse(compare_records(changed, records))

    def test_sorting_allows_ties_but_rejects_wrong_direction(self):
        records = self.suite['datasets']['ties']
        ordered = sorted(records, key=lambda r: r[4], reverse=True)
        ordered[0], ordered[1] = ordered[1], ordered[0]
        self.assertTrue(compare_records(ordered, records, 'count'))
        self.assertFalse(compare_records(list(reversed(ordered)), records, 'count'))
        self.assertFalse(compare_records(records, records, 'year'))

    def test_registration_profile_supports_count_prefix_and_terminator(self):
        text = registration_input(self.suite['datasets']['single'],
                                  {**self.profile, 'create_prefix': '{n}\n', 'create_suffix': '-1\n'})
        self.assertEqual(text, '1\n3 Hamnet Maggie 2020 0 0\n-1\n')

    def test_cases_target_single_source_and_preserve_source_file(self):
        cases = Grader().load_test_cases(COPY_CASES)
        self.assertEqual(len(cases), 19)
        for case in cases:
            self.assertEqual(case['target_file'], 'copy.c')
            self.assertEqual(case['sources'], ['copy.c'])
            self.assertIn(case['args'][1], case['files'])
            self.assertIn(case['args'][2], case['files'])
        targets = {c['target_file'] for c in self.suite['cases']}
        self.assertEqual(len(targets), 7)
        self.assertEqual(len(self.suite['cases']), 33)

    def fake_library(self, case, corrupt_update=False, bad_seed=False, inverted_filter=False, ignore_case=False):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for source in ('bookcreate.c', 'bookquery.c', case['target_file']):
                (folder / source).touch()
            original = b'private original database'
            (folder / 'db.dat').write_bytes(original)
            state = []

            def execute(work, data, args, config, target_file=None):
                self.assertEqual(config['sources'], [target_file])
                out = ''
                if target_file == 'bookcreate.c':
                    state[:] = [list(r) for r in self.suite['datasets'][case['dataset']]]
                    (work / 'db.dat').write_bytes(b'private layout')
                elif target_file == 'bookupdate.c':
                    op, book_id = map(int, data.split())
                    for record in state:
                        if record[0] == book_id:
                            if not op and record[5]:
                                record[4] += 0 if corrupt_update else 1
                                record[5] = False
                            elif op == 1:
                                record[5] = True
                elif target_file == 'searchbook.c':
                    found = [r for r in state if (r[1].lower() == data.strip().lower() if ignore_case else r[1] == data.strip())]
                    out = '\n'.join(' '.join(map(str, r)) for r in found) if found else 'not found'
                else:
                    selected = state if data.strip() == '0' else [r for r in state if r[5] != inverted_filter]
                    out = '\n'.join(' '.join(map(str, r)) for r in selected)
                    if bad_seed:
                        out = 'prompt only'
                return dict(stdout=out, stderr='', returncode=0, timed_out=False, output_limit=False)

            with patch.object(Grader, 'execute', side_effect=execute):
                row = library_case(folder, case, self.suite['datasets'], self.profile, {})
            self.assertEqual((folder / 'db.dat').read_bytes(), original)
            return row

    def test_state_isolation_and_missing_count_increment_is_detected(self):
        case = next(c for c in self.suite['cases'] if c['name'] == 'borrow_return_borrow')
        self.assertTrue(self.fake_library(case)['passed'])
        wrong = self.fake_library(case, corrupt_update=True)
        self.assertEqual(wrong['status'], 'wrong_answer')
        self.assertIn('0 2', wrong['message'])

    def test_seed_failure_needs_review_instead_of_blame_on_update(self):
        case = next(c for c in self.suite['cases'] if c['name'] == 'borrow_available_luster')
        self.assertEqual(self.fake_library(case, bad_seed=True)['status'], 'needs_review')

    def test_true_means_available_and_case_sensitive_search(self):
        case = next(c for c in self.suite['cases'] if c['name'] == 'query_available')
        self.assertTrue(self.fake_library(case)['passed'])
        self.assertFalse(self.fake_library(case, inverted_filter=True)['passed'])
        case = next(c for c in self.suite['cases'] if c['name'] == 'search_case_sensitive')
        self.assertTrue(self.fake_library(case)['passed'])
        self.assertFalse(self.fake_library(case, ignore_case=True)['passed'])

    def test_cli_selects_flat_midterm_and_saves_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            submission = root / 'student'
            (submission / 'midterm').mkdir(parents=True)
            (submission / 'midterm/bookupdate.c').touch()
            output = root / 'result.json'
            def run_case(folder, case, datasets, profile, config):
                self.assertEqual(folder, submission / 'midterm')
                self.assertEqual(case['target_file'], 'bookupdate.c')
                return dict(case=case['name'], passed=True, status='passed', trace=[{'source': 'bookupdate.c'}])
            with patch('midterm.environment', return_value={'image_id': 'test-image'}), \
                 patch('midterm.library_case', side_effect=run_case) as runner:
                code = main([str(submission), '--target', 'bookupdate.c', '--output', str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(runner.call_count, 9)
            results = json.loads(output.read_text(encoding='utf-8'))['results']
            self.assertTrue(all(r['available_policy'] == 'true_means_available' for r in results))
            self.assertEqual(results[0]['trace'][0]['source'], 'bookupdate.c')
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['scores'][0]['final_score'], 10)

    @unittest.skipUnless(os.environ.get('SWLAB_TEST_DOCKER') == '1', 'Set SWLAB_TEST_DOCKER=1')
    def test_full_suite_with_private_binary_fixture_in_flat_midterm(self):
        targets = {c['target_file'] for c in self.suite['cases']}
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            shutil.copy2(Path(__file__).parent / 'fixtures/midterm/library_fixture.h', work)
            for source in targets:
                (work / source).write_text('#include "library_fixture.h"\nint main(int n, char **v) { return fixture_main(n, v, "'
                                          + Path(source).stem + '"); }\n', encoding='utf-8')
            config = {'mode': 'docker', 'timeout': 15}
            for row in Grader().grade_student(work, Grader().load_test_cases(COPY_CASES), config):
                self.assertTrue(row['passed'], row)
            for case in self.suite['cases']:
                with self.subTest(case=case['name']):
                    row = copy_error_case(work, case, config) if case['target_file'] == 'copy.c' else library_case(
                        work, case, self.suite['datasets'], self.profile, config)
                    self.assertTrue(row['passed'], row)


if __name__ == '__main__':
    unittest.main()
