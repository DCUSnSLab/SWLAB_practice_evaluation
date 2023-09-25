from student import Student
from git.repo import Repo
import sys
import os
from src.setup_logging import logger

class gitManager:
    def __init__(self, student:Student, lec):
        self.student = student
        self.lec = lec
        self.origindir = 'origin'
        logger.name = __name__

    def make_safe_dir(self, dir):
        if not os.path.exists(dir):
            os.makedirs(dir)

    def has_dir(self, dir):
        return os.path.exists(dir)

    def syncCode(self):
        target_dir = os.path.join(self.origindir, self.student.getFilePathbyLecture(self.lec))
        gitaddr = self.student.getGitLinkbyLecture(self.lec)

        if self.has_dir(target_dir):
            logger.info(' ----- pull code [%s] [%s]'%(target_dir, gitaddr))
            repo = Repo(target_dir)
            o = repo.remotes.origin
            o.pull()
        else:
            logger.info(' ----- clone code [%s] [%s]' % (target_dir, gitaddr))
            self.make_safe_dir(target_dir)
            repog = Repo.clone_from(gitaddr, target_dir)

