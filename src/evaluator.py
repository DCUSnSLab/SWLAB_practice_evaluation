from lecture import Lecture
from student import Student
import csv
import re
import os
from PyQt6.QtCore import QObject, pyqtSignal as Signal
from grader import Grader

class Evaluator(QObject):
    progress_status = Signal(int)
    max_value = Signal(int)
    log_message = Signal(str)
    grade_finished = Signal(str, list) # student_path, results

    def __init__(self):
        super().__init__()
        self.id = 0
        self.max = 0
        self.grader = Grader()
        self.grader.log_message.connect(self.log_message.emit)

    def loadfile(self,file):
        #lecture = self.getDatafromCSV('../testdata/python01.csv', Lecture(0, 'python', 1))
        #lecture.syncCodefromLecture()

        # lecture2 = self.getDatafromCSV('../testdata/python02_test.csv', Lecture(1, 'python', 2))
        # #self.insertIntoDB(lecture2)
        # lecture2.syncCodefromLecture()
        
        # Extract year from path (parent directory)
        # file path example: .../testdata/2025/python_test_2.csv
        file_path = os.path.abspath(file)
        parent_dir = os.path.dirname(file_path)
        dir_name = os.path.basename(parent_dir)
        
        try:
            year = int(dir_name)
        except ValueError:
            year = 2025 # Default fallback
            
        division = int(re.findall(r'\d+', file)[-1])
        if file.find('python') != -1 :
            lecture = self.getDatafromCSV(file, Lecture(year, 'python', division))
        elif file.find('system') != -1 :
            lecture = self.getDatafromCSV(file, Lecture(year, 'system', division))
        else :
            lecture = self.getDatafromCSV(file, Lecture(year, '?', division))
        lecture.log_message.connect(self.log_message.emit)
        lecture.syncCodefromLecture(self.progress_status)

    def filterString(self, data):
        return re.sub(r'[^0-9]', '', data)

    def getDatafromCSV(self, path, lecture:Lecture):
        f = open(path, 'r', encoding='utf-8')
        rdr = csv.reader(f)
        for line in rdr:
            sid = self.filterString(line[0])
            s = Student(int(sid), name=line[1], sid=int(sid))
            s.insertGithubLink(lecture, line[2])
            lecture.addStudent(s)
            self.max += 1
        f.close()
        self.max_value.emit(self.max)
        return lecture

    def insertIntoDB(self, lecture:Lecture):
        print('insert db')
        self.db.insertLecture(lecture)
        for std in lecture.getStudentList():
            self.db.insertStudent(lecture, std)
        #database.insertLecture(lecture)

    def get_year_list(self):
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        if not os.path.exists(origin_path):
            return []
        
        years = set()
        for entry in os.listdir(origin_path):
            full_path = os.path.join(origin_path, entry)
            if os.path.isdir(full_path):
                # Format: Name_Div_Year e.g., python_2_2025
                parts = entry.split('_')
                if len(parts) >= 3:
                     # Assume last part is year
                     try:
                         year = int(parts[-1])
                         years.add(str(year))
                     except ValueError:
                         pass
        return sorted(list(years), reverse=True)

    def get_classes_by_year(self, year):
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        if not os.path.exists(origin_path):
            return []
        
        classes = []
        for entry in os.listdir(origin_path):
            full_path = os.path.join(origin_path, entry)
            if os.path.isdir(full_path):
                # Check if folder ends with _year
                if entry.endswith(f"_{year}"):
                    # Return Name_Div (remove _year for display? No, keeping folder name is easier for now, wait user asked for "수업_분반")
                    # User asked: "Selete Class에 고를 수 있는 선택지를 년도, 수업_분반 으로 바꿔줘."
                    # So I should return the folder name, but maybe process it in GUI or here?
                    # Let's return the full folder name here so logic is simple, and format it in GUI if needed.
                    # Or better, return full folder name, and GUI displays substring.
                    classes.append(entry)
        return sorted(classes)


    def get_student_list(self, class_name):
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        class_path = os.path.join(origin_path, class_name)
        if not os.path.exists(class_path):
            return []
        
        students = []
        for entry in os.listdir(class_path):
            full_path = os.path.join(class_path, entry)
            if os.path.isdir(full_path):
                students.append(entry)
        return sorted(students)
    
    def get_chapters(self, class_name):
        # Look in testdata for chapters
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        test_data_path = os.path.join(base_dir, 'testdata', class_name)
        
        if not os.path.exists(test_data_path):
            return []
        
        chapters = []
        for entry in os.listdir(test_data_path):
            full_path = os.path.join(test_data_path, entry)
            if os.path.isdir(full_path) and entry != 'testcases': # Exclude legacy 'testcases' folder if present? Or Treat as chapter?
                # Actually, legacy tests were in 'testcases'. If we move to hierarchy, 'testcases' shouldn't be a chapter.
                # Let's assume chapters don't start with '.', and maybe filter out 'testcases' if it's the old structure.
                if entry not in ['testcases', '__pycache__']:
                    chapters.append(entry)
        return sorted(chapters)

    def get_problems(self, class_name, chapter):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        chapter_path = os.path.join(base_dir, 'testdata', class_name, chapter)
        
        if not os.path.exists(chapter_path):
            return []
        
        problems = []
        for entry in os.listdir(chapter_path):
            full_path = os.path.join(chapter_path, entry)
            if os.path.isdir(full_path):
                 problems.append(entry)
        return sorted(problems)

    def get_student_chapters(self, class_name, student_id):
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        student_path = os.path.join(origin_path, class_name, student_id)
        
        if not os.path.exists(student_path):
            return []
        
        chapters = []
        for entry in os.listdir(student_path):
            full_path = os.path.join(student_path, entry)
            if os.path.isdir(full_path):
                if entry not in ['.git', '__pycache__']:
                    chapters.append(entry)
        return sorted(chapters)

    def get_student_problems(self, class_name, student_id, chapter):
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        chapter_path = os.path.join(origin_path, class_name, student_id, chapter)
        
        if not os.path.exists(chapter_path):
            return []
        
        problems = []
        for entry in os.listdir(chapter_path):
            full_path = os.path.join(chapter_path, entry)
            if os.path.isdir(full_path):
                if entry not in ['__pycache__']:
                     problems.append(entry)
        return sorted(problems)

    def get_student_files(self, class_name, student_id, chapter, problem=None):
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        target_path = os.path.join(origin_path, class_name, student_id, chapter)
        if problem:
            target_path = os.path.join(target_path, problem)
            
        if not os.path.exists(target_path):
            return []
            
        files = []
        for entry in os.listdir(target_path):
            full_path = os.path.join(target_path, entry)
            if os.path.isfile(full_path):
                files.append(entry)
        return sorted(files)

    def start_grading(self, class_name, student_id, test_case_dir, runner_config=None): # Updated signature
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        student_path = os.path.join(origin_path, class_name, student_id)
        
        self.log_message.emit(f"Loading test cases from {test_case_dir}")
        test_cases = self.grader.load_test_cases(test_case_dir)
        
        if not test_cases:
            self.log_message.emit("No test cases found.")
            return

        self.log_message.emit(f"Grading student {student_id}...")
        # Note: We need to pass runner_config to grade_student, but Grader isn't updated yet.
        # For now, keep old call until Grader is updated.
        if runner_config:
             results = self.grader.grade_student(student_path, test_cases, runner_config)
        else:
             results = self.grader.grade_student(student_path, test_cases)
             
        self.grade_finished.emit(student_path, results)
        
        pass_count = sum(1 for r in results if r['passed'])
        self.log_message.emit(f"Result: {pass_count}/{len(results)} passed")
        
        for r in results:
            status = "Pass" if r['passed'] else "Fail"
            
            def trunc(s, l=300):
                if s and len(s) > l: return s[:l] + "..."
                return s if s else "None/Empty"

            # Build rich log message
            log_str = f" - <b>{r['case']}</b>: "
            if r['passed']:
                 log_str += f"<span style='color:blue;'>{status}</span>"
            else:
                 log_str += f"<span style='color:red;'>{status}</span>"
            
            if 'message' in r and not r['passed'] and 'actual' not in r:
                # Execution error (compile fail etc)
                log_str += f"<br>&nbsp;&nbsp;Error: {r['message']}"
            else:
                 # Normal execution (even if failed logic)
                 # Show output for both pass (user asked) and fail
                 log_str += f"<br>&nbsp;&nbsp;Output: {trunc(r.get('actual'))}"
                 if not r['passed']:
                      log_str += f"<br>&nbsp;&nbsp;Expected: {trunc(r.get('expected'))}"
            
            self.log_message.emit(log_str)

    def run_manual_code(self, class_name, student_id, runner_config, input_data, target_file=None):
        origin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'origin')
        target_dir = os.path.join(origin_path, class_name, student_id)
        
        if runner_config:
            chap = runner_config.get('chapter')
            prob = runner_config.get('problem')
            if chap: target_dir = os.path.join(target_dir, chap)
            if prob: target_dir = os.path.join(target_dir, prob)
            
        if not os.path.exists(target_dir):
            return False, "", f"Directory not found: {target_dir}"
            
        return self.grader.run_code(target_dir, input_data, [], runner_config, target_file=target_file)