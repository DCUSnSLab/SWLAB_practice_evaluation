from PyQt6.QtCore import QObject, pyqtSignal as Signal
from gitmanager import gitManager
from setup_logging import logger
from student import Student

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
        for idx, l in enumerate(self.getStudentList()):
            message = f'[{idx+1}/{tcnt}] [{self.name}-{self.division}] Sync Code'
            logger.info(message)
            self.log_message.emit(message)

            gg = gitManager(student=l, lec=self)
            gg.log_message.connect(self.log_message.emit)
            gg.syncCode()

            progress_signal.emit(idx+1)