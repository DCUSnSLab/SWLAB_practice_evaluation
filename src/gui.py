import subprocess
import html
import json
from paths import case_path, parse_args
from reports import save_report, CaseReport, summarize_cases
from pathlib import Path
from table_items import SortableItem, student_sort_value

from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import *
import sys
import os
import shutil # Added for file operations
from evaluator import Evaluator

class LoadWorker(QObject):
    done_message = Signal(object)
    set_progress_value = Signal(int)
    in_progress_message = Signal(int)
    log_message = Signal(str)

    @Slot(str)
    def do_work(self, fname):
        summary = {'total': 0, 'success': 0, 'failed': 0, 'results': [], 'error': ''}
        try:
            evaluator = Evaluator()
            evaluator.max_value.connect(self.set_progress_value.emit)
            evaluator.progress_status.connect(self.in_progress_message.emit)
            evaluator.log_message.connect(self.log_message.emit)
            summary = evaluator.loadfile(fname)
        except Exception as exc:
            summary['error'] = str(exc)
            self.log_message.emit(f'Error: {exc}')
        finally:
            self.done_message.emit(summary)


class Job(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('저장소 동기화')
        self.resize(900, 650)
        layout = QVBoxLayout()
        self.summary_label = QLabel('저장소 동기화 중…')
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary_label)
        self.failure_table = QTableWidget(0, 3)
        self.failure_table.setHorizontalHeaderLabels(['이름', '학번', '실패 사유'])
        self.failure_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.failure_table.verticalHeader().hide()
        self.failure_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.failure_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.failure_table.hide()
        layout.addWidget(self.failure_table)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        
        self.btnClose = QPushButton('닫기')
        self.btnClose.clicked.connect(self.close)
        layout.addWidget(self.btnClose)
        self.setLayout(layout)

    def show_summary(self, summary):
        if summary['error']:
            text = f"동기화를 시작하지 못했습니다: {summary['error']}\n처리한 학생 0명"
        else:
            text = f"동기화 완료 · 전체 {summary['total']}명 / 성공 {summary['success']}명 / 실패 {summary['failed']}명"
        self.summary_label.setText(text)
        failures = [row for row in summary['results'] if not row['success']]
        self.failure_table.setRowCount(len(failures))
        for index, row in enumerate(failures):
            for column, value in enumerate((row['name'], row['student_id'], row['error'])):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.failure_table.setItem(index, column, item)
        self.failure_table.resizeRowsToContents()
        self.failure_table.setVisible(bool(failures))
        self.append_log(f'<b>{html.escape(text)}</b>')
        for row in failures:
            self.append_log(html.escape(f"실패: {row['name']} ({row['student_id']}) — {row['error']}"))
        self.show()
        self.raise_()
        return text

    @Slot(str)
    def append_log(self, message):
         # Same formatting as displayLog
        message = message.replace("\n", "<br>")
        if "error" in message.lower() or "exception" in message.lower():
            formatted_message = f'<span style="font-weight:600;">{message}</span>'
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
        self.job = None
        self.results = []
        self.case_report = None
        self.latest_view = True
        self.gradebook = None
        
        self.init_ui()

    def init_ui(self):
        from main_view import build_main_view
        self.busy = False
        self.active_case_count = 0
        self.grading_active = False
        build_main_view(self)

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
        from paths import natural_key
        self.listFiles.clear()
        self.txtCodePreview.clear()
        self.listStudents.blockSignals(True)
        self.listStudents.clear()
        class_folder = self.comboClass.currentData()
        students = self.eval.get_student_list(class_folder) if class_folder else []
        self.listStudents.addItems(students)
        from student_names import read_student_names
        names = read_student_names(class_folder) if class_folder else {}
        for index in range(self.listStudents.count()):
            item = self.listStudents.item(index)
            name = names.get(item.text(), '')
            item.setData(Qt.ItemDataRole.UserRole, name)
            label = f'{item.text()} · {name}' if name else item.text()
            item.setToolTip(label);item.setData(Qt.ItemDataRole.AccessibleTextRole, label)
        self.listStudents.selectAll()
        self.listStudents.blockSignals(False)
        chapters = set()
        for student in students:
            chapters.update(self.eval.get_student_chapters(class_folder, student))
        if class_folder:
            from paths import TESTCASES, lecture_name
            case_root = TESTCASES / lecture_name(class_folder)
            if case_root.is_dir():
                chapters.update(p.name for p in case_root.iterdir() if p.is_dir() and not p.name.startswith('.'))
        self.comboChapter.blockSignals(True)
        self.comboChapter.clear()
        self.comboChapter.addItems(sorted(chapters, key=natural_key))
        self.comboChapter.blockSignals(False)
        self.onChapterSelected()
        self.updateSelectionSummary()

    def onStudentSelected(self):
        # Batch target changes must not switch the chosen problem.
        self.updateFileList()
        self.updateSelectionSummary()

    def onChapterSelected(self):
        from case_catalog import problem_catalog
        current_problem = self.selectedProblem()
        class_folder = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problems = set()
        if class_folder and chapter:
            for index in range(self.listStudents.count()):
                problems.update(self.eval.get_student_problems(class_folder, self.listStudents.item(index).text(), chapter))
        rows = problem_catalog(class_folder, chapter, problems) if class_folder and chapter else []
        self.comboProblem.blockSignals(True)
        self.comboProblem.clear()
        for row in rows:
            status = '케이스 오류' if row['error'] else f"채점 {row['active']}개" if row['active'] else f"초안 {row['drafts']}개" if row['drafts'] else '케이스 없음'
            self.comboProblem.addItem(f"{row.get('label', row['name'])} · {status}", row['name'])
            self.comboProblem.setItemData(self.comboProblem.count()-1, row['error'] or row['path'], Qt.ItemDataRole.ToolTipRole)
        index = self.comboProblem.findData(current_problem)
        scope = (class_folder, chapter)
        if index >= 0 and getattr(self, '_problem_scope', None) == scope:
            self.comboProblem.setCurrentIndex(index)
        self._problem_scope = scope
        self.comboProblem.blockSignals(False)
        self.comboProblem.setVisible(bool(rows))
        self.lblProblem.setVisible(bool(rows))
        self.onProblemChanged()

    def selectedProblem(self):
        value = self.comboProblem.currentData()
        return value if isinstance(value, str) else self.comboProblem.currentText()

    def isMidterm(self):
        from midterm import is_midterm
        return is_midterm(self.comboClass.currentData(), self.comboChapter.currentText())

    def submissionProblem(self):
        return None if self.isMidterm() or self.comboProblem.isHidden() else self.selectedProblem()

    def studentNames(self, students=None):
        """Roster names as shown in the list; IDs remain the key for paths, reports and lookups."""
        names = {}
        for index in range(self.listStudents.count()):
            item = self.listStudents.item(index)
            name = item.data(Qt.ItemDataRole.UserRole)
            if name and (students is None or item.text() in students):
                names[item.text()] = name
        return names

    def onProblemChanged(self):
        self.latest_view = True
        midterm = self.isMidterm()
        self.midtermPanel.setVisible(midterm)
        self.midtermScoringInfo.setVisible(midterm)
        self.btnAI.setVisible(not midterm)
        self.btnCasePath.setVisible(not midterm)
        self.comboProblem.parentWidget().layout().addWidget(self.comboProblem, 1, 3, 1, 4 if midterm else 1)
        self.casePathPanel.setVisible(not midterm and self.btnCasePath.isChecked())
        self.updateTestCasePath()
        self.updateFileList()
        scope = self.selectedResultScope()
        if self.case_report and self.case_report.context.get('class_name') and any(
                self.case_report.context.get(key) != scope[key] for key in scope):
            self.case_report = None
            self.results = []
            self.btnOpenReport.setEnabled(False)
            self.report_location.setText('선택한 문제의 저장된 정성평가를 DB에서 불러옵니다.')
        self.refreshRunList()
        self.refreshResultsTable()

    def updateFileList(self):
        self.listFiles.clear()
        self.txtCodePreview.clear() # Clear preview on list update
        
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.submissionProblem()
        
        if self.comboProblem.isHidden():
            problem = None # Ignore problem if hidden
            
        selected_items = self.listStudents.selectedItems()
        if not selected_items or not class_name or not chapter:
            return
            
        student_id = selected_items[0].text()
        
        files = self.eval.get_student_files(class_name, student_id, chapter, problem)
        self.listFiles.addItems(files)
        if self.isMidterm():
            matches = self.listFiles.findItems(self.selectedProblem(), Qt.MatchFlag.MatchExactly)
            if matches:
                self.listFiles.setCurrentItem(matches[0])

    def onFileDoubleClicked(self, item):
        filename = item.text()
        
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.submissionProblem()
        
        if self.comboProblem.isHidden():
            problem = None
            
        selected_items = self.listStudents.selectedItems()
        if not selected_items:
            return
        student_id = selected_items[0].text()
        
        content = self.eval.get_file_content(class_name, student_id, chapter, problem, filename)
        
        # Preview is now shared, no need to switch tab
        # self.right_tabs.setCurrentWidget(self.tab_manual)
        
        self.txtCodePreview.setPlainText(content)

    def updateTestCasePath(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.selectedProblem() if not self.comboProblem.isHidden() else None
        if self.isMidterm():
            from midterm import SUITE
            self.txtTestCasePath.setText(str(SUITE))
        else:
            self.txtTestCasePath.setText(str(case_path(class_name, chapter, problem)) if class_name and chapter else '')
        self.refreshCaseInfo()

    def browseMidtermProfile(self):
        path, _ = QFileDialog.getOpenFileName(self, '도서 입력·출력 프로필', self.txtMidtermProfile.text(), '프로필 (*.json)')
        if path:
            self.txtMidtermProfile.setText(path)

    def browseTestPath(self):
        path = QFileDialog.getExistingDirectory(self, "Select Test Case Directory")
        if path:
            self.txtTestCasePath.setText(path)


    def addAuxTab(self):
        page = QWidget()
        layout = QVBoxLayout()
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel('파일 이름:'))
        txt_name = QLineEdit()
        txt_name.setPlaceholderText("e.g. input.txt")
        name_layout.addWidget(txt_name)
        layout.addLayout(name_layout)
        
        layout.addWidget(QLabel('파일 내용:'))
        txt_content = QTextEdit()
        # txt_content.setMaximumHeight(80) 
        layout.addWidget(txt_content)
        
        page.setLayout(layout)
        self.aux_tabs.addTab(page, f"File {self.aux_tabs.count() + 1}")
        self.aux_tabs.setCurrentWidget(page)

    def removeAuxTab(self):
        idx = self.aux_tabs.currentIndex()
        if idx >= 0:
            self.aux_tabs.removeTab(idx)

    def addFile(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.submissionProblem()
        
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

    def deleteFile(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.submissionProblem()
        
        selected_students = self.listStudents.selectedItems()
        selected_files = self.listFiles.selectedItems()
        
        if not selected_students or not selected_files or not class_name:
             QMessageBox.warning(self, "Warning", "Please select a student and a file to delete.")
             return
             
        student_id = selected_students[0].text()
        filename = selected_files[0].text()
        
        confirm = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete '{filename}'?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                                       
        if confirm == QMessageBox.StandardButton.Yes:
            success, msg = self.eval.delete_student_file(class_name, student_id, chapter, problem, filename)
            if success:
                self.updateFileList()
                self.txtCodePreview.clear() # Clear preview if deleted
                QMessageBox.information(self, "Success", f"Deleted {filename}")
            else:
                QMessageBox.critical(self, "Error", f"Failed to delete: {msg}")

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
                self.log_output.append("<span style='font-weight:600;'>Docker Image Built Successfully.</span><br>")
            else:
                self.log_output.append(f"<span style='font-weight:600;'>Docker Build Failed:</span><br>{stderr}<br>")
                
        except Exception as e:
            self.log_output.append(f"<span style='font-weight:600;'>Error launching docker: {e}</span><br>")

    def gradeSelected(self):
        if self.job and self.job.isRunning():
            return
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.selectedProblem()
        midterm = self.isMidterm()
        
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
        elif self.radioLinux.isChecked(): mode = 'linux'
        elif self.radioDocker.isChecked(): mode = 'docker'

        runner_config = {
            'mode': mode,
            'chapter': chapter,
            'problem': self.submissionProblem()
        }

        self.log_output.append("<b>Starting Grading...</b>")
        self.log_output.append(f"<i>Environment: {mode.upper()}</i>")

        students = [item.text() for item in selected_items]
        if self.comboProblem.isHidden():
            runner_config['problem'] = None
        try:
            from grader import Grader
            bundle = None
            if midterm:
                from midterm import load_suite
                from midterm_scoring import settings
                bundle = load_suite(problem, self.txtMidtermProfile.text())
                cases = bundle['cases']
            else:
                cases = Grader().load_test_cases(test_case_dir)
            if not cases:
                raise ValueError('활성 케이스가 없습니다. AI 케이스 생성에서 검토 완료로 저장하거나 케이스 폴더를 확인하세요.')
            names = self.studentNames(students)
            report = CaseReport({'class_name': class_name, 'chapter': chapter, 'problem': problem if midterm else runner_config['problem'],
                                 'mode': mode, 'students': students, 'student_names': names, 'case_count': len(cases),
                                 'case_directory': str(Path(test_case_dir).resolve()), 'cases': cases,
                                 **({'midterm_suite': bundle, 'midterm_scoring': settings()} if midterm else {})})
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            QMessageBox.warning(self, '채점 준비 실패', str(exc))
            return
        self.case_report = report
        self.latest_view = True
        self.grading_active = True
        self.showReportLocation()
        self.results = []
        self.log_output.clear()
        self.resultDetail.clear()
        self.right_tabs.setCurrentWidget(self.tab_grade)
        self.refreshResultsTable()
        self.resultHeadline.setText(f'{len(students)}명 채점 중 · 완료한 학생부터 결과를 표시합니다.')
        self.progress_bar.setMaximum(len(students))
        self.progress_bar.setValue(0)
        def grade(progress):
            from grader import Grader
            from paths import ORIGIN
            grader = Grader()
            rows = []
            try:
                if mode == 'docker':
                    from core.service import environment
                    environment(mode, 'grader-image', 'c')
                for index, student in enumerate(students, 1):
                    if self.job.isInterruptionRequested():
                        report.save(rows, 'cancelled')
                        return rows
                    try:
                        if midterm:
                            from midterm import grade_suite
                            results = grade_suite(ORIGIN / class_name / student / chapter, bundle, runner_config)
                        else:
                            results = grader.grade_student(ORIGIN / class_name / student, cases, runner_config)
                    except Exception as exc:
                        results = [{'case': 'Setup', 'passed': False, 'status': 'error', 'message': str(exc)}]
                    for result in results:
                        rows.append(dict(result, class_name=class_name, student=student, student_name=names.get(student, ''), chapter=chapter,
                                         problem=result.get('target_file', problem) if midterm else runner_config['problem']))
                    report.save(rows)
                    progress(index)
                report.save(rows, 'completed')
            except Exception as exc:
                try:
                    report.save(rows, 'error', str(exc))
                except OSError:
                    pass
                raise
            return rows
        self.startJob(grade, self.gradingDone)
        self.job.progress.connect(self.onGradingProgress)
        self.job.failed.connect(self.gradingFailed)
        self.job.finished.connect(self.finishGrading)

    def startJob(self, function, callback):
        if self.job and self.job.isRunning():
            return
        self.job = Job(function, self)
        self.setBusy(True)
        self.job.result.connect(callback)
        self.job.failed.connect(lambda text: self.displayLog('Error: ' + html.escape(text)))
        self.job.progress.connect(self.progress_bar.setValue)
        self.job.finished.connect(lambda: self.setBusy(False))
        self.job.start()

    def setBusy(self, busy):
        self.busy = busy
        for widget in (self.btnGrade, self.btnRunManual, self.btnLoad, self.btnAddFile,
                       self.btnDeleteFile, self.comboClass, self.comboYear, self.comboChapter,
                       self.comboProblem, self.listStudents, self.btnMaker, self.btnReview, self.actionManifestGrading,
                       self.btnReadReport, self.txtTestCasePath, self.btnBrowseTestPath, self.btnAI,
                       self.btnSelectAll, self.btnClearSelection, self.btnQualitative, self.actionEnvironment,
                       self.comboRuns, self.btnReloadReviews,
                       self.radioWin, self.radioLinux, self.radioDocker, self.radioWSL):
            widget.setEnabled(not busy)
        self.txtMidtermProfile.setEnabled(not busy)
        self.btnMidtermProfile.setEnabled(not busy)
        self.btnMidtermScore.setEnabled(not busy)
        self.btnStop.setEnabled(busy and self.grading_active)

    def updateSelectionSummary(self):
        if not hasattr(self, 'btnGrade'):
            return
        count = len(self.listStudents.selectedItems())
        total = self.listStudents.count()
        self.selectionCount.setText(f'선택 {count}명 / 전체 {total}명')
        self.btnGrade.setText(f'선택 {count}명 일괄 채점' if count else '학생을 선택하세요')
        if not count:
            self.batchSummary.setText('왼쪽에서 ‘전체 선택’을 누르거나 채점할 학생을 클릭하세요.')
        elif not self.comboChapter.currentText():
            self.batchSummary.setText('채점할 장과 문제를 선택하세요.')
        elif not self.active_case_count:
            self.batchSummary.setText('활성 케이스가 없습니다. ‘AI 케이스 생성’에서 검토 완료로 저장하세요.')
        else:
            problem = ('전체 문제 (7개 파일)' if self.selectedProblem() == '__all__' else self.selectedProblem()) if not self.comboProblem.isHidden() else ''
            mode = 'Docker' if self.radioDocker.isChecked() else ('WSL' if self.radioWSL.isChecked() else ('Linux' if self.radioLinux.isChecked() else 'Windows'))
            if self.isMidterm():
                self.batchSummary.setText(f'{self.comboClass.currentText()} · midterm · {problem}\n학생 {count}명 × 케이스 {self.active_case_count}개 · {mode}')
            else:
                self.batchSummary.setText(f'{self.comboClass.currentText()} · {self.comboChapter.currentText()} {problem} · 학생 {count}명 × 케이스 {self.active_case_count}개 · {mode}')
        self.batchSummary.setMinimumHeight(self.batchSummary.fontMetrics().lineSpacing() * 2 + 8 if self.isMidterm() else 0)

    def stopGrading(self):
        if self.grading_active and self.job and self.job.isRunning():
            self.job.requestInterruption()
            self.btnStop.setEnabled(False)
            self.resultHeadline.setText('현재 학생의 결과를 저장한 뒤 중지합니다. 완료한 결과는 유지됩니다.')

    def onGradingProgress(self, index):
        if self.case_report:
            try:
                saved = self.case_report.saved()
                self.results = saved['results']
                self.refreshResultsTable()
                self.resultHeadline.setText(f"{index} / {len(self.case_report.context['students'])}명 완료 · 결과 자동 저장 중")
            except (OSError, ValueError) as exc:
                self.displayLog(html.escape(str(exc)))

    def finishGrading(self):
        self.grading_active = False
        self.btnStop.setEnabled(False)
        self.refreshResultsTable()

    def gradingFailed(self, message):
        self.onGradingProgress(self.progress_bar.value())
        self.resultHeadline.setText('채점 중단: ' + message)

    def refreshResultsTable(self):
        self.loadLatestGradebook()
        context = self.display_context
        self.loadResultReviews()
        if self.latest_view:
            self.showReportLocation()
        self.resultDetail.clear()
        scored = 'midterm_scoring' in context
        self.btnMidtermScore.setVisible(scored)
        if scored:
            self.refreshMidtermScores()
            return
        self.resultLegend.setText('O 통과 · △ 부족(일부 통과) · X 오답(통과 없음) · — 미판정')
        selected = self.resultStudent(self.resultTable.currentRow()) if self.resultTable.currentRow()>=0 else None
        self.resultTable.blockSignals(True)
        self.resultTable.setSortingEnabled(False)
        self.resultTable.clearContents()
        from result_reviews import HEADERS
        self.resultTable.setColumnCount(6 + (len(HEADERS) if self.result_reviews else 0))
        self.resultTable.setHorizontalHeaderLabels(['학번', '이름', '판정', '기호', '통과 / 전체', '실패 케이스'] +
                                                   (HEADERS if self.result_reviews else []))
        if (getattr(self,'_result_sort_schema',None)!='cases' or
                self.resultTable.horizontalHeader().sortIndicatorSection() >= self.resultTable.columnCount()):
            self.resultTable.horizontalHeader().setSortIndicator(0,Qt.SortOrder.AscendingOrder)
        self._result_sort_schema='cases'
        self.resultTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.resultTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        if self.result_reviews:
            # Additional score columns should scroll, rather than squeezing IDs/names and headers.
            header = self.resultTable.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            for column in range(6):
                width = header.fontMetrics().horizontalAdvance(self.resultTable.horizontalHeaderItem(column).text()) + 36
                self.resultTable.setColumnWidth(column, max(110, width))
        students = context.get('students')
        names = dict(context.get('student_names') or {})
        if not self.case_report or self.gradebook:
            students = list(dict.fromkeys([*[self.listStudents.item(i).text() for i in range(self.listStudents.count())],
                                           *self.result_reviews]))
            names = self.studentNames()
        for student, reviews in self.result_reviews.items():
            if not names.get(student):
                names[student] = next((r.get('student_name') for r in reviews if r.get('student_name')), '')
        if self.gradebook:
            self.gradebook.context['students'] = list(dict.fromkeys([*context['students'], *self.result_reviews]))
            self.gradebook.context['student_names'].update({s: n for s, n in names.items() if n})
            summaries = self.gradebook.summaries()
        else:
            summaries = summarize_cases(self.display_rows, students, context.get('case_count', 0),
                                        self.case_report.state if self.case_report else 'completed', names)
        self.resultTable.setRowCount(len(summaries))
        labels = {'pending': '대기', 'not_run': '미실행', 'ungraded': '채점 불가', 'manual_review': '수동 검토',
                  'needs_review': '검토 필요'}
        for index, summary in enumerate(summaries):
            passed, total = summary['passed_cases'], summary['total_cases']
            status = labels.get(summary['status'], '모두 통과' if passed == total else '오답 있음')
            symbol = '—'
            if summary['status'] == 'graded' and total > 0:
                symbol = 'O' if passed == total else ('△' if passed else 'X')
            name=str(summary.get('student_name') or '')
            values = [summary['student'], name, status, symbol, '—' if passed is None else f'{passed} / {total}',
                      '—' if passed is None else str(total - passed)]
            sort_values=[student_sort_value(summary['student']),name,status,symbol,passed,None if passed is None else total-passed]
            for column, (value,sort_value) in enumerate(zip(values,sort_values)):
                item = SortableItem(value,sort_value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, summary['student'])
                if column == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    font = item.font(); font.setBold(True); item.setFont(font)
                    item.setToolTip({'O': '통과: 모든 케이스를 통과했습니다.',
                                     '△': '부족: 일부 케이스만 통과했습니다.',
                                     'X': '오답: 통과한 케이스가 없습니다.',
                                     '—': '아직 판정할 수 없습니다. 판정 열과 상세 근거를 확인하세요.'}[symbol])
                self.resultTable.setItem(index, column, item)
            self.setResultReviewCells(index, summary['student'], 6)
        self.resultTable.setSortingEnabled(True)
        self.resultTable.blockSignals(False)
        self.restoreResultStudent(selected)
        self.showResultReviewLegend()

    def selectedResultScope(self):
        return dict(class_name=self.comboClass.currentData(), chapter=self.comboChapter.currentText(),
                    problem=None if self.comboProblem.isHidden() else self.selectedProblem())

    def loadLatestGradebook(self):
        self.gradebook = None
        self.gradebook_error = None
        if self.latest_view:
            from latest_gradebook import LatestGradebook
            try:
                gradebook = LatestGradebook(self.selectedResultScope(),
                    [self.listStudents.item(i).text() for i in range(self.listStudents.count())], self.studentNames())
                if gradebook.records:
                    self.gradebook = gradebook
            except Exception as exc:
                self.gradebook_error = str(exc)
        self.display_context = self.gradebook.context if self.gradebook else (self.case_report.context if self.case_report else {})
        self.display_rows = self.gradebook.rows if self.gradebook else self.results

    def showLatestResults(self):
        if self.grading_active:
            return
        if not self.latest_view:
            self.case_report = None
            self.results = []
        self.latest_view = True
        self.comboRuns.setCurrentIndex(0)
        self.refreshResultsTable()
        self.showReportLocation()

    def loadResultReviews(self):
        import db
        scope = self.display_context or self.selectedResultScope()
        problem = scope.get('problem')
        problems = [problem]
        if problem == '__all__':
            from midterm import TARGETS
            problems.extend(TARGETS)
        self.result_reviews = {}
        self.result_reviews_all = problem == '__all__'
        try:
            rows = db.latest_qualitative_reviews(scope.get('class_name'), scope.get('chapter'), problems)
            for row in sorted(rows, key=lambda r: (str(r.get('problem') or ''), r['student'])):
                self.result_reviews.setdefault(row['student'], []).append(row)
            self.result_reviews_error = None
        except Exception as exc:
            self.result_reviews_error = str(exc)

    def setResultReviewCells(self, index, student, start):
        if not self.result_reviews:
            return
        from result_reviews import cells, details
        reviews = self.result_reviews.get(student, [])
        tooltip = '\n\n'.join(details(row) for row in reviews) or '이 문제에 저장된 정성평가가 없습니다.'
        for column, (text, sort) in enumerate(cells(reviews, self.result_reviews_all), start):
            item = SortableItem(text, sort)
            item.setToolTip(tooltip)
            self.resultTable.setItem(index, column, item)
            self.resultTable.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.resultTable.setColumnWidth(column, 170)

    def showResultReviewLegend(self):
        if self.gradebook_error:
            self.resultLegend.setText(self.resultLegend.text() + '\n최신 점수표 DB 읽기 실패: ' + self.gradebook_error)
        if self.result_reviews_error:
            self.resultLegend.setText(self.resultLegend.text() + '\n정성평가 DB 읽기 실패: ' + self.result_reviews_error)
        elif self.result_reviews:
            self.resultLegend.setText(self.resultLegend.text() +
                '\n정성평가: DB의 학생·문제별 최근 평가(재시도 실패 시 이전 점수 유지) · 확정 전 점수는 AI 제안 · 실행 점수와 별도 표시' +
                (' · 전체 보기에서는 파일별 점수를 각각 표시' if self.result_reviews_all else ''))
        if not self.case_report and not self.results:
            self.resultHeadline.setText(f'저장된 정성평가 {len(self.result_reviews)}명 · 실행 채점 미실행' if self.result_reviews
                                       else '아직 채점 결과가 없습니다. 아래 일괄 채점 버튼을 눌러 시작하세요.')
        if self.gradebook:
            self.resultLegend.setText(self.resultLegend.text() + '\n최신 점수표: 학생·문제별 최근 실행 + 저장된 수동 조정 점수')
            if not self.grading_active:
                stopped = self.case_report and self.case_report.state == 'cancelled'
                self.resultHeadline.setText(('최근 실행 중지됨 · ' if stopped else '') +
                    f'최신 점수표 · {self.resultTable.rowCount()}명 · 실행·정성평가·점수 조정 자동 반영')

    def midtermScores(self):
        from midterm_scoring import score_students
        if self.gradebook:
            self.gradebook.context['students'] = list(dict.fromkeys([*self.gradebook.context['students'], *self.result_reviews]))
            return self.gradebook.scores(self.case_report.state if self.grading_active and self.case_report else 'completed')
        return score_students(self.results, self.case_report.context, self.case_report.state,
                              self.case_report.score_overrides)

    def refreshMidtermScores(self):
        from midterm import TARGETS
        from midterm_scoring import POINTS
        selected = self.resultStudent(self.resultTable.currentRow()) if self.resultTable.currentRow()>=0 else None
        table = self.resultTable
        table.blockSignals(True)
        table.setSortingEnabled(False)
        table.clearContents()
        from result_reviews import HEADERS
        table.setColumnCount(13 + (len(HEADERS) if self.result_reviews else 0))
        table.setHorizontalHeaderLabels(['학번', '이름', '점수 상태', '총점',
            *[f'{TARGETS[t].split(" · ")[0]}\n{POINTS[t]}점' for t in POINTS], '통과 / 전체', '사유'] +
            (HEADERS if self.result_reviews else []))
        if (getattr(self,'_result_sort_schema',None)!='midterm' or
                table.horizontalHeader().sortIndicatorSection() >= table.columnCount()):
            table.horizontalHeader().setSortIndicator(0,Qt.SortOrder.AscendingOrder)
        self._result_sort_schema='midterm'
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(12, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(12, 340)
        scores = self.midtermScores()
        table.setRowCount(len(scores))
        labels = {'graded': '자동 계산', 'adjusted': '점수 조정', 'needs_review': '검토 필요',
                  'pending': '대기', 'not_run': '미실행'}
        for index, row in enumerate(scores):
            total = '검토 필요' if row['final_score'] is None else f'{row["final_score"]:g} / {row["max_score"]:g}'
            name=str(row.get('student_name') or self.studentNames().get(row['student']) or
                     next((r.get('student_name') for r in self.result_reviews.get(row['student'], [])
                           if r.get('student_name')), ''))
            values = [row['student'], name, labels[row['status']], total]
            sort_values=[student_sort_value(row['student']),name,values[2],row['final_score']]
            for target in POINTS:
                problem = row['problems'].get(target)
                values.append('—' if problem is None else ('검토' if problem['final_score'] is None else f'{problem["final_score"]:g}'))
                sort_values.append(problem['final_score'] if problem is not None else None)
            values.append(f'{row["passed_cases"]} / {row["total_cases"]}')
            values.append(row['reason_short'])
            sort_values.extend([row['passed_cases'],row['reason_short']])
            for column, (value,sort_value) in enumerate(zip(values,sort_values)):
                item = SortableItem(value,sort_value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row['student'])
                if column == 12:
                    item.setToolTip(row['reason'])
                if 4 <= column <= 10:
                    target = list(POINTS)[column - 4]
                    problem = row['problems'].get(target)
                    item.setToolTip(target + (f'\n필수 통과 {problem["passed_required"]}/{problem["required_cases"]}'
                                              f'\n자동 {problem["auto_score"]} / 최종 {problem["final_score"]} / 배점 {problem["max_score"]}' if problem else '\n이번 실행에서 선택하지 않은 문제'))
                table.setItem(index, column, item)
            self.setResultReviewCells(index, row['student'], 13)
        table.setSortingEnabled(True)
        table.blockSignals(False)
        self.resultLegend.setText('점수 = 문제 배점 × 필수 케이스 통과 비율 (소수 둘째 자리) · 추가 케이스는 점수 제외 · 검토 문제는 총점 미확정')
        self.restoreResultStudent(selected)
        self.showResultReviewLegend()

    def adjustMidtermScore(self):
        if self.grading_active or 'midterm_scoring' not in self.display_context:
            return
        if self.resultTable.currentRow() < 0 and self.resultTable.rowCount():
            self.resultTable.selectRow(0)
        if self.resultTable.currentRow() < 0:
            return
        student = self.resultStudent(self.resultTable.currentRow())
        row = next(s for s in self.midtermScores() if s['student'] == student)
        from midterm import TARGETS
        dialog = QDialog(self); dialog.setWindowTitle(f'{student} · 문제 점수 조정')
        form = QFormLayout(dialog)
        target = QComboBox()
        for filename, problem in row['problems'].items():
            target.addItem(f'{TARGETS[filename]} [{filename}] · {problem["max_score"]}점', filename)
        score = QDoubleSpinBox(); score.setDecimals(2); score.setObjectName('midtermFinalScore')
        auto = QLabel()
        def select_problem():
            problem = row['problems'][target.currentData()]
            score.setRange(0, problem['max_score']); score.setValue(problem['final_score'] or 0)
            auto.setText(f'자동 점수: {problem["auto_score"] if problem["auto_score"] is not None else "미확정"} · 자동 판정과 이전 조정 이력을 보존합니다.')
        target.currentIndexChanged.connect(select_problem); select_problem()
        reviewer = QLineEdit(); reviewer.setObjectName('midtermReviewer')
        reason = QLineEdit(); reason.setObjectName('midtermReason')
        error = QLabel(); error.setWordWrap(True)
        save = QPushButton('점수 저장'); save.setObjectName('saveMidtermScore')
        form.addRow('문제', target); form.addRow(auto); form.addRow('최종 점수', score)
        form.addRow('검토자', reviewer); form.addRow('조정 사유', reason); form.addRow(error); form.addRow(save)
        def persist():
            try:
                if self.gradebook:
                    self.gradebook.adjust(student, target.currentData(), score.value(), reviewer.text(), reason.text())
                else:
                    self.case_report.override_midterm_score(student, target.currentData(), score.value(), reviewer.text(), reason.text())
                self.refreshResultsTable()
                dialog.accept()
            except (OSError, ValueError) as exc:
                error.setText(str(exc))
        save.clicked.connect(persist)
        dialog.exec()

    def resultStudent(self, index):
        """Sorting changes visual rows; the ID alone identifies the student."""
        item = self.resultTable.item(index, 0)
        return (item.data(Qt.ItemDataRole.UserRole) or item.text()) if item is not None else None

    def restoreResultStudent(self, student):
        if student is None:return
        for index in range(self.resultTable.rowCount()):
            if self.resultStudent(index)==student:
                self.resultTable.selectRow(index);self.showResultDetails();return

    def showResultDetails(self):
        index = self.resultTable.currentRow()
        if index < 0 or self.resultTable.item(index, 0) is None:
            return
        student = self.resultStudent(index)
        from student_names import student_label
        lines = [f'학생 {student_label(dict(student=student,student_name=self.resultTable.item(index,1).text()))} · 케이스별 상세 결과']
        from result_reviews import details
        for review in getattr(self, 'result_reviews', {}).get(student, []):
            lines.extend(['', details(review), ''])
        if 'midterm_scoring' in self.display_context:
            summary = next(s for s in self.midtermScores() if s['student'] == student)
            lines.append(f'총점: {summary["final_score"]} / {summary["max_score"]} · 문제별 필수 케이스 통과 비율 적용')
            lines.extend(['사유:', summary['reason']])
            for target, score in summary['problems'].items():
                lines.append(f'{target}: 자동 {score["auto_score"]}, 최종 {score["final_score"]} / {score["max_score"]}점 · 필수 {score["passed_required"]}/{score["required_cases"]}')
                for adjustment in score['overrides']:
                    lines.append(f'점수 조정: {adjustment["previous_score"]} → {adjustment["score"]} · {adjustment["reviewer"]} · {adjustment["reason"]} · {adjustment["at"]}')
        labels = {'passed': '통과', 'wrong_answer': '오답', 'compile_error': '컴파일 오류',
                  'runtime_error': '실행 오류', 'timeout': '시간 초과', 'output_limit': '출력 제한 초과',
                  'missing': '제출 경로 없음', 'missing_source': '제출 없음 · 0점', 'empty_source': '빈 제출 · 0점',
                  'error': '채점 오류', 'no_tests': '케이스 없음', 'needs_review': '검토 필요'}
        def display(value):
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        for row in self.display_rows:
            if row['student'] != student:
                continue
            lines.extend(['', f"[{row['case']}] {labels.get(row['status'], row['status'])}"])
            if row.get('source_run'):
                lines.append(f"실행 기록: {row['source_run']} · {row.get('graded_at', '')}")
            if row.get('target_file'): lines.append('대상 파일: ' + row['target_file'])
            if row.get('message'): lines.append(row['message'])
            if row.get('expected') is not None: lines.extend(['기대 출력:', display(row['expected'])])
            if row.get('actual') is not None: lines.extend(['실제 출력:', display(row['actual'])])
            if row.get('stderr'): lines.extend(['오류 출력:', row['stderr']])
            for step in row.get('trace', []):
                lines.extend([f"실행 단계: {step['source']} (종료 코드 {step.get('returncode')})",
                              '입력:', step.get('input', ''), '출력:', step.get('stdout', '')])
                if step.get('stderr'): lines.extend(['오류 출력:', step['stderr']])
            for filename, result in row.get('file_results', {}).items():
                lines.extend([f"파일 {filename}: {'통과' if result['passed'] else '미통과'}",
                              '기대 내용:', result['expected'], '실제 내용:', result['actual'] if result['actual'] is not None else '(파일 없음 또는 크기 초과)'])
        self.resultDetail.setPlainText('\n'.join(lines))

    def openResultDetails(self):
        if self.resultTable.currentRow() < 0:
            if not self.resultTable.rowCount():
                self.resultHeadline.setText('채점 결과가 생기면 학생별 상세 근거를 볼 수 있습니다.')
                return
            self.resultTable.selectRow(0)
        self.showResultDetails()
        self.detailDialog.show()
        self.detailDialog.raise_()

    def gradingDone(self, rows):
        self.results = rows
        self.refreshResultsTable()
        count = len({r['student'] for r in rows})
        stopped = self.case_report and self.case_report.state == 'cancelled'
        self.resultHeadline.setText(f"{'중지됨' if stopped else '채점 완료'} · {count}명 결과 · 학생 선택 후 ‘상세 근거 보기’를 누르세요.")
        for row in rows:
            self.log_output.append('<b>' + html.escape(f"{row['student']} / {row['case']}: {row['status']}") + '</b>')
            self.log_output.append('<pre>' + html.escape(str(row.get('message') or row.get('actual', ''))) + '</pre>')
            if not row['passed'] and row.get('expected') is not None:
                self.log_output.append('<pre>Expected: ' + html.escape(str(row['expected'])) + '</pre>')
            if row.get('files'):
                self.log_output.append(html.escape(str(row['files'])))
        self.log_output.append(f"Finished: {sum(r['passed'] for r in rows)}/{len(rows)} passed")
        labels = {'graded': '판정 완료', 'ungraded': '채점 불가', 'not_run': '미실행', 'pending': '대기',
                  'manual_review': '수동 검토', 'needs_review': '검토 필요'}
        from student_names import student_label
        if self.case_report and 'midterm_scoring' in self.case_report.context:
            for summary in self.midtermScores():
                text = '총점 미확정 · 검토 필요' if summary['final_score'] is None else f"{summary['final_score']:g} / {summary['max_score']:g}점"
                self.log_output.append(html.escape(f"{student_label(summary)}: {text}"))
        else:
            for summary in summarize_cases(rows):
                count = '점수 없음' if summary['passed_cases'] is None else f"{summary['passed_cases']}/{summary['total_cases']} 케이스 통과"
                self.log_output.append(html.escape(f"{student_label(summary)}: {labels[summary['status']]} · {count}"))
        if self.case_report:
            self.showReportLocation()
            self.log_output.append(html.escape(f'자동 저장: {self.case_report.directory}'))
        self.refreshRunList()

    def refreshCaseInfo(self):
        from grader import Grader
        try:
            if self.isMidterm():
                from midterm import load_suite
                from midterm_scoring import POINTS
                cases = load_suite(self.selectedProblem(), self.txtMidtermProfile.text())['cases']
            else:
                cases = Grader().load_test_cases(self.txtTestCasePath.text()) if self.txtTestCasePath.text() else []
            self.active_case_count = len(cases)
            if self.isMidterm():
                required = sum(c.get('category') != 'extra' for c in cases)
                points = sum(POINTS[t] for t in {c['target_file'] for c in cases})
                self.case_info.setText(f'배점 {points}점 · 필수 {required}개로 점수 계산 / 추가 {len(cases) - required}개는 진단용 · True = 대출 가능')
            else:
                self.case_info.setText(f'활성 케이스 {len(cases)}개 · 초안은 제외됩니다.' if cases else '활성 케이스 없음 · AI 케이스를 생성하거나 케이스 폴더를 선택하세요.')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.active_case_count = 0
            self.case_info.setText('케이스 확인 오류: ' + str(exc))
        self.updateSelectionSummary()

    def showReportLocation(self):
        if self.latest_view:
            import db
            self.report_location.setText(f'최신 점수표: {db.default_path()} · 과거 실행 선택은 선택사항입니다.')
            self.report_location.setToolTip('학생별 상세 근거에서 사용한 실행 기록과 점수 조정 내역을 확인합니다.')
            self.btnOpenReport.setEnabled(False)
            return
        if not self.case_report:
            return
        self.report_location.setText(f'자동 저장: {self.case_report.directory}')
        self.report_location.setCursorPosition(0)
        summary = '문제별 점수·총점' if 'midterm_scoring' in self.case_report.context else '학생별 통과 수'
        self.report_location.setToolTip(f'{self.case_report.directory}\nrun.json: 전체 근거 · cases.csv: 케이스별 판정 · summary.csv: {summary}')
        self.btnOpenReport.setEnabled(True)

    def openReportFolder(self):
        if self.case_report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.case_report.directory)))

    def readCaseReport(self):
        """Open a run.json export (for example copied from another PC) and keep it in the database."""
        from paths import ROOT
        path, _ = QFileDialog.getOpenFileName(self, '저장된 채점 결과', str(ROOT / 'reports' / 'case-grading'), '채점 기록 (run.json)')
        if path:
            try:
                report, document = CaseReport.open(path)
                import db
                db.save_run(report.directory.name, report.context, document['results'], report.state,
                            document.get('error'), report.score_overrides, report.created_at, report.directory)
                self.showSavedRun(report, document)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, '기록 열기 실패', str(exc))

    def showSavedRun(self, report, document):
        self.latest_view = False
        self.case_report = report
        self.log_output.clear()
        self.gradingDone(document['results'])
        self.log_output.append(html.escape('저장된 실행 상태: ' + str(document.get('state'))))
        if document.get('error'):
            self.log_output.append(html.escape(document['error']))
        self.resultHeadline.setText('과거 실행 조회 · ' + report.directory.name + ' · 최신 점수표는 목록의 첫 항목으로 돌아가세요.')

    def refreshRunList(self):
        """Saved runs for the selected class and chapter, newest first; the current run stays selected."""
        import db
        from datetime import datetime
        combo = self.comboRuns
        current = self.case_report.directory.name if self.case_report and not self.latest_view else None
        combo.blockSignals(True)
        combo.clear()
        combo.addItem('최신 점수표 (기본)', None)
        try:
            runs = db.list_runs(self.comboClass.currentData(), self.comboChapter.currentText()) if self.comboClass.currentData() else []
        except Exception as exc:  # a damaged database must not block grading
            runs = []
            self.displayLog('저장된 실행 목록을 읽지 못했습니다: ' + html.escape(str(exc)))
        states = {'completed': '완료', 'cancelled': '중지됨', 'running': '진행 중', 'error': '오류'}
        for run in runs:
            try:
                stamp = datetime.fromisoformat(run['created_at']).astimezone().strftime('%Y-%m-%d %H:%M')
            except (TypeError, ValueError):
                stamp = run['id']
            problem = run['problem'] or '문제 없음'
            if problem == '__all__':
                problem = '중간고사 전체'
            combo.addItem(f"{stamp} · {problem} · {states.get(run['state'], run['state'])} · {run['student_count']}명", run['id'])
        if current is not None and combo.findData(current) >= 0:
            combo.setCurrentIndex(combo.findData(current))
        combo.blockSignals(False)
        combo.setToolTip(f'기본은 학생·문제별 최신 점수표입니다. 과거 실행 {len(runs)}개는 필요할 때만 선택하세요.')

    def loadSavedRun(self):
        run_id = self.comboRuns.currentData()
        if not run_id:
            self.showLatestResults()
            return
        if self.grading_active or (not self.latest_view and self.case_report and self.case_report.directory.name == run_id):
            return
        try:
            report, document = CaseReport.load(run_id)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '기록 열기 실패', str(exc))
            return
        self.showSavedRun(report, document)

    def importReports(self):
        """Load run.json folders and qualitative_*.json files written before the database existed."""
        import db
        try:
            runs = db.import_reports()
            reviews = db.import_qualitative()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '기록 가져오기 실패', str(exc))
            return
        self.refreshRunList()
        self.refreshResultsTable()
        QMessageBox.information(self, '기록 가져오기', f'채점 {len(runs)}개 · 정성평가 {len(reviews)}개 실행을 DB에 추가했습니다.\n{db.default_path()}')

    def recordReview(self):
        students = [item.text() for item in self.listStudents.selectedItems()]
        if not students:
            QMessageBox.information(self, '수동 평가', '평가할 학생을 선택하세요.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('수동 평가 기록')
        layout = QFormLayout(dialog)
        decision = QComboBox()
        decision.addItems(['통과', '미통과'])
        notes = QTextEdit()
        notes.setPlaceholderText('확인한 실습, 원본 판본·쪽, 실행 조건과 판단 근거를 기록하세요.')
        layout.addRow('판정', decision)
        layout.addRow('검토 근거', notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not notes.toPlainText().strip():
            QMessageBox.warning(self, '수동 평가', '검토 근거를 입력해야 기록할 수 있습니다.')
            return
        passed = decision.currentIndex() == 0
        context = {'class_name': self.comboClass.currentData(), 'chapter': self.comboChapter.currentText(),
                   'problem': None if self.comboProblem.isHidden() else self.selectedProblem()}
        if self.case_report and any(self.case_report.context.get(k) != v for k, v in context.items()):
            self.case_report = None
            self.results = []
        names = self.studentNames(students)
        for student in students:
            self.results.append({'class_name': self.comboClass.currentData(), 'student': student, 'student_name': names.get(student, ''),
                                 'chapter': self.comboChapter.currentText(),
                                 'problem': self.selectedProblem(), 'case': 'Manual review',
                                 'passed': passed, 'status': 'manual_passed' if passed else 'manual_failed',
                                 'message': notes.toPlainText()})
        try:
            if self.case_report is None:
                self.case_report = CaseReport({**context, 'students': students, 'student_names': names, 'case_count': 0})
                self.case_report.state = 'completed'
            self.case_report.save(self.results, self.case_report.state)
            self.showReportLocation()
            self.displayLog(f'수동 평가 {len(students)}건 자동 저장.')
        except OSError as exc:
            self.displayLog('저장 실패: ' + html.escape(str(exc)))

    def exportResults(self):
        if not self.display_rows and not self.result_reviews and not self.listStudents.count():
            QMessageBox.information(self, '내보내기', '분반과 문제를 선택하세요.')
            return
        path, _ = QFileDialog.getSaveFileName(self, '점수표 내보내기', 'latest_gradebook.csv',
                                             '최신 점수표 CSV (*.csv);;JSON (*.json)')
        if path:
            from peewee import PeeweeException
            try:
                if Path(path).suffix.lower() == '.csv':
                    from gradebook_csv import export_latest_csv
                    count = export_latest_csv(path, self.selectedResultScope(),
                        [self.listStudents.item(i).text() for i in range(self.listStudents.count())], self.studentNames())
                    self.displayLog(f'최신 점수표 CSV 저장 · {count}명 · ' + html.escape(path))
                elif self.gradebook:
                    from core.record import atomic_text
                    document = self.gradebook.document()
                    document['qualitative_reviews'] = self.result_reviews
                    if self.gradebook.midterm:
                        document['scores'] = self.midtermScores()
                    else:
                        document['summaries'] = self.gradebook.summaries()
                    atomic_text(path, json.dumps(document, ensure_ascii=False, indent=2))
                elif 'midterm_scoring' in self.display_context:
                    from core.record import atomic_text
                    document = self.case_report.saved()
                    atomic_text(path, json.dumps(document, ensure_ascii=False, indent=2))
                else:
                    save_report(path, self.display_rows)
            except (OSError, ValueError, PeeweeException) as exc:
                QMessageBox.warning(self, 'Export', str(exc))

    def openProblemGrading(self):
        from grading_window import GradingWindow
        from paths import ORIGIN, safe_path
        if hasattr(self, 'problem_grading_window') and self.problem_grading_window.isVisible():
            self.problem_grading_window.raise_()
            return
        class_name = self.comboClass.currentData()
        submissions = [{'student_id': item.text(), 'path': str(safe_path(ORIGIN, class_name, item.text()))}
                       for item in self.listStudents.selectedItems()] if class_name else []
        self.problem_grading_window = GradingWindow(submissions)
        self.problem_grading_window.show()

    def openQualitative(self):
        from qualitative_gui import QualitativeWindow
        from paths import ORIGIN, safe_path
        class_name = self.comboClass.currentData()
        selected = self.listStudents.selectedItems()
        if not class_name or not selected:
            QMessageBox.information(self, '정성평가', '분반과 평가할 학생을 선택하세요.')
            return
        chapter = self.comboChapter.currentText()
        problem = self.submissionProblem()
        if not chapter or chapter == '(No Files)':
            QMessageBox.information(self, '정성평가', '평가할 장과 문제를 선택하세요.')
            return
        preset = None
        extra = {}
        if self.isMidterm():
            # Exam files share one midterm/ folder: send only the selected problem's file(s) with the paper's statement.
            from midterm_qualitative import qualitative_preset
            try:
                preset = qualitative_preset(self.selectedProblem())
            except (OSError, ValueError, KeyError, TypeError) as exc:
                QMessageBox.warning(self, '정성평가', f'중간고사 문제 정보를 읽지 못했습니다: {exc}')
                return
            extra = dict(problem=self.selectedProblem(), sources=preset['sources'])
        submissions = [{**dict(class_name=class_name, student=item.text(), student_name=item.data(Qt.ItemDataRole.UserRole) or '', chapter=chapter, problem=problem,
                               path=str(safe_path(ORIGIN, class_name, item.text(), chapter, problem))), **extra}
                       for item in selected]
        existing=getattr(self,'qualitative_window',None)
        if existing is not None and existing.isVisible():
            if existing.worker and existing.worker.isRunning():
                existing.raise_()
                existing.status.setText('정성평가가 진행 중입니다. 완료하거나 중지한 뒤 평가 대상을 바꾸세요.')
                return
            assignment=lambda s:tuple(s.get(k,'') for k in ('class_name','chapter','problem'))
            if existing.submissions and assignment(existing.submissions[0])==assignment(submissions[0]):
                existing.select_submissions(submissions);existing.raise_();return
            existing.close()
        self.qualitative_window = QualitativeWindow(submissions, preset)
        self.qualitative_window.reviews_saved.connect(self.refreshResultsTable)
        self.qualitative_window.show()

    def openAIMaker(self):
        from ai_case_generator import AICaseMaker
        if hasattr(self, 'ai_maker') and self.ai_maker.isVisible():
            self.ai_maker.raise_()
            return
        self.ai_maker = AICaseMaker(self.comboClass.currentData() or 'system',
                                   self.comboChapter.currentText(), self.selectedProblem())
        self.ai_maker.cases_saved.connect(self.onAICasesSaved)
        self.ai_maker.show()

    def onAICasesSaved(self, saved):
        from paths import lecture_name
        current = self.comboClass.currentData()
        if current and lecture_name(current) == lecture_name(saved['class_name']):
            if self.comboChapter.findText(saved['chapter']) < 0:
                self.comboChapter.addItem(saved['chapter'])
            if saved['enabled']:
                self.comboChapter.setCurrentText(saved['chapter'])
            self.onChapterSelected()
            if saved['enabled']:
                index = self.comboProblem.findData(saved['problem'])
                if index >= 0:
                    self.comboProblem.setCurrentIndex(index)
        if not saved['enabled']:
            self.refreshCaseInfo()
            return
        matches = (current and lecture_name(current) == lecture_name(saved['class_name'])
                   and self.comboChapter.currentText() == saved['chapter']
                   and self.selectedProblem() == saved['problem'])
        if matches:
            self.txtTestCasePath.setText(saved['destination'])
            self.refreshCaseInfo()
            self.displayLog(f"검토 완료 케이스 {saved['count']}개 추가. 대상 학생 수를 확인하고 ‘일괄 채점’ 버튼을 누르세요.")
        else:
            self.displayLog(html.escape(f"케이스 저장: {saved['destination']} · 해당 과목/장/문제를 선택하면 채점할 수 있습니다."))

    def openMaker(self):
        from case_generator import TestMaker
        if hasattr(self, "maker") and self.maker.isVisible():
            self.maker.raise_()
            return
        self.maker = TestMaker()
        self.maker.show()

    def openMaterials(self):
        from materials import MaterialsWindow
        self.materials = MaterialsWindow()
        self.materials.show()

    def closeEvent(self, event):
        if (self.job and self.job.isRunning()) or not self.btnLoad.isEnabled():
            QMessageBox.information(self, '작업 진행 중', '현재 작업이 끝난 후 창을 닫아주세요.')
            event.ignore()
            return
        self.worker_thread.quit()
        self.worker_thread.wait()
        event.accept()

    def runManual(self):
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.submissionProblem()
        
        selected_items = self.listStudents.selectedItems()
        if not class_name or len(selected_items) != 1:
            QMessageBox.warning(self, '직접 실행', '‘선택 해제’를 누른 뒤 학생 한 명만 선택하세요. 여러 학생의 자동 채점은 ‘일괄 채점’을 사용하세요.')
            return

        student_id = selected_items[0].text()
        
        # Determine Mode
        mode = 'windows'
        if self.radioWSL.isChecked(): mode = 'wsl'
        elif self.radioDocker.isChecked(): mode = 'docker'
        elif self.radioLinux.isChecked(): mode = 'linux'
        if self.comboProblem.isHidden():
            problem = None
        
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
        if self.isMidterm():
            from midterm import TARGETS
            if not target_file and self.selectedProblem() in TARGETS:
                target_file = self.selectedProblem()
            if target_file and target_file.endswith('.c'):
                runner_config['sources'] = [target_file]
        
        input_data = self.txtManualInput.toPlainText()
        args_str = self.txtManualArgs.text()
        try:
            final_args = parse_args(args_str)
        except ValueError as exc:
            QMessageBox.warning(self, 'Arguments', str(exc))
            return
        
        # Auxiliary File Creation (Multiple)
        created_any = False
        for i in range(self.aux_tabs.count()):
            page = self.aux_tabs.widget(i)
            # Find widgets in the page layout
            # Note: We rely on type finding. Page has QLineEdit and QTextEdit.
            txt_name = page.findChild(QLineEdit)
            txt_content = page.findChild(QTextEdit)
            
            if txt_name and txt_content:
                aux_filename = txt_name.text().strip()
                aux_content = txt_content.toPlainText()
                
                if aux_filename:
                    success, msg = self.eval.create_file_from_string(class_name, student_id, chapter, problem, aux_filename, aux_content)
                    if success:
                        self.log_output.append(f"Created aux file: {aux_filename}")
                        created_any = True
                    else:
                        self.log_output.append(f"<span style='font-weight:600;'>Failed to create aux file {aux_filename}: {msg}</span>")

        msg = f"Running {target_file if target_file else 'Default'}..."
        if final_args:
             msg += f" with args: {final_args}"
        self.txtManualOutput.setPlainText(msg)
        self.txtManualOutput.repaint() # Force update
        
        def run(progress):
            evaluator = Evaluator()
            return evaluator.run_manual_code(class_name, student_id, runner_config, input_data, final_args, target_file)
        self.startJob(run, self.manualDone)
        if created_any:
            self.updateFileList()

    def manualDone(self, result):
        success, stdout, stderr = result
        self.txtManualOutput.setPlainText(f"[{'Finished' if success else 'Failed'}]\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}")
        self.updateFileList()

    def load(self):
        self.progress_bar.setValue(0)
        fname = QFileDialog.getOpenFileName(self, '저장소 동기화에 사용할 학생 명단 CSV 선택', '', '학생 명단 (*.csv)')
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
        
        self.btnLoad.setText("저장소 동기화 중…")
        self.setBusy(True)
        self.work_requested.emit(fname[0])

    def loadFinished(self, summary):
        if self.log_window:
            text = self.log_window.show_summary(summary)
            self.log_output.append(html.escape(text))
            for row in summary['results']:
                if not row['success']:
                    self.log_output.append(html.escape(f"실패: {row['name']} ({row['student_id']}) — {row['error']}"))

        self.btnLoad.setText("저장소 동기화")
        self.setBusy(False)
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
            formatted_message = f'<span style="font-weight:600;">{message}</span>'
        elif "pass" in message.lower():
             formatted_message = f'<span style="font-weight:600;">{message}</span>'
        else:
            formatted_message = message
        self.log_output.append(formatted_message)
