from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import *
import sys

from src.evaluator import Evaluator

class LoadWorker(QObject):
    done_message = Signal()
    @Slot(str)
    def do_work(self, fname):#, evaluation, fname, label, lineedit):
        print('start thread', fname)
        eval = Evaluator()
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
        self.setGeometry(500, 500, 500, 240)
        self.setWindowTitle('PyQt6 Example')


        # Create a central widget
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()

        self.btnLoad = QPushButton("Load CSV file")
        #btnLoad.move(20, 20)
        self.btnLoad.clicked.connect(self.load)
        layout.addWidget(self.btnLoad)

        self.lineedit = QLineEdit(self)
        self.lineedit.setText('File name : ')
        layout.addWidget(self.lineedit)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.label = QLabel('Choose file')
        layout.addWidget(self.label)
        # self.label2 = QLabel('file name : ')
        # layout.addWidget(self.label2)

        central_widget.setLayout(layout)

        print('start thread')
        self.worker = LoadWorker()
        self.worker_thread = QThread()

        self.work_requested.connect(self.worker.do_work)
        self.worker.done_message.connect(self.loadFinished)

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.start()

        self.show()

    def load(self):
        fname = QFileDialog.getOpenFileName(self)
        self.lineedit.setText("File path : %s" % fname[0])
        self.btnLoad.setText("In progress")
        self.btnLoad.setDisabled(True)
        self.work_requested.emit(fname[0])
        #worker = LoadWorker(self.eval, fname=fname[0], label=self.label, lineedit=self.lineedit)

        #self.eval.loadfile(fname[0])
        # self.label.setText("Clear Git clone & pull")
        # self.lineedit.setText("file path : %s" %fname[0])

    def loadFinished(self):
        self.label.setText("Clear Git clone & pull")
        self.btnLoad.setText("Load CSV file")
        self.btnLoad.setEnabled(True)


