import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from reference_program import snapshot_reference, ReferenceProgram
from llm_cases import fill_from_reference, verify_with_reference, verification_matches, validate_bundle, bundle_digest


class ReferenceProgramTests(unittest.TestCase):
    def test_snapshot_preserves_layout_and_copies_only_selected_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, content in {'src/main.c': 'int main(void){return 0;}',
                                  'include/util.h': 'int value(void);',
                                  'lib/util.c': 'int value(void){return 1;}',
                                  'src/other.c': 'invalid unselected source'}.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            selected = [root / name for name in ('src/main.c', 'include/util.h', 'lib/util.c')]
            program = snapshot_reference(selected)
            self.assertEqual(program.entry, 'src/main.c')
            self.assertEqual(program.runner_config['sources'], ['lib/util.c', 'src/main.c'])
            self.assertIn('-Iinclude', program.runner_config['cflags'])
            (root / 'include/util.h').write_text('changed header')
            self.assertNotEqual(program.digest, snapshot_reference(selected).digest)
            program.copy_to(root / 'work')
            self.assertEqual((root / 'work/include/util.h').read_text(), 'int value(void);')
            self.assertFalse((root / 'work/src/other.c').exists())

    def test_header_only_mixed_language_and_invalid_entry_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / name for name in ('main.c', 'main.py', 'util.h')]
            for path in paths: path.write_text('')
            for selected, entry in (([], None), ([paths[2]], None), (paths[:2], None),
                                     ([paths[0], paths[2]], 'util.h')):
                with self.subTest(selected=selected), self.assertRaises(ValueError):
                    snapshot_reference(selected, entry)

    def test_verification_evidence_describes_the_snapshot_that_was_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / 'main.c'; main.write_text('int main(void){return 0;}')
            header = Path(temp) / 'util.h'; header.write_text('original')
            bundle = validate_bundle({'cases': [{'name': 'one', 'expected': 'ok'}]})
            executed = []
            def oracle(data, program, progress):
                executed.append(program)
                header.write_text('edited while verification was running')
                return bundle
            with patch('llm_cases.fill_from_reference', side_effect=oracle):
                result, evidence = verify_with_reference(bundle, [main, header])
            self.assertIs(executed[0], executed[1])
            self.assertIsInstance(executed[0], ReferenceProgram)
            self.assertEqual(len(evidence['reference_files']), 2)
            self.assertTrue(verification_matches(result, {'verification': evidence}))
            self.assertFalse(verification_matches(result, {'verification': evidence}, [main, header]))


@unittest.skipUnless(os.environ.get('SWLAB_TEST_DOCKER') == '1', 'Docker integration disabled')
class ReferenceProgramDockerTests(unittest.TestCase):
    def test_c_sources_and_headers_in_different_directories_compile_together(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = {'src/main.c': '#include <stdio.h>\n#include "util.h"\nint main(void){int n;scanf("%d",&n);printf("%d\\n",twice(n));}',
                       'lib/util.c': '#include "util.h"\nint twice(int n){return 2*n;}',
                       'include/util.h': 'int twice(int n);'}
            for name, text in sources.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            (root / 'src/unselected.c').write_text('int main(void){return 1;}')
            bundle = {'cases': [{'name': 'positive', 'input': '3', 'expected': 'AI guess'},
                                {'name': 'negative', 'input': '-4', 'expected': 'AI guess'}]}
            result, evidence = verify_with_reference(bundle, [root / name for name in sources])
            self.assertEqual([case['expected'] for case in result['cases']], ['6\n', '-8\n'])
            self.assertEqual(len(evidence['reference_files']), 3)
            self.assertEqual(len(evidence['corrections']), 2)

    def test_python_entry_and_helper_module_are_both_available(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / 'runner.py'
            helper = Path(temp) / 'helper.py'
            main.write_text('from helper import twice\nprint(twice(int(input())))')
            helper.write_text('def twice(value): return value * 2')
            program = snapshot_reference([helper, main], 'runner.py')
            bundle = {'cases': [{'name': 'one', 'input': '7', 'expected': 'AI guess'}]}
            result = fill_from_reference(bundle, program)
            self.assertEqual(result['cases'][0]['expected'], '14\n')


class ReferenceSelectionGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_multiselect_keeps_all_sources_and_changing_a_header_requires_reverification(self):
        from ai_case_generator import AICaseMaker
        with tempfile.TemporaryDirectory() as temp, patch('ai_case_generator.build_catalog', return_value=[]):
            root = Path(temp)
            paths = [root / name for name in ('main.c', 'util.c', 'util.h')]
            for path in paths: path.write_text('original')
            window = AICaseMaker('system', 'chap1', 'prob1')
            try:
                with patch('ai_case_generator.QFileDialog.getOpenFileNames', return_value=([str(p) for p in paths], '')):
                    window.browse_reference()
                self.assertEqual(len(window.reference_files), 3)
                self.assertEqual(window.reference_entry.currentData(), 'main.c')
                self.assertEqual(window.reference_entry.count(), 2)
                self.assertIn('util.h', window.reference.toolTip())
                bundle = {'cases': [{'name': 'one', 'expected': 'ok'}]}
                with patch('llm_cases.fill_from_reference', return_value=validate_bundle(bundle)):
                    verified, evidence = verify_with_reference(bundle, window.selected_reference())
                window.show_result((verified, {'verification': evidence}))
                window.set_busy(False)
                self.assertTrue(window.save_button.isEnabled())
                window.reference_entry.setCurrentIndex(window.reference_entry.findData('util.c'))
                self.assertNotIn('verification', window.generated_metadata)
                self.assertFalse(window.save_button.isEnabled())
                window.reference_entry.setCurrentIndex(window.reference_entry.findData('main.c'))
                window.show_result((verified, {'verification': evidence}))
                paths[2].write_text('changed header')
                window.update_quality()
                self.assertFalse(window.save_button.isEnabled())
                self.assertIn('변경', window.quality.text())
                window.save(True)
                self.assertIn('저장 실패', window.status.text())
                window.set_busy(True)
                self.assertFalse(window.reference_entry.isEnabled())
                self.assertFalse(window.reference_clear.isEnabled())
                window.set_busy(False)
                window.reference_clear.click()
                self.assertEqual(window.reference_files, ())
                self.assertEqual(window.reference.text(), '')
            finally:
                window.close()

    def test_generate_and_reverify_pass_the_entire_selection_to_the_oracle(self):
        from ai_case_generator import AICaseMaker
        with tempfile.TemporaryDirectory() as temp, patch('ai_case_generator.build_catalog', return_value=[]):
            paths = [Path(temp) / name for name in ('main.c', 'util.h')]
            for path in paths: path.write_text('original')
            window = AICaseMaker('system', 'chap1', 'prob1')
            try:
                window.url.setText('https://example.invalid'); window.model.setCurrentText('test-model')
                window.set_reference_files(paths)
                window.problem_text.setPlainText('Print ok')
                bundle = validate_bundle({'cases': [{'name': 'one', 'expected': 'ok'}]})
                def verify(data, program, wrong, progress):
                    self.assertEqual(len(program.files), 2)
                    return data, {'bundle_sha256': bundle_digest(data),
                        'reference_sha256': program.digest, 'repeated_runs': 2,
                        'corrections': [], 'wrong_programs': []}
                def run(function, callback, status): callback(function(lambda value: None))
                with patch.object(window, 'run_job', side_effect=run), \
                     patch('llm_cases.LLMClient.generate', return_value=bundle), \
                     patch('ai_case_generator.verify_with_reference', side_effect=verify) as oracle:
                    window.generate()
                    window.apply_reference()
                    self.assertEqual(oracle.call_count, 2)
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
