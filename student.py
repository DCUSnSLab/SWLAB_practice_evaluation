import os


class Student:
    def __init__(self, id:int, name:str, sid:int):
        self.id = id
        self.sid = sid
        self.name = name
        self.githublink = dict()

    def insertGithubLink(self, lec, link):
        self.githublink[lec.id] = link

    def getGitLinkbyLecture(self, lec) -> str:
        return self.githublink[lec.id]

    def getFilePathbyLecture(self, lec) -> str:
        return os.path.join(lec.getfilepath(), str(self.sid))
