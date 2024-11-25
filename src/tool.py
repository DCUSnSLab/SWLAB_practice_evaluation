import sys
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtCore import Qt


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()
        self.initUI()
        self.SetupUi()
        self.Setup()

    def initUI(self):
        self.setWindowTitle('시스템 프로그래밍 채점 툴')
        self.show()

    def SetupUi(self):
        self.file_open_btn = QPushButton('파일 업로드', self)
        self.file_open_btn.clicked.connect(self.FileOpen)

        self.info_class = QLabel('시스템 프로그래밍 00분반')
        self.info_class.setStyleSheet("border: 1px solid black; padding: 10px;")

        self.file_widget = QTreeWidget()
        self.file_widget.setHeaderLabels(['폴더명'])
        self.file_widget.header().setSectionResizeMode(0)

        self.save = QPushButton('저장', self)
        self.save.clicked.connect(self.Save)

        self.back = QPushButton('이전', self)
        self.back.clicked.connect(self.Back)

        self.next = QPushButton('다음', self)
        self.next.clicked.connect(self.Next)

        self.info1 = QLabel('학생: 21115078')
        self.info2 = QLabel('문제: chap3-prob1')
        self.info3 = QLabel('점수: 10점')

        self.score_input = QLineEdit()
        self.score_input.setStyleSheet("background-color: white")

        self.score_btn = QPushButton('입력', self)
        self.score_btn.clicked.connect(self.Score)

        self.problem = QLabel('문제 설명')
        self.problem.setStyleSheet("border: 1px solid black; padding: 10px;")

        self.input_data = QLabel('입력')
        self.input_data.setStyleSheet("border: 1px solid black; padding: 10px;")

        self.output_data = QLabel('출력')
        self.output_data.setStyleSheet("border: 1px solid black; padding: 10px;")

    def FileOpen(self):
        file_path = QFileDialog.getExistingDirectory(self, "폴더 선택", "")
        if file_path:
            self.file_widget.clear()
            self.file_data(file_path, self.file_widget)

    def file_data(self, path, file_widget):
        pass

    def Save(self):
        pass

    def Back(self):
        pass

    def Next(self):
        pass

    def Score(self):
        pass

    def Setup(self):
        layout1 = QHBoxLayout()
        layout1.addWidget(self.file_open_btn)
        layout1.addWidget(self.save)

        layout2 = QHBoxLayout()
        layout2.addWidget(self.back)
        layout2.addWidget(self.next)

        info_box =  QGroupBox('정보')
        info_layout = QVBoxLayout()
        info_layout.addWidget(self.info1)
        info_layout.addWidget(self.info2)
        info_layout.addWidget(self.info3)
        info_box.setLayout(info_layout)

        score_box = QGroupBox('점수')
        score_layout = QHBoxLayout()
        score_layout.addWidget(self.score_input)
        score_layout.addWidget(self.score_btn)
        score_box.setLayout(score_layout)

        layout3 = QHBoxLayout()
        layout3.addWidget(info_box)
        layout3.addWidget(score_box)

        layout4 = QVBoxLayout()
        layout4.addLayout(layout1)
        layout4.addLayout(layout2)
        layout4.addLayout(layout3)
        layout4.addWidget(self.problem)
        layout4.addWidget(self.input_data)
        layout4.addWidget(self.output_data)

        layout5 = QVBoxLayout()
        layout5.addWidget(self.info_class)
        layout5.addWidget(self.file_widget)

        layout = QHBoxLayout()
        layout.addLayout(layout5)
        layout.addLayout(layout4)

        self.setLayout(layout)

if __name__ == '__main__':
   app = QApplication(sys.argv)
   ex = MainWindow()
   sys.exit(app.exec_())
