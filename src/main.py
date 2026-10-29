import sys
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox
from gui import Gui


def report_error(kind, value, tb):
    """Show an uncaught slot error instead of letting PyQt abort the whole program."""
    traceback.print_exception(kind, value, tb)
    message = ''.join(traceback.format_exception_only(kind, value)).strip()
    if issubclass(kind, ImportError):  # source files changed under a running app
        message += '\n\n프로그램 파일이 실행 중에 바뀌었을 수 있습니다. 프로그램을 다시 실행하세요.'
    QMessageBox.critical(QApplication.activeWindow(), '오류', message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.excepthook = report_error
    gui = Gui()
    sys.exit(app.exec())
