from PyQt6.QtWidgets import *
import sys

from src.evaluator import Evaluator


class Gui(QMainWindow):
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

        self.btnLoad = QPushButton("load")
        #btnLoad.move(20, 20)
        self.btnLoad.clicked.connect(self.load)
        layout.addWidget(self.btnLoad)

        self.lineedit = QLineEdit(self)
        self.lineedit.setText('file name : ')
        layout.addWidget(self.lineedit)

        self.label = QLabel('choose file')
        layout.addWidget(self.label)
        # self.label2 = QLabel('file name : ')
        # layout.addWidget(self.label2)

        central_widget.setLayout(layout)
        self.show()

    def load(self):
        fname = QFileDialog.getOpenFileName(self)
        self.eval.loadfile(fname[0])
        self.label.setText("Clear Git clone & pull")
        self.lineedit.setText("file path : %s" %fname[0])

