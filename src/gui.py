import subprocess
import html
from paths import case_path, parse_args
from reports import save_report, CaseReport, summarize_cases
from pathlib import Path

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
            self.comboProblem.addItem(f"{row['name']} · {status}", row['name'])
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

    def onProblemChanged(self):
        self.updateTestCasePath()
        self.updateFileList()

    def updateFileList(self):
        self.listFiles.clear()
        self.txtCodePreview.clear() # Clear preview on list update
        
        class_name = self.comboClass.currentData()
        chapter = self.comboChapter.currentText()
        problem = self.selectedProblem()
        
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
        problem = self.selectedProblem()
        
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
        self.txtTestCasePath.setText(str(case_path(class_name, chapter, problem)) if class_name and chapter else '')

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
        problem = self.selectedProblem()
        
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
        problem = self.selectedProblem()
        
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
            'problem': problem
        }

        self.log_output.append("<b>Starting Grading...</b>")
        self.log_output.append(f"<i>Environment: {mode.upper()}</i>")

        students = [item.text() for item in selected_items]
        if self.comboProblem.isHidden():
            runner_config['problem'] = None
        try:
            from grader import Grader
            cases = Grader().load_test_cases(test_case_dir)
            if not cases:
                raise ValueError('활성 케이스가 없습니다. AI 케이스 생성에서 검토 완료로 저장하거나 케이스 폴더를 확인하세요.')
            report = CaseReport({'class_name': class_name, 'chapter': chapter, 'problem': runner_config['problem'],
                                 'mode': mode, 'students': students, 'case_count': len(cases),
                                 'case_directory': str(Path(test_case_dir).resolve()), 'cases': cases})
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '채점 준비 실패', str(exc))
            return
        self.case_report = report
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
                        results = grader.grade_student(ORIGIN / class_name / student, cases, runner_config)
                    except Exception as exc:
                        results = [{'case': 'Setup', 'passed': False, 'status': 'error', 'message': str(exc)}]
                    for result in results:
                        rows.append(dict(result, class_name=class_name, student=student, chapter=chapter, problem=runner_config['problem']))
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
                       self.radioWin, self.radioLinux, self.radioDocker, self.radioWSL):
            widget.setEnabled(not busy)
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
            problem = self.selectedProblem() if not self.comboProblem.isHidden() else ''
            mode = 'Docker' if self.radioDocker.isChecked() else ('WSL' if self.radioWSL.isChecked() else ('Linux' if self.radioLinux.isChecked() else 'Windows'))
            self.batchSummary.setText(f'{self.comboClass.currentText()} · {self.comboChapter.currentText()} {problem} · 학생 {count}명 × 케이스 {self.active_case_count}개 · {mode}')

    def stopGrading(self):
        if self.grading_active and self.job and self.job.isRunning():
            self.job.requestInterruption()
            self.btnStop.setEnabled(False)
            self.resultHeadline.setText('현재 학생의 결과를 저장한 뒤 중지합니다. 완료한 결과는 유지됩니다.')

    def onGradingProgress(self, index):
        if self.case_report:
            try:
                _, saved = CaseReport.open(self.case_report.directory / 'run.json')
                self.results = saved['results']
                self.refreshResultsTable()
                self.resultHeadline.setText(f"{index} / {len(self.case_report.context['students'])}명 완료 · 결과 자동 저장 중")
            except (OSError, ValueError) as exc:
                self.displayLog(html.escape(str(exc)))

    def finishGrading(self):
        self.grading_active = False
        self.btnStop.setEnabled(False)

    def gradingFailed(self, message):
        self.onGradingProgress(self.progress_bar.value())
        self.resultHeadline.setText('채점 중단: ' + message)

    def refreshResultsTable(self):
        context = self.case_report.context if self.case_report else {}
        summaries = summarize_cases(self.results, context.get('students'), context.get('case_count', 0),
                                    self.case_report.state if self.case_report else 'completed')
        selected = self.resultTable.currentRow()
        self.resultTable.blockSignals(True)
        self.resultTable.setRowCount(len(summaries))
        labels = {'pending': '대기', 'not_run': '미실행', 'ungraded': '채점 불가', 'manual_review': '수동 검토'}
        for index, summary in enumerate(summaries):
            passed, total = summary['passed_cases'], summary['total_cases']
            status = labels.get(summary['status'], '모두 통과' if passed == total else '오답 있음')
            symbol = '—'
            if summary['status'] == 'graded' and total > 0:
                symbol = 'O' if passed == total else ('△' if passed else 'X')
            values = [summary['student'], status, symbol, '—' if passed is None else f'{passed} / {total}',
                      '—' if passed is None else str(total - passed)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    font = item.font(); font.setBold(True); item.setFont(font)
                    item.setToolTip({'O': '통과: 모든 케이스를 통과했습니다.',
                                     '△': '부족: 일부 케이스만 통과했습니다.',
                                     'X': '오답: 통과한 케이스가 없습니다.',
                                     '—': '아직 판정할 수 없습니다. 판정 열과 상세 근거를 확인하세요.'}[symbol])
                self.resultTable.setItem(index, column, item)
        self.resultTable.blockSignals(False)
        if selected >= 0 and selected < len(summaries):
            self.resultTable.selectRow(selected)
            self.showResultDetails()

    def showResultDetails(self):
        index = self.resultTable.currentRow()
        if index < 0 or self.resultTable.item(index, 0) is None:
            return
        student = self.resultTable.item(index, 0).text()
        lines = [f'학생 {student} · 케이스별 상세 결과']
        labels = {'passed': '통과', 'wrong_answer': '오답', 'compile_error': '컴파일 오류',
                  'runtime_error': '실행 오류', 'timeout': '시간 초과', 'output_limit': '출력 제한 초과',
                  'missing': '제출 경로 없음', 'error': '채점 오류', 'no_tests': '케이스 없음'}
        for row in self.results:
            if row['student'] != student:
                continue
            lines.extend(['', f"[{row['case']}] {labels.get(row['status'], row['status'])}"])
            if row.get('message'): lines.append(row['message'])
            if row.get('expected') is not None: lines.extend(['기대 출력:', row['expected']])
            if row.get('actual') is not None: lines.extend(['실제 출력:', row['actual']])
            if row.get('stderr'): lines.extend(['오류 출력:', row['stderr']])
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
                self.log_output.append('<pre>Expected: ' + html.escape(row['expected']) + '</pre>')
            if row.get('files'):
                self.log_output.append(html.escape(str(row['files'])))
        self.log_output.append(f"Finished: {sum(r['passed'] for r in rows)}/{len(rows)} passed")
        labels = {'graded': '판정 완료', 'ungraded': '채점 불가', 'not_run': '미실행', 'pending': '대기', 'manual_review': '수동 검토'}
        for summary in summarize_cases(rows):
            count = '점수 없음' if summary['passed_cases'] is None else f"{summary['passed_cases']}/{summary['total_cases']} 케이스 통과"
            self.log_output.append(html.escape(f"{summary['student']}: {labels[summary['status']]} · {count}"))
        if self.case_report:
            self.showReportLocation()
            self.log_output.append(html.escape(f'자동 저장: {self.case_report.directory}'))

    def refreshCaseInfo(self):
        from grader import Grader
        try:
            cases = Grader().load_test_cases(self.txtTestCasePath.text()) if self.txtTestCasePath.text() else []
            self.active_case_count = len(cases)
            self.case_info.setText(f'활성 케이스 {len(cases)}개 · 초안은 제외됩니다.' if cases else '활성 케이스 없음 · AI 케이스를 생성하거나 케이스 폴더를 선택하세요.')
        except (OSError, ValueError) as exc:
            self.active_case_count = 0
            self.case_info.setText('케이스 확인 오류: ' + str(exc))
        self.updateSelectionSummary()

    def showReportLocation(self):
        self.report_location.setText(f'자동 저장: {self.case_report.directory}')
        self.report_location.setCursorPosition(0)
        self.report_location.setToolTip(f'{self.case_report.directory}\nrun.json: 전체 근거 · cases.csv: 케이스별 판정 · summary.csv: 학생별 통과 수')
        self.btnOpenReport.setEnabled(True)

    def openReportFolder(self):
        if self.case_report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.case_report.directory)))

    def readCaseReport(self):
        from paths import ROOT
        path, _ = QFileDialog.getOpenFileName(self, '저장된 채점 결과', str(ROOT / 'reports' / 'case-grading'), '채점 기록 (run.json)')
        if path:
            try:
                self.case_report, document = CaseReport.open(path)
                self.log_output.clear()
                self.gradingDone(document['results'])
                self.log_output.append(html.escape('저장된 실행 상태: ' + str(document.get('state'))))
                if document.get('error'):
                    self.log_output.append(html.escape(document['error']))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, '기록 열기 실패', str(exc))

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
        for student in students:
            self.results.append({'class_name': self.comboClass.currentData(), 'student': student, 'chapter': self.comboChapter.currentText(),
                                 'problem': self.selectedProblem(), 'case': 'Manual review',
                                 'passed': passed, 'status': 'manual_passed' if passed else 'manual_failed',
                                 'message': notes.toPlainText()})
        try:
            if self.case_report is None:
                self.case_report = CaseReport({**context, 'students': students, 'case_count': 0})
                self.case_report.state = 'completed'
            self.case_report.save(self.results, self.case_report.state)
            self.showReportLocation()
            self.displayLog(f'수동 평가 {len(students)}건 자동 저장.')
        except OSError as exc:
            self.displayLog('저장 실패: ' + html.escape(str(exc)))

    def exportResults(self):
        if not self.results:
            QMessageBox.information(self, 'Export', 'Run grading first.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export results', 'results.csv', 'CSV (*.csv);;JSON (*.json)')
        if path:
            try:
                save_report(path, self.results)
            except OSError as exc:
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
        if hasattr(self, 'qualitative_window') and self.qualitative_window.isVisible():
            self.qualitative_window.raise_()
            return
        chapter = self.comboChapter.currentText()
        problem = None if self.comboProblem.isHidden() else self.selectedProblem()
        if not chapter or chapter == '(No Files)':
            QMessageBox.information(self, '정성평가', '평가할 장과 문제를 선택하세요.')
            return
        submissions = [dict(class_name=class_name, student=item.text(), chapter=chapter, problem=problem,
                       path=str(safe_path(ORIGIN, class_name, item.text(), chapter, problem))) for item in selected]
        self.qualitative_window = QualitativeWindow(submissions)
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
        problem = self.selectedProblem()
        
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
