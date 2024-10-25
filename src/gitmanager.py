from student import Student
from git.repo import Repo
from git import exc
import sys
import os
from setup_logging import logger

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
        try:
            if self.has_dir(target_dir): #폴더가 있을 경우 pull
                logger.info(' ----- pull code [%s] [%s]'%(target_dir, gitaddr))
                repo = Repo(target_dir)
                o = repo.remotes.origin
                o.pull()
                return True
            else: #폴더가 없을 경우 clone
                logger.info(' ----- clone code [%s] [%s]' % (target_dir, gitaddr))
                self.make_safe_dir(target_dir)
                Repo.clone_from(gitaddr, target_dir)
                return True
        except exc.GitError as err: #git error
            logger.error('Git error [%s]: %s'%(err, gitaddr))
        except Exception as e: #예외처리
            logger.error('Exception: %s'%(e))
        return False