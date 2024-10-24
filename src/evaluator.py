from lecture import Lecture
from student import Student
import csv
import re

class Evaluator:
    def __init__(self):
        self.id = 0
        self.max = 0

    def loadfile(self,file):
        #lecture = self.getDatafromCSV('../testdata/python01.csv', Lecture(0, 'python', 1))
        #lecture.syncCodefromLecture()

        # lecture2 = self.getDatafromCSV('../testdata/python02_test.csv', Lecture(1, 'python', 2))
        # #self.insertIntoDB(lecture2)
        # lecture2.syncCodefromLecture()
        division = int(re.findall(r'\d+', file)[-1])
        if file.find('python') != -1 :
            lecture = self.getDatafromCSV(file, Lecture(2024, 'python', division))
            lecture.syncCodefromLecture()
        elif file.find('system') != -1 :
            lecture = self.getDatafromCSV(file, Lecture(2024, 'system', division))
            lecture.syncCodefromLecture()
        else :
            lecture = self.getDatafromCSV(file, Lecture(1, '?', division))
            lecture.syncCodefromLecture()

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
            self.max += 1
        f.close()
        return lecture

    def sendMaxValue(self):
        return self.max

    def insertIntoDB(self, lecture:Lecture):
        print('insert db')
        self.db.insertLecture(lecture)
        for std in lecture.getStudentList():
            self.db.insertStudent(lecture, std)
        #database.insertLecture(lecture)


