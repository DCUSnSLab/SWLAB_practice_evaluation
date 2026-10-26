import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PyQt6.QtWidgets import QApplication, QMessageBox
from gui import Gui
from midterm import ALL_TARGETS, TARGETS, load_suite, grade_suite
from reports import CaseReport


class MidtermGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for student in ('101', '102'):
            work = self.root / 'origin/system_3_2026' / student / 'midterm'
            work.mkdir(parents=True)
            shutil.copy2(Path(__file__).parent / 'fixtures/midterm/library_fixture.h', work)
            for source in TARGETS:
                (work / source).write_text('#include "library_fixture.h"\nint main(int n, char **v) { return fixture_main(n, v, "'
                                          + Path(source).stem + '"); }\n', encoding='utf-8')
            (work / 'db.dat').write_bytes(b'original student database')
        for target, value in [('paths.ORIGIN', self.root / 'origin'), ('reports.ROOT', self.root)]:
            mock = patch(target, value); mock.start(); self.addCleanup(mock.stop)
        with patch.object(Gui, 'refreshYearList'):
            self.window = Gui()
        self.addCleanup(self.close_window)
        w = self.window
        w.eval.get_student_list = lambda *args: ['101', '102']
        w.eval.get_student_chapters = lambda *args: ['midterm', 'chap1']
        w.eval.get_student_problems = lambda *args: []
        self.file_queries = []
        def files(course, student, chapter, problem):
            self.file_queries.append((chapter, problem))
            return list(TARGETS) if chapter == 'midterm' and problem is None else []
        w.eval.get_student_files = files
        w.comboClass.addItem('테스트 분반', 'system_3_2026')
        w.comboChapter.setCurrentText('midterm')

    def close_window(self):
        w = self.window
        if w.job and w.job.isRunning():
            w.job.wait(180000)
        self.app.processEvents()
        w.close()
        self.app.processEvents()

    def finish_job(self, seconds=10):
        w = self.window
        self.assertIsNotNone(w.job)
        deadline = time.monotonic() + seconds
        while w.job.isRunning() and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(w.job.isRunning())
        self.assertTrue(w.btnGrade.isEnabled())

    def test_file_catalog_counts_preview_and_switch_back_to_regular_chapter(self):
        w = self.window
        self.assertEqual(w.comboProblem.count(), 8)
        self.assertEqual(w.selectedProblem(), ALL_TARGETS)
        self.assertEqual(w.active_case_count, 52)
        self.assertTrue(w.midtermPanel.isVisible())
        self.assertFalse(w.btnCasePath.isVisible())
        for source, count in zip(TARGETS, [21, 3, 4, 10, 3, 7, 4]):
            w.comboProblem.setCurrentIndex(w.comboProblem.findData(source))
            self.assertEqual(w.active_case_count, count)
            self.assertEqual(w.listFiles.currentItem().text(), source)
            self.assertIsNone(self.file_queries[-1][1])
        with patch.object(w.eval, 'get_file_content', return_value='preview') as read:
            w.onFileDoubleClicked(w.listFiles.currentItem())
            self.assertIsNone(read.call_args.args[3])
            self.assertEqual(read.call_args.args[4], 'sortedbookcreate.c')
        w.comboChapter.setCurrentText('chap1')
        self.assertFalse(w.midtermPanel.isVisible())
        self.assertTrue(w.btnCasePath.isVisible())

    def test_all_file_batch_autosaves_nested_details_and_review_status(self):
        w = self.window
        (w.radioWin if os.name == 'nt' else w.radioLinux).setChecked(True)
        seen = []
        def grade(folder, bundle, config):
            self.assertEqual(folder.name, 'midterm')
            self.assertIsNone(config['problem'])
            seen.append(folder.parent.name)
            rows = [dict(case=c['target_file'] + ' / ' + c['name'], target_file=c['target_file'],
                         passed=True, status='passed') for c in bundle['cases']]
            rows[-1].update(passed=False, status='wrong_answer' if folder.parent.name == '101' else 'needs_review',
                            actual=[[2, 'Luster', 'Raven', 2020, 3, False]],
                            expected=[[2, 'Luster', 'Raven', 2020, 4, False]],
                            trace=[dict(source='bookupdate.c', input='0 2\n', stdout='details', stderr='', returncode=0)])
            return rows
        with patch('midterm.grade_suite', side_effect=grade):
            w.gradeSelected()
            self.assertFalse(w.txtMidtermProfile.isEnabled())
            self.finish_job()
        self.assertEqual(seen, ['101', '102'])
        self.assertEqual(len(w.results), 104)
        archive = w.case_report.directory / 'run.json'
        _, saved = CaseReport.open(archive)
        self.assertEqual(saved['state'], 'completed')
        self.assertEqual(len(saved['context']['midterm_suite']['cases']), 52)
        self.assertEqual(saved['context']['midterm_suite']['available_policy'], 'true_means_available')
        self.assertEqual(w.resultTable.item(0, 10).text(), '51 / 52')
        self.assertEqual(w.resultTable.item(0, 2).text(), '74.52 / 75')
        self.assertEqual(w.resultTable.horizontalHeaderItem(11).text(), '사유')
        self.assertIn('필수 20/21 통과', w.resultTable.item(0, 11).text())
        self.assertIn('검토 필요', w.resultTable.item(1, 11).toolTip())
        self.assertEqual(w.resultTable.item(1, 1).text(), '검토 필요')
        self.assertEqual(w.resultTable.item(1, 2).text(), '검토 필요')
        w.resultTable.selectRow(0)
        self.assertIn('Luster', w.resultDetail.toPlainText())
        self.assertIn('실행 단계: bookupdate.c', w.resultDetail.toPlainText())
        with patch('gui.QFileDialog.getOpenFileName', return_value=(str(archive), '')):
            w.readCaseReport()
        self.assertEqual(len(w.results), 104)
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QLineEdit, QDoubleSpinBox, QPushButton
        def adjust():
            dialog = self.app.activeModalWidget()
            dialog.findChild(QDoubleSpinBox, 'midtermFinalScore').setValue(10)
            dialog.findChild(QLineEdit, 'midtermReviewer').setText('teacher')
            dialog.findChild(QLineEdit, 'midtermReason').setText('manual review of copy output')
            dialog.findChild(QPushButton, 'saveMidtermScore').click()
        QTimer.singleShot(0, adjust)
        w.adjustMidtermScore()
        self.assertEqual(w.resultTable.item(0, 2).text(), '75 / 75')
        self.assertIn('manual review of copy output', w.resultDetail.toPlainText())
        self.assertIn('수동 조정', w.resultTable.item(0, 11).text())
        export = self.root / 'grades.csv'
        with patch('gui.QFileDialog.getSaveFileName', return_value=(str(export), '')):
            w.exportResults()
        import csv
        with export.open(encoding='utf-8-sig', newline='') as stream:
            summary = next(csv.DictReader(stream))
        self.assertEqual(summary['auto_score'], '74.52')
        self.assertEqual(summary['final_score'], '75.0')
        self.assertIn('manual review of copy output', summary['reason'])

    def test_one_file_dispatch_manual_sources_and_invalid_profile(self):
        w = self.window
        w.comboProblem.setCurrentIndex(w.comboProblem.findData('bookquery.c'))
        w.listStudents.clearSelection(); w.listStudents.item(0).setSelected(True)
        (w.radioWin if os.name == 'nt' else w.radioLinux).setChecked(True)
        with patch('midterm.grade_suite', return_value=[]) as grade:
            w.gradeSelected(); self.finish_job()
            self.assertEqual({c['target_file'] for c in grade.call_args.args[1]['cases']}, {'bookquery.c'})
            self.assertEqual(grade.call_args.args[0].name, 'midterm')
        with patch('evaluator.Evaluator.run_manual_code', return_value=(True, 'manual', '')) as run:
            w.runManual(); self.finish_job()
            self.assertEqual(run.call_args.args[2]['sources'], ['bookquery.c'])
            self.assertIsNone(run.call_args.args[2]['problem'])
            self.assertEqual(run.call_args.args[5], 'bookquery.c')
        profile = self.root / 'bad.json'; profile.write_text('{}', encoding='utf-8')
        w.txtMidtermProfile.setText(str(profile))
        self.assertEqual(w.active_case_count, 0)
        with patch.object(QMessageBox, 'warning') as warning, patch('midterm.grade_suite') as grade:
            w.gradeSelected()
            self.assertTrue(warning.called)
            grade.assert_not_called()

    @unittest.skipUnless(os.environ.get('SWLAB_TEST_DOCKER') == '1', 'Set SWLAB_TEST_DOCKER=1')
    def test_docker_gui_grades_all_52_cases_from_flat_midterm(self):
        w = self.window
        w.listStudents.clearSelection(); w.listStudents.item(0).setSelected(True)
        w.radioDocker.setChecked(True)
        w.gradeSelected(); self.finish_job(180)
        self.assertEqual(len(w.results), 52)
        self.assertTrue(all(row['passed'] for row in w.results), [(r['case'], r.get('message')) for r in w.results if not r['passed']])
        self.assertEqual({r['target_file'] for r in w.results}, set(TARGETS))
        self.assertEqual(w.resultTable.item(0, 10).text(), '52 / 52')
        self.assertEqual(w.resultTable.item(0, 2).text(), '75 / 75')
        work = self.root / 'origin/system_3_2026/101/midterm'
        self.assertEqual((work / 'db.dat').read_bytes(), b'original student database')


if __name__ == '__main__':
    unittest.main()
