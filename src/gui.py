from PyQt6.QtWidgets import *
import sys



class Gui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setGeometry(300, 300, 320, 240)
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
        self.lineedit.setText('testtest')
        layout.addWidget(self.lineedit)

        self.label = QLabel('hello')
        layout.addWidget(self.label)

        central_widget.setLayout(layout)
        self.show()

    def load(self):
        fname = QFileDialog.getOpenFileName(self)
        if not fname:
            return
        self.label.setText(fname[0])
