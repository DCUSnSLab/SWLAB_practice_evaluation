from gitmanager import gitManager
from setup_logging import logger
from student import Student

class Lecture:
    def __init__(self, id:int, name:str, division:int):
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

    def syncCodefromLecture(self):
        tcnt = len(self.getStudentList())
        for idx, l in enumerate(self.getStudentList()):
            logger.info('[%d/%d] [%s-%d] Sync Code'%(idx+1, tcnt, self.name,self.division))
            gg = gitManager(student=l, lec=self)
            gg.syncCode()