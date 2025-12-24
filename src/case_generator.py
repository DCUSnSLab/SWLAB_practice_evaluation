import sys
import os
import shutil
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, 
                             QComboBox, QFileDialog, QMessageBox, QGroupBox, QRadioButton)
from grader import Grader

class TestMaker(QWidget):
    def __init__(self):
        super().__init__()
        self.grader = Grader()
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
        layout.addWidget(QLabel("2. Target Location (testdata/...)"))
        
        # Class Selection (Scan origin directory)
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("Class:"))
        self.comboClass = QComboBox()
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
        self.btnGenerate.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
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
                self.comboClass.addItem("(origin folder not found)")
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
        args = args_str.split() if args_str else []
        
        if not sol_file or not os.path.exists(sol_file):
            QMessageBox.warning(self, "Error", "Solution file not found.")
            return
        if not chapter or not problem or not case_name:
            QMessageBox.warning(self, "Error", "Please fill all target path fields.")
            return
            
        self.txtLog.clear()
        self.txtLog.append(f"Running {os.path.basename(sol_file)}...")
        
        # 1. Run Code
        sol_dir = os.path.dirname(sol_file)
        sol_name = os.path.basename(sol_file)
        config = {'mode': self.get_mode()}
        
        success, stdout, stderr = self.grader.run_code(sol_dir, inputs, args, config, target_file=sol_name)
        
        if not success:
            self.txtLog.append("Execution Failed!")
            self.txtLog.append(f"Stderr: {stderr}")
            QMessageBox.critical(self, "Failed", "Solution execution failed. Check log.")
            return
            
        self.txtLog.append("Execution Successful.")
        self.txtLog.append(f"Output Preview:\n{stdout}")
        
        # 2. Save Artifacts
        # Path: root/testdata/<class>/testcases/<chap>/<prob>/<case>/
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        target_dir = os.path.join(project_root, 'testdata', class_name, 'testcases', chapter, problem, case_name)
        
        try:
            os.makedirs(target_dir, exist_ok=True)
            
            # Save output.txt (Required)
            with open(os.path.join(target_dir, 'output.txt'), 'w', encoding='utf-8') as f:
                f.write(stdout)
                
            # Save input.txt (if present)
            if inputs:
                with open(os.path.join(target_dir, 'input.txt'), 'w', encoding='utf-8') as f:
                    f.write(inputs)
            
            # Save args.txt (if present)
            if args_str:
                with open(os.path.join(target_dir, 'args.txt'), 'w', encoding='utf-8') as f:
                    f.write(args_str)
                    
            self.txtLog.append(f"\nSaved Test Case to:\n{target_dir}")
            QMessageBox.information(self, "Success", f"Test Case '{case_name}' Created!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save files: {e}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TestMaker()
    window.show()
    sys.exit(app.exec())
