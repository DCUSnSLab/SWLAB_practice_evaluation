from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import *
import sys
import os
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

class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Download Logs")
        self.setGeometry(600, 600, 600, 400)
        layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        
        self.btnClose = QPushButton("Close")
        self.btnClose.clicked.connect(self.close)
        layout.addWidget(self.btnClose)
        self.setLayout(layout)

    @Slot(str)
    def append_log(self, message):
         # Same formatting as displayLog
        message = message.replace("\n", "<br>")
        if "error" in message.lower() or "exception" in message.lower():
            formatted_message = f'<span style="color:red;">{message}</span>'
        else:
            formatted_message = message
        self.log_output.append(formatted_message)

class Gui(QMainWindow):
    work_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.eval = Evaluator() # Main thread evaluator for grading
        self.eval.log_message.connect(self.displayLog)
        
        # Keep track of log window
        self.log_window = None
        
        self.init_ui()

    def init_ui(self):
        self.setGeometry(500, 500, 1000, 700)
        self.setWindowTitle('SWLAB practice evaluation')

        main_layout = QVBoxLayout()

        # Top Section: Class & Hierarchy Selection
        top_layout = QHBoxLayout()
        
        top_layout.addWidget(QLabel("Year:"))
        self.comboYear = QComboBox()
        self.comboYear.currentIndexChanged.connect(self.onYearSelected)
        top_layout.addWidget(self.comboYear)
        
        top_layout.addWidget(QLabel("Class:"))
        self.comboClass = QComboBox()
        self.comboClass.currentIndexChanged.connect(self.onClassSelected)
        top_layout.addWidget(self.comboClass)
        
        top_layout.addWidget(QLabel("Chapter:"))
        self.comboChapter = QComboBox()
        self.comboChapter.currentIndexChanged.connect(self.onChapterSelected)
        top_layout.addWidget(self.comboChapter)
        
        self.lblProblem = QLabel("Problem:")
        top_layout.addWidget(self.lblProblem)
        self.comboProblem = QComboBox()
        self.comboProblem.currentIndexChanged.connect(self.onProblemChanged)
        top_layout.addWidget(self.comboProblem)

        # Execution Mode Selection
        mode_group = QGroupBox("Env")
        mode_layout = QHBoxLayout()
        self.radioWin = QRadioButton("Win")
        self.radioWSL = QRadioButton("WSL")
        self.radioDocker = QRadioButton("Docker")
        self.radioDocker.setChecked(True)
        mode_layout.addWidget(self.radioWin)
        mode_layout.addWidget(self.radioWSL)
        mode_layout.addWidget(self.radioDocker)
        mode_layout.setContentsMargins(0,0,0,0)
        mode_group.setLayout(mode_layout)
        top_layout.addWidget(mode_group)
        
        # self.btnBuildDocker = QPushButton("Build Img")
        # self.btnBuildDocker.setToolTip("Build Docker Image 'grader-image'")
        # self.btnBuildDocker.clicked.connect(self.buildDockerImage)
        # top_layout.addWidget(self.btnBuildDocker)
        
        top_layout.addStretch()
        main_layout.addLayout(top_layout)
        
        # Test Case Path Selection
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Test Case Dir:"))
        self.txtTestCasePath = QLineEdit()
        path_layout.addWidget(self.txtTestCasePath)
        self.btnBrowseTestPath = QPushButton("Browse...")
        self.btnBrowseTestPath.clicked.connect(self.browseTestPath)
        path_layout.addWidget(self.btnBrowseTestPath)
        main_layout.addLayout(path_layout)
        
        # Middle Section: Student List & Log
        mid_layout = QHBoxLayout()
        
        # Left: Student List
        student_group = QGroupBox("Students")
        student_layout = QVBoxLayout()
        self.listStudents = QListWidget()
        self.listStudents.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listStudents.itemSelectionChanged.connect(self.onStudentSelected)
        student_layout.addWidget(self.listStudents)
        student_group.setLayout(student_layout)
        mid_layout.addWidget(student_group, 1) # Ratio 1

        # Center: File List (New)
        file_group = QGroupBox("Submitted Files")
        file_layout = QVBoxLayout()
        self.listFiles = QListWidget()
        self.listFiles.itemDoubleClicked.connect(self.onFileDoubleClicked)
        file_layout.addWidget(self.listFiles)
        
        self.btnRefreshFiles = QPushButton("Refresh")
        self.btnRefreshFiles.clicked.connect(self.updateFileList)
        file_layout.addWidget(self.btnRefreshFiles)
        
        self.btnAddFile = QPushButton("+ Add File")
        self.btnAddFile.clicked.connect(self.addFile)
        file_layout.addWidget(self.btnAddFile)
        
        file_group.setLayout(file_layout)
        mid_layout.addWidget(file_group, 1) # Ratio 1

        # Right Side Layout (Preview + Tabs)
        right_side_layout = QVBoxLayout()
        
        # Code Preview (Top of Right Side)
        right_side_layout.addWidget(QLabel("Code Preview (Double-click file to view):"))
        self.txtCodePreview = QTextEdit()
        self.txtCodePreview.setReadOnly(True)
        # self.txtCodePreview.setMaximumHeight(200) # Optional
        right_side_layout.addWidget(self.txtCodePreview)

        # Tabs (Bottom of Right Side)
        self.right_tabs = QTabWidget()
        
        # Tab 1: Grading Result
        self.tab_grade = QWidget()
        grade_layout = QVBoxLayout()
        self.log_output = QTextEdit('')
        self.log_output.setReadOnly(True)
        grade_layout.addWidget(self.log_output)
        self.tab_grade.setLayout(grade_layout)
        self.right_tabs.addTab(self.tab_grade, "Grading Report")
        
        # Tab 2: Manual Execution
        self.tab_manual = QWidget()
        manual_layout = QVBoxLayout()
        
        manual_layout.addWidget(QLabel("Arguments:"))
        self.txtManualArgs = QLineEdit()
        self.txtManualArgs.setPlaceholderText("e.g. arg1 arg2 (Full paths will be copied automatically)")
        manual_layout.addWidget(self.txtManualArgs)

        manual_layout.addWidget(QLabel("Input(Stdin):"))
        self.txtManualInput = QTextEdit()
        self.txtManualInput.setMaximumHeight(100)
        manual_layout.addWidget(self.txtManualInput)
        
        # Aux File Section
        aux_group = QGroupBox("Create File (Optional)")
        aux_layout = QVBoxLayout()
        aux_name_layout = QHBoxLayout()
        aux_name_layout.addWidget(QLabel("Filename (e.g. data.txt):"))
        self.txtAuxFileName = QLineEdit()
        aux_name_layout.addWidget(self.txtAuxFileName)
        aux_layout.addLayout(aux_name_layout)
        
        aux_layout.addWidget(QLabel("Content:"))
        self.txtAuxFileContent = QTextEdit()
        self.txtAuxFileContent.setMaximumHeight(80) # Keep it compact
        aux_layout.addWidget(self.txtAuxFileContent)
        aux_group.setLayout(aux_layout)
        
        manual_layout.addWidget(aux_group)
        
        self.btnRunManual = QPushButton("Run Code (Single Student)")
        self.btnRunManual.clicked.connect(self.runManual)
        manual_layout.addWidget(self.btnRunManual)
        
        manual_layout.addWidget(QLabel("Output(Stdout):"))
        self.txtManualOutput = QTextEdit()
        self.txtManualOutput.setReadOnly(True)
        manual_layout.addWidget(self.txtManualOutput)
        
        self.tab_manual.setLayout(manual_layout)
        self.right_tabs.addTab(self.tab_manual, "Manual Execution")
        
        right_side_layout.addWidget(self.right_tabs)

        mid_layout.addLayout(right_side_layout, 2) # Ratio 2

        main_layout.addLayout(mid_layout)

        # Bottom Section: Controls
        bottom_layout = QHBoxLayout()
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        bottom_layout.addWidget(self.progress_bar)

        # Grade Button
        self.btnGrade = QPushButton("Grade Selected")
        self.btnGrade.clicked.connect(self.gradeSelected)
        bottom_layout.addWidget(self.btnGrade)

        # Load CSV Button (Existing)
        self.btnLoad = QPushButton("Load CSV file")
        self.btnLoad.clicked.connect(self.load)
        bottom_layout.addWidget(self.btnLoad)

        main_layout.addLayout(bottom_layout)
        
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        central_widget.setLayout(main_layout)

        # Initialize Data
        self.refreshYearList()

        # Worker setup for loading CSV
        self.worker = LoadWorker()
        self.worker_thread = QThread()

        self.work_requested.connect(self.worker.do_work)
        self.worker.done_message.connect(self.loadFinished)
        self.worker.set_progress_value.connect(self.setProgress)
        self.worker.in_progress_message.connect(self.loadProgress)
        # self.worker.log_message.connect(self.displayLog) # Removed global connection

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.start()

        self.show()

    def refreshYearList(self):
        self.comboYear.clear()
        years = self.eval.get_year_list()
        self.comboYear.addItems(years)
        # Trigger explicit update if items loaded, or if empty
        if years:
            self.onYearSelected()

    def onYearSelected(self):
        self.comboClass.clear()
        year = self.comboYear.currentText()
        if not year:
            return
        
        classes = self.eval.get_classes_by_year(year)
        for c in classes:
            # Assuming format Name_Div_Year
            display_name = c.rsplit('_', 1)[0]
            self.comboClass.addItem(display_name, c)

    def onClassSelected(self):
        self.listStudents.clear()
        self.comboChapter.clear()
        self.comboProblem.clear()
        
        class_folder = self.comboClass.currentData()
        if not class_folder:
            return
        
        # Update Student List
        students = self.eval.get_student_list(class_folder)
        self.listStudents.addItems(students)
        
    def onStudentSelected(self):
        # Only update chapters if not already populated or if we want to enforce consistency
        selected_items = self.listStudents.selectedItems()
        if not selected_items:
            return
            
        student_id = selected_items[0].text()
        class_folder = self.comboClass.currentData()
        
        current_chapter = self.comboChapter.currentText()
        self.comboChapter.blockSignals(True)
        self.comboChapter.clear()
        
        chapters = self.eval.get_student_chapters(class_folder, student_id)
        self.comboChapter.addItems(chapters)
        
        # Restore selection if exists
        index = self.comboChapter.findText(current_chapter)
        if index >= 0:
            self.comboChapter.setCurrentIndex(index)
        
        self.comboChapter.blockSignals(False)
        
        # Manually trigger problem update if chapter matches (or first item selected)
        if self.comboChapter.count() > 0:
             self.onChapterSelected()

    def onChapterSelected(self):
        current_problem = self.comboProblem.currentText()
        self.comboProblem.clear()
        
        class_folder = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        
        selected_items = self.listStudents.selectedItems()
        if not selected_items:
            return
        student_id = selected_items[0].text()
        
        if not class_folder or not chapter:
            return

        problems = self.eval.get_student_problems(class_folder, student_id, chapter)
        
        if not problems:
            # Case: No sub-problems (files in chapter dir)
            self.comboProblem.hide()
            self.lblProblem.hide()
            self.updateFileList()
        else:
            self.comboProblem.show()
            self.lblProblem.show()
            self.comboProblem.addItems(problems)
            
            # Restore selection if exists
            index = self.comboProblem.findText(current_problem)
            if index >= 0:
                 self.comboProblem.setCurrentIndex(index)

    def onProblemChanged(self):
        self.updateTestCasePath()
        self.updateFileList()

    def updateFileList(self):
        self.listFiles.clear()
        self.txtCodePreview.clear() # Clear preview on list update
        
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.comboProblem.currentText()
        
        if self.comboProblem.isHidden():
            problem = None # Ignore problem if hidden
            
        selected_items = self.listStudents.selectedItems()
        if not selected_items or not class_name or not chapter:
            return
            
        student_id = selected_items[0].text()
        
        files = self.eval.get_student_files(class_name, student_id, chapter, problem)
        self.listFiles.addItems(files)

    def onFileDoubleClicked(self, item):
        filename = item.text()
        
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.comboProblem.currentText()
        
        if self.comboProblem.isHidden():
            problem = None
            
        selected_items = self.listStudents.selectedItems()
        if not selected_items:
            return
        student_id = selected_items[0].text()
        
        content = self.eval.get_file_content(class_name, student_id, chapter, problem, filename)
        
        # Preview is now shared, no need to switch tab
        # self.right_tabs.setCurrentWidget(self.tab_manual)
        
        self.txtCodePreview.setText(content)

    def updateTestCasePath(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.comboProblem.currentText()
        
        if not class_name or not chapter or not problem:
            return
            
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Parse lecture name (Name_Div_Year)
        # Expected: System_1_2025 -> Lecture: System
        parts = class_name.split('_')
        if len(parts) >= 3:
            lecture_name = "_".join(parts[:-2])
        else:
            lecture_name = class_name
            
        # Structure: testcase/<LectureName>/<Chapter>/<Problem>
        # Note: Removing 'testcases' subfolder logic as per request imply testcase/ is the root
        # and Project/testcase/system/chap/prob contains the cases.
        default_path = os.path.join(base_dir, 'testcase', lecture_name, chapter, problem)
        self.txtTestCasePath.setText(default_path)

    def browseTestPath(self):
        path = QFileDialog.getExistingDirectory(self, "Select Test Case Directory")
        if path:
            self.txtTestCasePath.setText(path)

    def addFile(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.comboProblem.currentText()
        
        selected_items = self.listStudents.selectedItems()
        if not selected_items or not class_name:
             QMessageBox.warning(self, "Warning", "Please select a class and student first.")
             return
             
        student_id = selected_items[0].text()
        
        fname = QFileDialog.getOpenFileName(self, "Select File to Add")
        if not fname[0]:
            return
            
        success, msg = self.eval.add_student_file(class_name, student_id, chapter, problem, fname[0])
        
        if success:
            self.updateFileList()
            QMessageBox.information(self, "Success", f"File added: {os.path.basename(fname[0])}")
        else:
            QMessageBox.critical(self, "Error", f"Failed to add file: {msg}")





    def buildDockerImage(self):
        self.log_output.append("<b>Building Docker Image...</b>")
        self.log_output.repaint()
        try:
            # Assume Dockerfile is in project root (../Dockerfile from src/gui.py? No, main.py is in src. Dockerfile in root.)
            # root is one level up from src
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cmd = ["docker", "build", "-t", "grader-image", "."]
            
            # Run docker build
            # Note: capturing output to show user
            process = subprocess.Popen(cmd, cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            
            if process.returncode == 0:
                self.log_output.append("<span style='color:blue;'>Docker Image Built Successfully.</span><br>")
            else:
                self.log_output.append(f"<span style='color:red;'>Docker Build Failed:</span><br>{stderr}<br>")
                
        except Exception as e:
            self.log_output.append(f"<span style='color:red;'>Error launching docker: {e}</span><br>")

    def gradeSelected(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.comboProblem.currentText()
        
        selected_items = self.listStudents.selectedItems()
        
        if not class_name or not selected_items:
            QMessageBox.warning(self, "Warning", "Please select a class and at least one student.")
            return

        # Use path from input
        test_case_dir = self.txtTestCasePath.text()

        if not test_case_dir or not os.path.exists(test_case_dir):
            QMessageBox.warning(self, "Warning", f"Test case directory not found: {test_case_dir}")
            return
            
        # Determine Mode
        mode = 'windows'
        if self.radioWSL.isChecked(): mode = 'wsl'
        elif self.radioDocker.isChecked(): mode = 'docker'

        runner_config = {
            'mode': mode,
            'chapter': chapter,
            'problem': problem
        }

        self.log_output.append("<b>Starting Grading...</b>")
        self.log_output.append(f"<i>Environment: {mode.upper()}</i>")

        for item in selected_items:
            student_id = item.text()
            self.eval.start_grading(class_name, student_id, test_case_dir, runner_config)
        
        self.log_output.append("<b>Grading Finished.</b>")

    def runManual(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.comboProblem.currentText()
        
        selected_items = self.listStudents.selectedItems()
        if not class_name or not selected_items:
            QMessageBox.warning(self, "Warning", "Please select a student.")
            return

        student_id = selected_items[0].text()
        
        # Determine Mode
        mode = 'windows'
        if self.radioWSL.isChecked(): mode = 'wsl'
        elif self.radioDocker.isChecked(): mode = 'docker'
        
        # Config
        runner_config = {
            'mode': mode,
            'chapter': chapter,
            'problem': problem
        }
        
        target_file = None
        file_selection = self.listFiles.selectedItems()
        if file_selection:
            target_file = file_selection[0].text()
        
        input_data = self.txtManualInput.toPlainText()
        args_str = self.txtManualArgs.text()
        final_args = args_str.split()
        
        # Auxiliary File Creation
        aux_filename = self.txtAuxFileName.text().strip()
        aux_content = self.txtAuxFileContent.toPlainText()
        
        if aux_filename:
             success, msg = self.eval.create_file_from_string(class_name, student_id, chapter, problem, aux_filename, aux_content)
             if success:
                 self.log_output.append(f"Created aux file: {aux_filename}")
                 # self.updateFileList() # Optional: Refresh list to show it? Yes, good UX.
             else:
                 self.log_output.append(f"<span style='color:red;'>Failed to create aux file: {msg}</span>")

        msg = f"Running {target_file if target_file else 'Default'}..."
        if final_args:
             msg += f" with args: {final_args}"
        self.txtManualOutput.setText(msg)
        self.txtManualOutput.repaint() # Force update
        
        success, stdout, stderr = self.eval.run_manual_code(class_name, student_id, runner_config, input_data, final_args, target_file)
        
        if aux_filename:
            self.updateFileList() # Update list after run to see created file
        
        output_msg = ""
        if success:
            output_msg += f"[Process Finished]\n\n--- STDOUT ---\n{stdout}"
            if stderr:
                output_msg += f"\n\n--- STDERR ---\n{stderr}"
        else:
            output_msg += f"[Execution Failed]\nReason/Stderr: {stderr}\nStdout: {stdout}"
            
        self.txtManualOutput.setText(output_msg)

    def load(self):
        self.progress_bar.setValue(0)
        fname = QFileDialog.getOpenFileName(self)
        if not fname[0]:
            return
        
        # Setup Log Window
        self.log_window = LogWindow()
        self.log_window.show()
        
        # Connect worker log to log window
        try:
            self.worker.log_message.disconnect()
        except:
            pass # Ignore if not connected
        self.worker.log_message.connect(self.log_window.append_log)
        
        self.btnLoad.setText("In progress")
        self.btnLoad.setDisabled(True)
        self.work_requested.emit(fname[0])

    def loadFinished(self):
        if self.log_window:
             self.log_window.append_log('<p style="color:green; font-weight:bold; font-size:16px; text-align:center;">'
                               '✔ Clear Git clone & pull</p><br>')
        
        self.btnLoad.setText("Load CSV file")
        self.btnLoad.setEnabled(True)
        self.log_output.append('\n')
        self.refreshYearList() # Refresh after load

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
        if "error" in message.lower() or "exception" in message.lower() or "fail" in message.lower():
            formatted_message = f'<span style="color:red;">{message}</span>'
        elif "pass" in message.lower():
             formatted_message = f'<span style="color:blue;">{message}</span>'
        else:
            formatted_message = message
        self.log_output.append(formatted_message)