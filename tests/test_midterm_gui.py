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
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401  isolates the SQLite store
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
        support.isolate(self)
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

    def test_saved_runs_are_listed_per_chapter_and_reload_from_the_database(self):
        import db
        w = self.window
        (w.radioWin if os.name == 'nt' else w.radioLinux).setChecked(True)
        self.assertEqual(w.comboRuns.count(), 1)
        def grade(folder, bundle, config):
            return [dict(case=c['target_file'] + ' / ' + c['name'], target_file=c['target_file'], passed=True, status='passed')
                    for c in bundle['cases']]
        with patch('midterm.grade_suite', side_effect=grade):
            w.gradeSelected(); self.finish_job()
        first = w.case_report.directory.name
        self.assertEqual([w.comboRuns.itemData(i) for i in range(w.comboRuns.count())], [None, first])
        self.assertIsNone(w.comboRuns.currentData())
        self.assertEqual(w.comboRuns.currentText(), '최신 점수표 (기본)')
        self.assertIn('중간고사 전체 · 완료 · 2명', w.comboRuns.itemText(1))
        w.comboProblem.setCurrentIndex(w.comboProblem.findData('copy.c'))
        with patch('midterm.grade_suite', side_effect=grade):
            w.gradeSelected(); self.finish_job()
        second = w.case_report.directory.name
        self.assertEqual([w.comboRuns.itemData(i) for i in range(w.comboRuns.count())], [None, second, first])
        self.assertEqual(len(w.results), 10)
        # The run.json export is gone, the database still has every row.
        import shutil; shutil.rmtree(w.case_report.directory.parent)
        w.comboRuns.setCurrentIndex(w.comboRuns.findData(first)); w.loadSavedRun()
        self.assertEqual(w.case_report.directory.name, first)
        self.assertEqual(len(w.results), 72)
        self.assertEqual(w.resultTable.item(0, 3).text(), '75 / 75')
        self.assertIn('저장된 실행 상태: completed', w.log_output.toPlainText())
        w.comboChapter.setCurrentText('chap1')
        self.assertEqual(w.comboRuns.count(), 1)
        w.comboChapter.setCurrentText('midterm')
        self.assertEqual(w.comboRuns.count(), 3)
        self.assertEqual(db.list_runs('system_3_2026', 'midterm')[0]['id'], second)

    def test_file_catalog_counts_preview_and_switch_back_to_regular_chapter(self):
        w = self.window
        self.assertEqual(w.comboProblem.count(), 8)
        self.assertEqual(w.selectedProblem(), ALL_TARGETS)
        self.assertEqual(w.active_case_count, 36)
        self.assertTrue(w.midtermPanel.isVisible())
        self.assertFalse(w.btnCasePath.isVisible())
        for source, count in zip(TARGETS, [5, 3, 4, 10, 3, 7, 4]):
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
        self.assertEqual(len(w.results), 72)
        archive = w.case_report.directory / 'run.json'
        _, saved = CaseReport.open(archive)
        self.assertEqual(saved['state'], 'completed')
        self.assertEqual(len(saved['context']['midterm_suite']['cases']), 36)
        self.assertEqual(saved['context']['midterm_suite']['available_policy'], 'true_means_available')
        self.assertEqual(w.resultTable.item(0, 11).text(), '35 / 36')
        self.assertEqual(w.resultTable.item(0, 3).text(), '73 / 75')
        self.assertEqual(w.resultTable.horizontalHeaderItem(12).text(), '사유')
        self.assertIn('필수 4/5 통과', w.resultTable.item(0, 12).text())
        self.assertIn('검토 필요', w.resultTable.item(1, 12).toolTip())
        self.assertEqual(w.resultTable.item(1, 2).text(), '검토 필요')
        self.assertEqual(w.resultTable.item(1, 3).text(), '검토 필요')
        w.resultTable.selectRow(0)
        self.assertIn('Luster', w.resultDetail.toPlainText())
        self.assertIn('실행 단계: bookupdate.c', w.resultDetail.toPlainText())
        with patch('gui.QFileDialog.getOpenFileName', return_value=(str(archive), '')):
            w.readCaseReport()
        self.assertEqual(len(w.results), 72)
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
        self.assertEqual(w.resultTable.item(0, 3).text(), '75 / 75')
        self.assertIn('manual review of copy output', w.resultDetail.toPlainText())
        self.assertIn('수동 조정', w.resultTable.item(0, 12).text())
        export = self.root / 'grades.csv'
        with patch('gui.QFileDialog.getSaveFileName', return_value=(str(export), '')):
            w.exportResults()
        import csv
        with export.open(encoding='utf-8-sig', newline='') as stream:
            summary = next(csv.DictReader(stream))
        self.assertEqual(summary['auto_score'], '73.0')
        self.assertEqual(summary['final_score'], '75.0')
        self.assertIn('manual review of copy output', summary['reason'])

    def test_midterm_score_sorting_uses_numbers_and_preserves_student_on_refresh(self):
        from PyQt6.QtCore import Qt
        w=self.window
        for i,name in enumerate(('나학생','가학생')):
            w.listStudents.item(i).setData(Qt.ItemDataRole.UserRole,name)
        w.comboProblem.setCurrentIndex(w.comboProblem.findData('copy.c'))
        (w.radioWin if os.name=='nt' else w.radioLinux).setChecked(True)
        def grade(folder,bundle,config):
            return [dict(case=c['target_file']+' / '+c['name'],target_file=c['target_file'],
                         status='wrong_answer' if folder.parent.name=='101' and i==0 else 'passed',
                         passed=not(folder.parent.name=='101' and i==0)) for i,c in enumerate(bundle['cases'])]
        with patch('midterm.grade_suite',side_effect=grade):
            w.gradeSelected();self.finish_job()
        table=w.resultTable
        self.assertEqual([table.horizontalHeaderItem(i).text() for i in range(2)],['학번','이름'])
        table.selectRow(0)
        table.sortItems(3,Qt.SortOrder.AscendingOrder)
        self.assertEqual([table.item(i,0).text() for i in range(2)],['101','102'])
        self.assertEqual([table.item(i,3).text() for i in range(2)],['8 / 10','10 / 10'])
        table.sortItems(3,Qt.SortOrder.DescendingOrder)
        self.assertEqual([table.item(i,0).text() for i in range(2)],['102','101'])
        self.assertEqual(w.resultStudent(table.currentRow()),'101')
        w.case_report.override_midterm_score('101','copy.c',10,'teacher','정렬 후 점수 조정')
        w.refreshResultsTable()
        self.assertEqual(w.resultStudent(table.currentRow()),'101')
        self.assertEqual(table.item(table.currentRow(),3).text(),'10 / 10')
        self.assertIn('정렬 후 점수 조정',w.resultDetail.toPlainText())

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

    def test_qualitative_review_gets_exam_statement_file_scope_and_points(self):
        w = self.window
        w.listStudents.clearSelection()
        for index in range(w.listStudents.count()):
            w.listStudents.item(index).setSelected(True)
        w.comboProblem.setCurrentIndex(w.comboProblem.findData('copy.c'))
        with patch('qualitative_gui.QualitativeWindow') as window:
            window.return_value.isVisible.return_value = False
            w.openQualitative()
        submissions, preset = window.call_args.args
        self.assertEqual([s['student'] for s in submissions], ['101', '102'])
        self.assertEqual(Path(submissions[0]['path']).name, 'midterm')
        self.assertEqual(submissions[0]['problem'], 'copy.c')
        self.assertEqual(submissions[0]['sources'], ['copy.c', '*.h'])
        self.assertIn('옵션은 명령어의 인자값으로 전달', preset['problem'])
        self.assertEqual([r['max_score'] for r in preset['rubric']], [10] * 7)
        w.comboProblem.setCurrentIndex(w.comboProblem.findData(ALL_TARGETS))
        with patch('qualitative_gui.QualitativeWindow') as window:
            window.return_value.isVisible.return_value = False
            w.openQualitative()
        submissions, preset = window.call_args.args
        self.assertEqual(submissions[0]['problem'], ALL_TARGETS)
        self.assertEqual(preset['points'], 75)
        self.assertEqual(len(submissions[0]['sources']), 8)
        # DCUCode axes keep their scale; problem points are separate.
        from qualitative_gui import QualitativeWindow
        real = QualitativeWindow(submissions, preset)
        try:
            self.assertIn('중간고사', real.windowTitle())
            self.assertIn('sortedbookcreate.c', real.problem_text.toPlainText())
            self.assertEqual(real.rubric_table.rowCount(), 7)
            self.assertEqual([r['max_score'] for r in real.read_rubric()], [10] * 7)
            self.assertEqual(real.problem_points.value(), 75)
            self.assertIn('75점', real.source_summary.text())
        finally:
            real.close()
        w.comboChapter.setCurrentText('chap1')
        with patch('qualitative_gui.QualitativeWindow') as window:
            w.openQualitative()
        submissions, preset = window.call_args.args
        self.assertIsNone(preset)
        self.assertNotIn('sources', submissions[0])

    def test_names_appear_in_main_and_qualitative_lists_while_ids_stay_unchanged(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QStyleOptionViewItem
        w=self.window
        with patch('student_names.read_student_names',return_value={'101':'첫 학생','102':'둘째 학생'}):
            w.onClassSelected()
        w.comboChapter.setCurrentText('midterm')
        item=w.listStudents.item(0)
        self.assertEqual(item.text(),'101')
        self.assertEqual(item.data(Qt.ItemDataRole.UserRole),'첫 학생')
        option=QStyleOptionViewItem()
        w.listStudents.itemDelegate().initStyleOption(option,w.listStudents.model().index(0,0))
        self.assertEqual(option.text,'101 · 첫 학생')
        w.comboProblem.setCurrentIndex(w.comboProblem.findData('copy.c'))
        w.openQualitative();review=w.qualitative_window;self.addCleanup(review.close)
        self.assertEqual(review.table.item(0,0).text(),'101')
        self.assertEqual(review.table.item(0,1).text(),'첫 학생')
        self.assertEqual(review.submissions[0]['student'],'101')
        self.assertEqual(Path(review.submissions[0]['path']).parent.name,'101')
        review.student_search.setText('102')
        self.assertEqual(review.table.item(review.table.currentRow(),0).text(),'102')
        self.assertEqual(review.table.item(review.table.currentRow(),1).text(),'둘째 학생')
        review.close()
        # Grading results keep the ID as the key while the table, log and CSV/JSON carry the name.
        (w.radioWin if os.name == 'nt' else w.radioLinux).setChecked(True)
        with patch('midterm.grade_suite',return_value=[dict(case='copy.c / x',target_file='copy.c',passed=True,status='passed')]), \
                patch.object(QMessageBox,'warning') as warning:
            w.gradeSelected();warning.assert_not_called();self.finish_job()
        self.assertEqual(w.case_report.context['student_names'],{'101':'첫 학생','102':'둘째 학생'})
        self.assertEqual([r['student_name'] for r in w.results],['첫 학생','둘째 학생'])
        self.assertEqual(w.resultTable.item(0,0).text(),'101')
        self.assertEqual(w.resultTable.item(0,1).text(),'첫 학생')
        self.assertEqual(w.resultStudent(0),'101')
        w.resultTable.selectRow(1)
        self.assertIn('102 · 둘째 학생',w.resultDetail.toPlainText())
        import csv
        with (w.case_report.directory/'summary.csv').open(encoding='utf-8-sig',newline='') as stream:summary=list(csv.DictReader(stream))
        self.assertEqual([(s['student'],s['student_name']) for s in summary],[('101','첫 학생'),('102','둘째 학생')])
        _,saved=CaseReport.open(w.case_report.directory/'run.json')
        self.assertEqual(saved['results'][1]['student_name'],'둘째 학생')

    def test_reopening_qualitative_syncs_current_main_selection(self):
        w=self.window
        w.comboProblem.setCurrentIndex(w.comboProblem.findData('copy.c'))
        w.listStudents.clearSelection();w.listStudents.item(0).setSelected(True)
        w.openQualitative();original=w.qualitative_window
        self.addCleanup(original.close)
        self.assertEqual([r['student'] for r in original.rows],['101'])
        w.listStudents.clearSelection();w.listStudents.item(1).setSelected(True)
        w.openQualitative()
        self.assertIs(w.qualitative_window,original)
        self.assertEqual([original.rows[i]['student'] for i in original.selected_indices()],['102'])
        self.assertEqual(original.start_button.text(),'선택 1명 일괄 정성평가')
        w.comboProblem.setCurrentIndex(w.comboProblem.findData('bookquery.c'))
        w.openQualitative();changed=w.qualitative_window
        self.addCleanup(changed.close)
        self.assertIsNot(changed,original)
        self.assertFalse(original.isVisible())
        self.assertEqual(changed.submissions[0]['problem'],'bookquery.c')
        self.assertEqual(changed.rows[0]['student'],'102')

    @unittest.skipUnless(os.environ.get('SWLAB_TEST_DOCKER') == '1', 'Set SWLAB_TEST_DOCKER=1')
    def test_docker_gui_grades_all_36_cases_from_flat_midterm(self):
        w = self.window
        w.listStudents.clearSelection(); w.listStudents.item(0).setSelected(True)
        w.radioDocker.setChecked(True)
        w.gradeSelected(); self.finish_job(180)
        self.assertEqual(len(w.results), 36)
        self.assertTrue(all(row['passed'] for row in w.results), [(r['case'], r.get('message')) for r in w.results if not r['passed']])
        self.assertEqual({r['target_file'] for r in w.results}, set(TARGETS))
        self.assertEqual(w.resultTable.item(0, 11).text(), '36 / 36')
        self.assertEqual(w.resultTable.item(0, 3).text(), '75 / 75')
        work = self.root / 'origin/system_3_2026/101/midterm'
        self.assertEqual((work / 'db.dat').read_bytes(), b'original student database')


if __name__ == '__main__':
    unittest.main()
