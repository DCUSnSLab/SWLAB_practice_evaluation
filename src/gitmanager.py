from student import Student
from git.repo import Repo
from git import exc
import sys
import os
from setup_logging import logger
from PyQt6.QtCore import QObject, pyqtSignal as Signal

class gitManager(QObject):
    log_message = Signal(str)
    def __init__(self, student:Student, lec):
        super().__init__()
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
                message = f' ----- pull code [{target_dir}] [{gitaddr}]'
                logger.info(message)
                self.log_message.emit(message)
                repo = Repo(target_dir)
                repo.remotes.origin.pull()
                return True
            else: #폴더가 없을 경우 clone
                message = f' ----- clone code [{target_dir}] [{gitaddr}]'
                logger.info(message)
                self.log_message.emit(message)
                self.make_safe_dir(target_dir)
                Repo.clone_from(gitaddr, target_dir)
                return True
        except exc.GitError as err: #git error
            err_message = f'Git error [{err}]: {gitaddr}'
            logger.error(err_message)
            self.log_message.emit(err_message)
        except Exception as e: #예외처리
            err_message = f'Exception: {e}'
            logger.error(err_message)
            self.log_message.emit(err_message)
        return False