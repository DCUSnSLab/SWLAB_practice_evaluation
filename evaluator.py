from gitgrabber import gitGrabber
from lecture import Lecture
from student import Student
import csv
import re

class Evaluator:
    def __init__(self):
        self.id = 0

    def start(self):
        lecture = self.getDatafromCSV('python01.csv', Lecture(0, 'python', 1))
        self.syncCodefromLecture(lecture)

    def syncCodefromLecture(self, lecture:Lecture):
        tcnt = len(lecture.getStudentList())
        for idx, l in enumerate(lecture.getStudentList()):
            print('[%d/%d] Sync Code of Lecture named %s-%d'%(idx+1, tcnt, lecture.name,lecture.division))
            gg = gitGrabber(student=l, lec=lecture)
            gg.syncCode()

    def filterString(self, data):
        return re.sub(r'[^0-9]', '', data)

    def getDatafromCSV(self, path, lecture:Lecture):
        f = open(path, 'r', encoding='utf-8')
        rdr = csv.reader(f)
        for line in rdr:
            sid = self.filterString(line[0])
            s = Student(int(sid), name=line[1], sid=int(sid))
            s.insertGithubLink(lecture, line[2])
            lecture.addStudent(s)
        f.close()
        return lecture

if __name__ == "__main__":
    eval = Evaluator()
    eval.start()