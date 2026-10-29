import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401  isolates the SQLite store
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ai_case_generator import AICaseMaker
from case_catalog import problem_catalog
from gui import Gui
from llm_cases import bundle_digest
from materials import read_deck
from paths import lecture_name
from slide_picker import SlidePicker, problem_heading


DECKS = [dict(source='lecture.pptx', title='4장 실습', chapter=4, slides=[
    dict(page=1, text='실습 4'),
    dict(page=2, text='실습 1 – cat\n내용'),
    dict(page=3, text='실습 2 – 파일 복사\n요구사항'),
    dict(page=4, text='실습 2 – 파일 복사\n코드', has_images=True),
    dict(page=5, text='과제 2 – 추가 기능'),
])]
BUNDLE = {'cases': [{'name': 'one', 'input': 'abc', 'expected': 'abc'}]}


def write_case(root, name, enabled=True):
    folder = root / name; folder.mkdir(parents=True)
    (folder / 'case.json').write_text(json.dumps({'expected': 'ok', 'enabled': enabled}), encoding='utf-8')


class CaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def maker(self, chapter='chap4', problem='prob2'):
        with patch('ai_case_generator.build_catalog', return_value=DECKS):
            window = AICaseMaker('system_3_2026', chapter, problem)
        self.addCleanup(window.close)
        return window

    def test_picker_selects_problem_pages_and_blocks_mixed_problems(self):
        picker = SlidePicker(DECKS, 'chap4', 'prob2')
        self.addCleanup(picker.close)
        self.assertEqual([s['page'] for s in picker.selected_slides()], [3, 4])
        self.assertIn('이미지', picker.summary.text())
        picker.pages.item(1).setSelected(True)
        self.assertFalse(picker.use_button.isEnabled())
        picker.pages.setCurrentRow(2)
        picker.select_problem()
        self.assertEqual([s['page'] for s in picker.selected_slides()], [3, 4])
        picker.accept_selection()
        self.assertEqual(picker.selection['problem'], ['prob', 2])
        self.assertIn('코드', picker.selection['text'])

    def test_heading_does_not_confuse_chapter_title_or_homework(self):
        self.assertIsNone(problem_heading('실습 3'))
        self.assertEqual(problem_heading('실습 문제 2 – 파일 열기'), ('prob', 2))
        self.assertEqual(problem_heading('연습문제 2번 - 확장'), ('hw', 2))

    def test_slide_selection_fills_target_and_preserves_existing_alias(self):
        window = self.maker('chap3', 'prod1')
        selection = dict(source='lecture.pptx', title='3장', chapter=3, pages=[2],
                         problem=['prob', 1], text='문제', has_images=False)
        window.apply_slide_selection(selection)
        self.assertEqual(window.problem.text(), 'prod1')
        window.apply_slide_selection(dict(selection, chapter=4, problem=['prob', 2]))
        self.assertEqual(window.chapter.text(), 'chap4')
        self.assertEqual(window.problem.text(), 'prob2')
        self.assertIn('4장 · 문제 2번', window.target_summary.text())
        window.problem.setText('prob3')
        with patch('llm_cases.LLMClient.generate') as generate:
            window.generate()
            generate.assert_not_called()
        self.assertIn('번호가 다릅니다', window.status.text())

    def test_context_changes_cannot_save_old_cases_under_new_target(self):
        window = self.maker()
        window.problem_text.setPlainText('Echo')
        window.show_result((BUNDLE, {})); window.manual_review.setChecked(True)
        self.assertTrue(window.save_button.isEnabled())
        for field, changed, original in [(window.problem, 'prob3', 'prob2'),
                (window.chapter, 'chap5', 'chap4'), (window.course, 'other_3_2026', 'system_3_2026')]:
            field.setText(changed); window.manual_review.setChecked(True)
            self.assertFalse(window.save_button.isEnabled())
            with patch('ai_case_generator.save_bundle') as save:
                window.save(True); save.assert_not_called()
            field.setText(original)
        window.problem_text.setPlainText('Different problem')
        self.assertIn('문제 설명이 바뀌었습니다', window.quality.text())

    def test_target_is_required_before_network_request_and_numbers_normalize(self):
        window = self.maker('', '')
        window.problem_text.setPlainText('Echo')
        with patch('llm_cases.LLMClient.generate') as generate:
            window.generate(); generate.assert_not_called()
        window.chapter.setText('4'); window.problem.setText('2'); window.normalize_target()
        self.assertEqual(window.read_target(), {'course': 'system', 'chapter': 'chap4', 'problem': 'prob2'})

    def test_reference_selection_change_invalidates_verification(self):
        window = self.maker()
        evidence = dict(bundle_sha256=bundle_digest(BUNDLE), repeated_runs=2, corrections=[], wrong_programs=[])
        window.show_result((BUNDLE, {'verification': evidence})); window.set_busy(False)
        self.assertTrue(window.save_button.isEnabled())
        window.reference.setText('different.c')
        self.assertFalse(window.save_button.isEnabled())
        window.set_busy(True)
        self.assertFalse(window.reference_browse.isEnabled())

    def test_case_only_problems_are_prioritized_without_student_folders(self):
        with tempfile.TemporaryDirectory() as temp, patch('paths.TESTCASES', Path(temp)):
            root = Path(temp) / 'system/chap4'
            write_case(root, 'prob2/one')
            write_case(root, 'prob3/draft', False)
            rows = problem_catalog('system_3_2026', 'chap4', ['prob1'])
            self.assertEqual([r['name'] for r in rows], ['prob2', 'prob3', 'prob1'])
            self.assertEqual(rows[1]['drafts'], 1)
            with patch.object(Gui, 'refreshYearList'):
                window = Gui()
            try:
                window.eval.get_student_list = lambda _: []
                window.comboClass.addItem('분반', 'system_3_2026')
                self.assertEqual(window.selectedProblem(), 'prob2')
                self.assertIn('채점 1개', window.comboProblem.currentText())
                self.assertEqual(Path(window.txtTestCasePath.text()), root / 'prob2')
                write_case(root, 'prob4/new')
                window.onAICasesSaved(dict(enabled=True, class_name='system_3_2026',
                    chapter='chap4', problem='prob4', count=1, destination=str(root / 'prob4')))
                self.assertEqual(window.selectedProblem(), 'prob4')
                self.assertEqual(Path(window.txtTestCasePath.text()), root / 'prob4')
            finally:
                window.close()

    def test_legacy_flat_cases_are_not_presented_as_problem_names(self):
        with tempfile.TemporaryDirectory() as temp, patch('paths.TESTCASES', Path(temp)):
            root = Path(temp) / 'system/chap4'
            write_case(root, 'empty'); write_case(root, 'normal')
            self.assertEqual(problem_catalog('system', 'chap4'), [])

    def test_course_names_with_underscores_remain_intact(self):
        self.assertEqual(lecture_name('python_test_2_2026'), 'python_test')
        self.assertEqual(lecture_name('python_test'), 'python_test')

    def test_ppt_uses_presentation_order_not_zip_filename_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'reordered.pptx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('ppt/presentation.xml', '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="1" r:id="second"/><p:sldId id="2" r:id="first"/></p:sldIdLst></p:presentation>')
                archive.writestr('ppt/_rels/presentation.xml.rels', '<Relationships><Relationship Id="first" Target="slides/slide1.xml"/><Relationship Id="second" Target="slides/slide9.xml"/></Relationships>')
                for name, text in [('slide1.xml', 'AFTER'), ('slide9.xml', 'FIRST')]:
                    archive.writestr('ppt/slides/' + name, f'<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:r><a:t>{text}</a:t></a:r></a:p>')
            slides = read_deck(path)
            self.assertEqual([s['text'] for s in slides], ['FIRST', 'AFTER'])
            self.assertEqual([s['page'] for s in slides], [1, 2])
