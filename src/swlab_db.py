#import logging
from src.dbbase import database, Student, Enrollment
from src.lecture import Lecture as m_Lecture
from src.student import Student as m_Student
from src.dbbase import Lecture
from src.setup_logging import logger

class DBConn:
    def __init__(self):
        database.init('testdata/testdb.db')
        self.db = database
        logger.name = __name__
        self.createDB()

    def createDB(self):
        self.db.create_tables([Student, Lecture, Enrollment])

    def insertLecture(self, lecture:m_Lecture):
        lec = Lecture.select().where(Lecture.name == lecture.name, Lecture.division == lecture.division)
        if len(lec) == 0:
            logger.info('[%s - not matched] insert data [%s, %d]'%((lecture.name+'_'+str(lecture.division)), lecture.name, lecture.division))
            l = Lecture(name=lecture.name, division=lecture.division)
            l.save()
        else:
            #pass
            logger.info('[%s - matched] not inserted' % (
            (lecture.name + '_' + str(lecture.division))))

    def insertStudent(self, lecture:m_Lecture, student:m_Student):
        db_std = Student.select().where(Student.sid == student.sid)
        db_lec = Lecture.select().where(Lecture.name == lecture.name, Lecture.division == lecture.division)
        sel_lec = None
        sel_std = None

        if len(db_std) == 0:
            sel_std = Student(name=student.name, sid=student.sid)
            sel_std.save()
        else:
            sel_std = db_std[0]

        if len(db_lec) == 0:
            sel_lec = l = Lecture(name=lecture.name, division=lecture.division)
            sel_lec.save()
        else:
            sel_lec = db_lec[0]

        db_enroll = Enrollment.select().where(Enrollment.student==sel_std, Enrollment.lecture==sel_lec)
        if len(db_enroll) == 0:
            sel_enroll = Enrollment(student=sel_std, lecture=sel_lec, gitaddr=student.githublink[lecture.id])
            sel_enroll.save()

        return True

    def test(self):
        print('test')
        lec = Lecture.select().where(Lecture.name == 'python', Lecture.division == 1)
        for l in lec.dicts():
            print(l)

        # enr = Enrollment.select()
        # for e in enr.dicts():
        #     print(e)