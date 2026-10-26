import sys
import os
import shutil
import tempfile
import json
from pathlib import Path
from paths import case_path, safe_path, parse_args
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, 
                             QComboBox, QFileDialog, QMessageBox, QGroupBox, QRadioButton)
from grader import Grader

class TestMaker(QWidget):
    def __init__(self):
        super().__init__()
        self.grader = Grader()
        self.job = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Test Case Generator")
        self.setGeometry(100, 100, 600, 700)
        
        layout = QVBoxLayout()
        
        # 1. Solution File Selection
        layout.addWidget(QLabel("1. Solution Source Code:"))
        sol_layout = QHBoxLayout()
        self.txtSolFile = QLineEdit()
        self.btnBrowse = QPushButton("Browse...")
        self.btnBrowse.clicked.connect(self.browse_file)
        sol_layout.addWidget(self.txtSolFile)
        sol_layout.addWidget(self.btnBrowse)
        layout.addLayout(sol_layout)
        
        # 2. Target Path Configuration
        layout.addWidget(QLabel("2. Target Location (testcase/lecture/chapter/problem/case)"))
        
        # Class Selection (Scan origin directory)
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("Class:"))
        self.comboClass = QComboBox()
        self.comboClass.setEditable(True)
        self.scan_classes()
        target_layout.addWidget(self.comboClass)
        layout.addLayout(target_layout)
        
        # Chap/Prob
        cp_layout = QHBoxLayout()
        cp_layout.addWidget(QLabel("Chapter:"))
        self.txtChapter = QLineEdit()
        self.txtChapter.setPlaceholderText("chap1")
        cp_layout.addWidget(self.txtChapter)
        
        cp_layout.addWidget(QLabel("Problem:"))
        self.txtProblem = QLineEdit()
        self.txtProblem.setPlaceholderText("prob1")
        cp_layout.addWidget(self.txtProblem)
        layout.addLayout(cp_layout)
        
        # Case Name
        cn_layout = QHBoxLayout()
        cn_layout.addWidget(QLabel("Case Name:"))
        self.txtCaseName = QLineEdit()
        self.txtCaseName.setPlaceholderText("case_01")
        cn_layout.addWidget(self.txtCaseName)
        layout.addLayout(cn_layout)
        
        # 3. Test Data Input
        layout.addWidget(QLabel("3. Input Data (Stdin):"))
        self.txtInput = QTextEdit()
        self.txtInput.setMaximumHeight(100)
        layout.addWidget(self.txtInput)
        
        layout.addWidget(QLabel("Arguments (Command Line):"))
        self.txtArgs = QLineEdit()
        layout.addWidget(self.txtArgs)
        
        # 4. Environment
        env_group = QGroupBox("4. Execution Environment")
        env_layout = QHBoxLayout()
        self.radioWin = QRadioButton("Windows")
        self.radioWSL = QRadioButton("WSL")
        self.radioLinux = QRadioButton("Linux")
        self.radioDocker = QRadioButton("Docker")
        self.radioDocker.setChecked(True) # Default
        
        env_layout.addWidget(self.radioWin)
        env_layout.addWidget(self.radioWSL)
        env_layout.addWidget(self.radioLinux)
        env_layout.addWidget(self.radioDocker)
        env_group.setLayout(env_layout)
        layout.addWidget(env_group)
        
        # 5. Controls
        btn_layout = QHBoxLayout()
        self.btnGenerate = QPushButton("Generate & Save Case")
        self.btnGenerate.setStyleSheet("background-color: #216e39; color: white; font-weight: bold; padding: 10px;")
        self.btnGenerate.clicked.connect(self.generate_case)
        btn_layout.addWidget(self.btnGenerate)
        layout.addLayout(btn_layout)
        
        # 6. Log Console
        layout.addWidget(QLabel("Execution Log / Output Preview:"))
        self.txtLog = QTextEdit()
        self.txtLog.setReadOnly(True)
        layout.addWidget(self.txtLog)
        
        self.setLayout(layout)

    def scan_classes(self):
        # Scan 'origin' directory for classes
        # Assume directory structure: ../origin
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            origin_dir = os.path.join(current_dir, 'origin')
            
            if os.path.exists(origin_dir):
                dirs = [d for d in os.listdir(origin_dir) if os.path.isdir(os.path.join(origin_dir, d))]
                self.comboClass.addItems(sorted(dirs))
            else:
                self.comboClass.addItems(["system", "python"])
        except:
             self.comboClass.addItem("Error scanning")

    def browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Select Solution File", "", "Source Code (*.py *.c)")
        if fname:
            self.txtSolFile.setText(fname)

    def get_mode(self):
        if self.radioWin.isChecked(): return 'windows'
        if self.radioWSL.isChecked(): return 'wsl'
        if self.radioLinux.isChecked(): return 'linux'
        return 'docker'

    def generate_case(self):
        sol_file = self.txtSolFile.text().strip()
        class_name = self.comboClass.currentText()
        chapter = self.txtChapter.text().strip()
        problem = self.txtProblem.text().strip()
        case_name = self.txtCaseName.text().strip()
        
        inputs = self.txtInput.toPlainText()
        args_str = self.txtArgs.text().strip()
        try:
            args = parse_args(args_str)
        except ValueError as exc:
            QMessageBox.warning(self, 'Arguments', str(exc))
            return
        
        if not sol_file or not os.path.exists(sol_file):
            QMessageBox.warning(self, "Error", "Solution file not found.")
            return
        if not chapter or not problem or not case_name:
            QMessageBox.warning(self, "Error", "Please fill all target path fields.")
            return
            
        try:
            for component in (class_name, chapter, problem, case_name):
                if not component or Path(component).name != component or component in ('.', '..') or '\\' in component:
                    raise ValueError('Use single folder names for the target location.')
            destination = safe_path(case_path(class_name, chapter, problem), case_name)
            if destination.exists():
                raise ValueError('Case already exists. Choose a new case name.')
        except ValueError as exc:
            QMessageBox.warning(self, 'Target', str(exc))
            return
        self.txtLog.clear()
        self.btnGenerate.setEnabled(False)
        mode = self.get_mode()
        def generate(progress):
            grader = Grader()
            with tempfile.TemporaryDirectory(prefix='swlab-solution-') as temp:
                work = Path(temp) / 'work'
                shutil.copytree(Path(sol_file).parent, work, ignore=shutil.ignore_patterns('.git', '__pycache__'))
                success, stdout, stderr = grader.run_code(work, inputs, args, {'mode': mode}, target_file=Path(sol_file).name)
            if not success:
                raise ValueError(stderr or 'Solution execution failed.')
            destination.mkdir(parents=True, exist_ok=False)
            (destination / 'output.txt').write_text(stdout, encoding='utf-8')
            (destination / 'input.txt').write_text(inputs, encoding='utf-8')
            (destination / 'case.json').write_text(json.dumps({'args': args, 'target_file': Path(sol_file).name}, indent=2), encoding='utf-8')
            return str(destination), stdout
        from gui import Job
        self.job = Job(generate, self)
        self.job.result.connect(lambda result: self.txtLog.setPlainText(f'Saved: {result[0]}\n\n{result[1]}'))
        self.job.failed.connect(lambda error: self.txtLog.setPlainText('Error: ' + error))
        self.job.finished.connect(lambda: self.btnGenerate.setEnabled(True))
        self.job.start()

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            event.ignore()
        else:
            event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TestMaker()
    window.show()
    sys.exit(app.exec())
