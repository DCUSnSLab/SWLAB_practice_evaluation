import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from gui import Gui, LoadWorker, LogWindow
from evaluator import Evaluator


class FakeManager(QObject):
    log_message = pyqtSignal(str)

    def __init__(self, student, lec):
        super().__init__()
        self.student = student
        self.last_error = ''

    def syncCode(self):
        if self.student.sid == 102:
            self.last_error = '로컬 수정 파일이 있습니다.'
            return False
        if self.student.sid == 103:
            raise RuntimeError('연결 실패 <retry>')
        return True


class SyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_counts_each_student_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            roster = Path(temp) / '2026/system_1.csv'
            roster.parent.mkdir()
            roster.write_text('101,첫학생,https://github.com/a/syspro\n'
                              '102,둘학생,https://github.com/b/syspro\n'
                              '103,셋학생,https://github.com/c/syspro\n'
                              '104,끝학생,https://github.com/d/syspro\n', encoding='utf-8')
            worker = LoadWorker()
            done, progress, maxima = [], [], []
            worker.done_message.connect(done.append)
            worker.in_progress_message.connect(progress.append)
            worker.set_progress_value.connect(maxima.append)
            with patch('lecture.gitManager', FakeManager), patch('paths.ORIGIN',Path(temp)/'origin'), patch('paths.ROOT',Path(temp)):
                worker.do_work(str(roster))
                from student_names import read_student_names
                self.assertEqual(read_student_names('system_1_2026')['102'],'둘학생')
            self.assertEqual(len(done), 1)
            summary = done[0]
            self.assertEqual((summary['total'], summary['success'], summary['failed']), (4, 2, 2))
            self.assertEqual(progress, [1, 2, 3, 4])
            self.assertEqual(maxima, [4])
            self.assertEqual(summary['results'][1]['name'], '둘학생')
            self.assertEqual(summary['results'][1]['student_id'], '102')
            self.assertIn('로컬 수정', summary['results'][1]['error'])
            self.assertIn('연결 실패', summary['results'][2]['error'])
            self.assertTrue(summary['results'][3]['success'])
            with patch.object(Gui, 'refreshYearList'):
                window = Gui()
                window.log_window = LogWindow()
                try:
                    window.setBusy(True)
                    window.loadFinished(summary)
                    self.assertIn('성공 2명 / 실패 2명', window.log_window.summary_label.text())
                    self.assertEqual(window.log_window.failure_table.rowCount(), 2)
                    self.assertEqual(window.log_window.failure_table.item(0, 0).text(), '둘학생')
                    self.assertEqual(window.log_window.failure_table.item(0, 1).text(), '102')
                    self.assertIn('연결 실패 <retry>', window.log_window.failure_table.item(1, 2).text())
                    self.assertIn('둘학생 (102)', window.log_output.toPlainText())
                    self.assertIn('연결 실패 <retry>', window.log_output.toPlainText())
                    self.assertEqual(window.btnLoad.text(), '저장소 동기화')
                    self.assertTrue(window.btnLoad.isEnabled())
                    window.log_window.show_summary({**summary, 'success': 4, 'failed': 0,
                        'results': [{**row, 'success': True, 'error': ''} for row in summary['results']]})
                    self.assertEqual(window.log_window.failure_table.rowCount(), 0)
                    self.assertTrue(window.log_window.failure_table.isHidden())
                finally:
                    window.log_window.close()
                    window.close()
                    self.app.processEvents()

    def test_invalid_roster_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            roster = Path(temp) / 'system_1.csv'
            roster.write_text('101,학생,https://github.com/a/syspro\n'
                              '101,중복,https://github.com/b/syspro\n', encoding='utf-8')
            worker = LoadWorker()
            done = []
            worker.done_message.connect(done.append)
            with patch('lecture.gitManager') as manager:
                worker.do_work(str(roster))
            manager.assert_not_called()
            self.assertEqual(len(done), 1)
            self.assertEqual(done[0]['total'], 0)
            self.assertIn('duplicate', done[0]['error'])
            log = LogWindow()
            try:
                log.show_summary(done[0])
                self.assertIn('시작하지 못했습니다', log.summary_label.text())
                self.assertNotIn('동기화 완료', log.summary_label.text())
            finally:
                log.close()


if __name__ == '__main__':
    unittest.main()
