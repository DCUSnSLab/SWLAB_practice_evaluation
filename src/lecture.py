from PyQt6.QtCore import QObject, pyqtSignal as Signal
from gitmanager import gitManager
from setup_logging import logger
from student import Student
from html import escape

class Lecture(QObject):
    log_message = Signal(str)
    def __init__(self, id:int, name:str, division:int):
        super().__init__()
        self.id = id
        self.name = name
        self.division = division
        self.students = dict()
        logger.name = __name__

    def getfilepath(self):
        return self.name + '_' + str(self.division) + '_' + str(self.id)
    def addStudent(self, stu:Student):
        self.students[stu.sid] = stu

    def getStudentList(self):
        return self.students.values()

    def getStudentbySID(self, sid:int) -> Student:
        return self.students[sid]

    def syncCodefromLecture(self,progress_signal):
        tcnt = len(self.getStudentList())
        results = []
        for idx, l in enumerate(self.getStudentList()):
            message = f'[{idx+1}/{tcnt}] {escape(l.name)} ({l.sid}) 저장소 동기화'
            logger.info(message)
            self.log_message.emit(message)

            try:
                gg = gitManager(student=l, lec=self)
                gg.log_message.connect(self.log_message.emit)
                success = gg.syncCode()
                error = '' if success else (gg.last_error or '저장소 동기화에 실패했습니다.')
            except Exception as exc:
                success, error = False, str(exc)
            results.append({'student_id': str(l.sid), 'name': l.name,
                            'success': bool(success), 'error': error})
            status = '성공' if success else f'실패: {escape(error)}'
            self.log_message.emit(f'{escape(l.name)} ({l.sid}) — {status}')

            progress_signal.emit(idx+1)
        succeeded = sum(row['success'] for row in results)
        return {'total': tcnt, 'success': succeeded, 'failed': tcnt - succeeded,
                'results': results, 'error': ''}
