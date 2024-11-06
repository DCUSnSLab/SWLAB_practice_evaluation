from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import *
import sys

from evaluator import Evaluator

class LoadWorker(QObject):
    done_message = Signal()
    set_progress_value = Signal(int)
    in_progress_message = Signal(int)
    log_message = Signal(str)

    @Slot(str)
    def do_work(self, fname):
        # 파일 호출하면 동작
        print('start thread', fname)
        eval = Evaluator()
        eval.max_value.connect(self.set_progress_value.emit)
        eval.progress_status.connect(self.in_progress_message.emit)
        eval.log_message.connect(self.log_message.emit)
        eval.loadfile(fname)
        self.done_message.emit()
        print('end thread')

class Gui(QMainWindow):
    work_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.eval = Evaluator()
        self.init_ui()

    def init_ui(self):
        self.setGeometry(500, 500, 700, 500)
        self.setWindowTitle('SWLAB practice evaluation')

        # Create a central widget
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()

        self.btnLoad = QPushButton("Load CSV file")
        self.btnLoad.clicked.connect(self.load) #호출함수 선언
        layout.addWidget(self.btnLoad)

        self.lineedit = QLineEdit(self)
        self.lineedit.setText('File name : ')
        self.lineedit.setReadOnly(True)
        layout.addWidget(self.lineedit)

        self.label = QLabel('Select CSV file')
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar(self)
        self.label.setFixedHeight(self.progress_bar.height())
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_output = QTextEdit('')
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        central_widget.setLayout(layout)

        print('start thread')
        self.worker = LoadWorker()
        self.worker_thread = QThread()

        self.work_requested.connect(self.worker.do_work)
        self.worker.done_message.connect(self.loadFinished)
        self.worker.set_progress_value.connect(self.setProgress)
        self.worker.in_progress_message.connect(self.loadProgress)
        self.worker.log_message.connect(self.displayLog)

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.start()

        self.show()

    def load(self):
        self.progress_bar.setValue(0)
        self.label.setText('Select CSV file')
        fname = QFileDialog.getOpenFileName(self)
        if not fname[0]:
            self.lineedit.setText("No file selected. Try select file again.")
            return
        self.lineedit.setText("File path : %s" % fname[0])
        self.btnLoad.setText("In progress")
        self.label.setText('')
        self.log_output.setText('')
        self.btnLoad.setDisabled(True)
        self.work_requested.emit(fname[0])

    def loadFinished(self):
        self.log_output.append('<p style="color:green; font-weight:bold; font-size:16px; text-align:center;">'
                               '✔ Clear Git clone & pull</p><br>')
        self.btnLoad.setText("Load CSV file")
        self.btnLoad.setEnabled(True)
        self.log_output.append('\n')

    @Slot(int)
    def setProgress(self, max):
        self.progress_bar.setMaximum(max)

    @Slot(int)
    def loadProgress(self, now): #해결해야함
        self.progress_bar.setValue(now)

    @Slot(str)
    def displayLog(self, message):
        # self.log_output.append(message)
        message = message.replace("\n", "<br>")
        if "error" in message.lower() or "exception" in message.lower():
            formatted_message = f'<span style="color:red;">{message}</span>'
        else:
            formatted_message = message
        self.log_output.append(formatted_message)