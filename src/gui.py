from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import *
import sys

from evaluator import Evaluator
from src.lecture import Lecture


class LoadWorker(QObject):
    done_message = Signal()
    set_progress_value = Signal(int)
    in_progress_message = Signal(int)
    @Slot(str)
    def do_work(self, fname):#, evaluation, fname, label, lineedit):
        # 파일 호출하면 동작
        print('start thread', fname)
        eval = Evaluator()
        eval.loadfile(fname)
        self.set_progress_value.emit(eval.sendMaxValue())
        self.done_message.emit(eval.sendMaxValue())
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
        layout.addWidget(self.lineedit)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)

        self.label = QLabel('Choose file')
        layout.addWidget(self.label)

        central_widget.setLayout(layout)

        print('start thread')
        self.worker = LoadWorker()
        self.worker_thread = QThread()

        self.work_requested.connect(self.worker.do_work)
        self.worker.done_message.connect(self.loadFinished)
        self.worker.set_progress_value.connect(self.setProgress)
        self.worker.in_progress_message.connect(self.loadProgress)
        # self.lecture.progress_status.connect(self.loadProgress)
        # self.lecture.progress_max.connect(self.setProgress)

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.start()

        self.show()

    def load(self):
        fname = QFileDialog.getOpenFileName(self)
        self.lineedit.setText("File path : %s" % fname[0])
        self.btnLoad.setText("In progress")
        self.progress_bar.setValue(0)
        self.btnLoad.setDisabled(True)
        self.work_requested.emit(fname[0])
        #worker = LoadWorker(self.eval, fname=fname[0], label=self.label, lineedit=self.lineedit)


    def loadFinished(self, max):
        self.label.setText("Clear Git clone & pull")
        self.btnLoad.setText("Load CSV file")
        self.btnLoad.setEnabled(True)
        self.progress_bar.setValue(max)

    # def getPro_value(self,now,max):
    #     self.progress_status.emit(now)
    #     self.progress_count.emit(max)

    @Slot(int)
    def setProgress(self, max):
        self.progress_bar.setMaximum(max)

    @Slot(int)
    def loadProgress(self, now): #해결해야함
        self.progress_bar.setValue(now)