import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from llm_cases import LLMClient, validate_bundle, save_bundle, fill_from_reference, data_path, verify_with_reference, verification_matches
from grader import Grader


def example():
    return {'summary': 'copy test', 'review_notes': [], 'cases': [
        {'name': 'normal', 'description': 'copy data', 'input': '', 'args': ['input.txt', 'result.txt'],
         'fixtures': {'input.txt': 'hello\n'}, 'files': {'result.txt': 'hello\n'}, 'expected': None}]}


class LLMCaseTests(unittest.TestCase):
    def test_validates_defaults(self):
        bundle = validate_bundle(example())
        self.assertEqual(bundle['cases'][0]['exit_code'], 0)
        self.assertEqual(bundle['cases'][0]['comparison'], 'exact')

    def test_rejects_unsafe_paths_and_executable_files(self):
        for path in ['../secret', '/tmp/test', 'C:/test', 'a\\b', '.git/config', 'main.c', 'a/../b', 'CON.txt', 'AUX', 'a:b', 'a/./b']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                data_path(path)

    def test_rejects_executable_metadata(self):
        for field in ['sources', 'cflags', 'target_file', 'command', 'fixture_root', 'enabled']:
            bundle = example()
            bundle['cases'][0][field] = 'unexpected'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_bundle(bundle)

    def test_rejects_duplicate_case_names(self):
        bundle = example()
        bundle['cases'].append(dict(bundle['cases'][0], name='NORMAL'))
        with self.assertRaises(ValueError):
            validate_bundle(bundle)

    def test_llm_request_contains_problem_not_source(self):
        client = LLMClient('http://example.invalid:1234', 'model')
        with patch.object(client, '_request', return_value={'choices':[{'finish_reason':'stop', 'message':{'content':json.dumps(example())}}]}) as request:
            result = client.generate('Copy a file.', 2)
        route, payload = request.call_args.args
        self.assertEqual(route, '/chat/completions')
        self.assertEqual(payload['model'], 'model')
        self.assertIn('Copy a file.', payload['messages'][1]['content'])
        self.assertNotIn('reference', payload['messages'][1]['content'])
        self.assertEqual(len(result['cases']), 1)

    def test_truncated_generation_fails(self):
        client = LLMClient('https://example.invalid', 'test-model')
        with patch.object(client, '_request', return_value={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}):
            with self.assertRaisesRegex(ValueError, 'truncated'):
                client.generate('problem')

    def test_markdown_fence_response(self):
        client = LLMClient('https://example.invalid', 'test-model')
        response = '<think>private reasoning</think>\n```json\n' + json.dumps(example()) + '\n```'
        with patch.object(client, '_request', return_value={'choices':[{'message':{'content':response}}]}):
            self.assertEqual(len(client.generate('problem')['cases']), 1)

    def test_draft_disabled_and_active_loadable(self):
        with tempfile.TemporaryDirectory() as temp:
            draft = save_bundle(example(), Path(temp) / 'draft')
            self.assertEqual(Grader().load_test_cases(Path(temp) / 'draft'), [])
            active = save_bundle(example(), Path(temp) / 'active', True)
            cases = Grader().load_test_cases(Path(temp) / 'active')
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]['fixture_root'], '_fixtures')
            self.assertEqual((active[0] / '_fixtures/input.txt').read_text(), 'hello\n')

    def test_no_assertion_cannot_activate(self):
        bundle = example()
        bundle['cases'][0]['files'] = {}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'no expected assertion'):
                save_bundle(bundle, temp, True)
            self.assertEqual(len(save_bundle(bundle, temp, False)), 1)

    def test_fixture_input_txt_does_not_conflict_with_stdin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            student = root / 'student'
            student.mkdir()
            (student / 'main.py').write_text("from pathlib import Path; import sys; Path(sys.argv[2]).write_text(Path(sys.argv[1]).read_text())")
            save_bundle(example(), root / 'cases', True)
            cases = Grader().load_test_cases(root / 'cases')
            rows = Grader().grade_student(student, cases)
            self.assertTrue(rows[0]['passed'], rows)
            self.assertFalse((student / 'result.txt').exists())

    def test_same_content_reuses_existing_but_changed_content_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            first = save_bundle(example(), temp, True)
            second = save_bundle(example(), temp, True)
            self.assertEqual(first, second)
            self.assertTrue(first[0].is_dir())
            changed = example()
            changed['cases'][0]['fixtures']['input.txt'] = 'different input'
            third = save_bundle(changed, temp, True)
            self.assertNotEqual(first, third)
            self.assertEqual(len(Grader().load_test_cases(temp)), 2)

    def test_rejects_duplicate_inputs_even_with_other_names_or_answers(self):
        bundle = example()
        bundle['cases'].append(dict(bundle['cases'][0], name='other', expected='contradiction'))
        with self.assertRaisesRegex(ValueError, '중복'):
            validate_bundle(bundle)

    def test_reference_repetition_and_edits_invalidate_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'main.py'
            source.write_text('print(1)')
            first = validate_bundle(example())
            second = validate_bundle(example())
            second['cases'][0]['files']['result.txt'] = 'changed'
            with patch('llm_cases.fill_from_reference', side_effect=[first, second]):
                with self.assertRaisesRegex(ValueError, '반복 실행'):
                    verify_with_reference(example(), source)
            with patch('llm_cases.fill_from_reference', return_value=first):
                bundle, evidence = verify_with_reference(example(), source)
            self.assertTrue(verification_matches(bundle, {'verification': evidence}))
            bundle['cases'][0]['input'] = 'edited'
            self.assertFalse(verification_matches(bundle, {'verification': evidence}))


@unittest.skipUnless(os.environ.get('SWLAB_TEST_DOCKER') == '1', 'Docker integration disabled')
class ReferenceTests(unittest.TestCase):
    def test_longest_line_regression_suite_detects_three_known_defects(self):
        root = Path(__file__).resolve().parents[1]
        bundle = json.loads((root / 'examples/longest_line/cases.json').read_text(encoding='utf-8'))
        result, evidence = verify_with_reference(bundle, root / 'examples/longest_line/main.c',
                                  sorted((root / 'tests/fixtures/longest_line').glob('*/main.c')))
        self.assertEqual(len(result['cases']), 10)
        self.assertEqual(evidence['corrections'], [])
        self.assertEqual(len(evidence['wrong_programs']), 3)

    def test_reference_error_exit_is_not_blessed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'main.py'
            source.write_text('raise SystemExit(1)')
            with self.assertRaisesRegex(ValueError, '예상 0, 실제 1'):
                fill_from_reference(example(), source)

    def test_wrong_program_surviving_is_rejected_and_caught_program_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'reference/main.py'
            source.parent.mkdir()
            source.write_text('import sys; print(max(sys.stdin.read().splitlines(), key=len))')
            wrong = Path(temp) / 'wrong/main.py'
            wrong.parent.mkdir()
            wrong.write_text('import sys; print(max(sys.stdin.read().split(), key=len))')
            weak = {'cases': [{'name': 'weak', 'input': 'a\nbbb\n', 'expected': 'bbb\n'}]}
            with self.assertRaisesRegex(ValueError, '검사 누락'):
                verify_with_reference(weak, source, [wrong])
            strong = {'cases': [{'name': 'spaces', 'input': 'abc\na bc\n', 'expected': 'WRONG AI ANSWER'}]}
            bundle, evidence = verify_with_reference(strong, source, [wrong])
            self.assertEqual(bundle['cases'][0]['expected'], 'a bc\n')
            self.assertEqual(len(evidence['corrections']), 1)
            self.assertEqual(evidence['wrong_programs'][0]['detected_by'], ['spaces'])

    def test_oracle_corrects_llm_expected_file(self):
        bundle = example()
        bundle['cases'][0]['files']['result.txt'] = 'wrong prediction'
        source = Path(__file__).resolve().parents[1] / 'examples/copy/main.c'
        result = fill_from_reference(bundle, source)
        self.assertEqual(result['cases'][0]['files']['result.txt'], 'hello\n')
        self.assertEqual(bundle['cases'][0]['files']['result.txt'], 'wrong prediction')

    def test_oracle_failure_is_not_an_expected_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'main.c'
            source.write_text('invalid c;')
            with self.assertRaisesRegex(ValueError, 'Reference execution failed'):
                fill_from_reference(example(), source)


if __name__ == '__main__':
    unittest.main()
