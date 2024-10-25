from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import *
import sys

from evaluator import Evaluator

class LoadWorker(QObject):
    done_message = Signal(int)
    set_progress_value = Signal(int)
    in_progress_message = Signal(int)
    @Slot(str)
    def do_work(self, fname):#, evaluation, fname, label, lineedit):
        # 파일 호출하면 동작
        print('start thread', fname)
        eval = Evaluator()
        eval.loadfile(fname)
        max = eval.sendMaxValue()
        self.set_progress_value.emit(max)
        self.done_message.emit(max)
        print('end thread')

class Gui(QMainWindow):
    work_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.eval = Evaluator()
        self.init_ui()

    def init_ui(self):
        self.setGeometry(500, 500, 500, 240)
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

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)

        self.label = QLabel('Select CSV file')
        layout.addWidget(self.label)

        self.output_label = QLabel('')
        layout.addWidget(self.output_label)

        central_widget.setLayout(layout)

        print('start thread')
        self.worker = LoadWorker()
        self.worker_thread = QThread()

        self.work_requested.connect(self.worker.do_work)
        self.worker.done_message.connect(self.loadFinished)
        self.worker.set_progress_value.connect(self.setProgress)
        self.worker.in_progress_message.connect(self.loadProgress)

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.start()

        self.show()

    def load(self):
        fname = QFileDialog.getOpenFileName(self)
        if not fname[0]:
            self.lineedit.setText("No file selected. Try select file again.")
            return
        self.lineedit.setText("File path : %s" % fname[0])
        self.btnLoad.setText("In progress")
        self.progress_bar.setValue(0)
        self.btnLoad.setDisabled(True)
        self.work_requested.emit(fname[0])
        #worker = LoadWorker(self.eval, fname=fname[0], label=self.label, lineedit=self.lineedit)

    @Slot(int)
    def loadFinished(self,max):
        self.label.setText("Clear Git clone & pull")
        self.btnLoad.setText("Load CSV file")
        self.btnLoad.setEnabled(True)
        self.progress_bar.setValue(max)

    @Slot(int)
    def setProgress(self, max):
        self.progress_bar.setMaximum(max)

    @Slot(int)
    def loadProgress(self, now): #해결해야함
        self.progress_bar.setValue(now)