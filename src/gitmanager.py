"""Clone/pull submissions without changing locally edited student work."""
import os
import signal
import subprocess
from git import Repo, exc
from PyQt6.QtCore import QObject, pyqtSignal as Signal
from paths import ORIGIN
from setup_logging import logger


class gitManager(QObject):
    log_message = Signal(str)

    def __init__(self, student, lec):
        super().__init__()
        self.student = student
        self.lec = lec
        self.origindir = str(ORIGIN)
        self.last_error = ''

    def _run_git(self, arguments):
        environment = dict(os.environ, GIT_TERMINAL_PROMPT='0')
        process = subprocess.Popen(['git', *arguments], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=environment, start_new_session=os.name != 'nt')
        try:
            stdout, stderr = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, timeout=10)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.communicate()
            raise RuntimeError('Git operation timed out after 120 seconds.')
        if process.returncode:
            raise RuntimeError(stderr.decode('utf-8', errors='replace').strip())

    def syncCode(self):
        self.last_error = ''
        target = os.path.join(self.origindir, self.student.getFilePathbyLecture(self.lec))
        address = self.student.getGitLinkbyLecture(self.lec)
        try:
            if os.path.isdir(os.path.join(target, '.git')):
                with Repo(target) as repo:
                    if repo.is_dirty(untracked_files=True):
                        self.last_error = '로컬에서 수정하거나 추가한 파일이 있어 동기화를 건너뛰었습니다.'
                        self.log_message.emit(f'Error: {self.last_error}')
                        return False
                self.log_message.emit(f'Pull: {target}')
                self._run_git(['-C', target, 'pull', '--ff-only'])
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                self.log_message.emit(f'Clone: {target}')
                self._run_git(['clone', '--', address, target])
            return True
        except (OSError, RuntimeError, exc.GitError, subprocess.SubprocessError) as error:
            self.last_error = str(error)
            message = f'Git error: {error}'
            logger.error(message)
            self.log_message.emit(message)
            return False
