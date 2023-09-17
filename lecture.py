from student import Student


class Lecture:
    def __init__(self, id:int, name:str, division:int):
        self.id = id
        self.name = name
        self.division = division
        self.students = dict()

    def getfilepath(self):
        return self.name + '_' + str(self.division) + '_' + str(self.id)
    def addStudent(self, stu:Student):
        self.students[stu.sid] = stu

    def getStudentList(self):
        return self.students.values()

    def getStudentbySID(self, sid:int) -> Student:
        return self.students[sid]