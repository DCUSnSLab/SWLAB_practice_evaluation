import subprocess
import os
import shutil
import tempfile
from PyQt6.QtCore import QObject, pyqtSignal as Signal

class Grader(QObject):
    log_message = Signal(str)

    def __init__(self):
        super().__init__()

    def to_wsl_path(self, win_path):
        """
        Converts a Windows path to a WSL path.
        C:\dev\test -> /mnt/c/dev/test
        """
        win_path = os.path.abspath(win_path)
        drive, tail = os.path.splitdrive(win_path)
        drive_letter = drive[0].lower()
        wsl_path = f"/mnt/{drive_letter}" + tail.replace("\\", "/")
        return wsl_path

    def to_docker_path(self, win_path):
        """
        Converts a Windows path to a Docker container path.
        Assumes C:\dev\SWLAB_practice_evaluation is mounted to /app
        """
        win_path = os.path.abspath(win_path)
        # Find project root (2 levels up from src/grader.py)
        src_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(src_dir)
        
        rel_path = os.path.relpath(win_path, project_root)
        # Join with /app
        docker_path = "/app/" + rel_path.replace("\\", "/")
        return docker_path.replace("//", "/")

    def run_code(self, target_dir, input_data=None, args=[], runner_config=None, target_file=None):
        """
        Executes code in target_dir.
        Detects main.py or main.c, or uses target_file if provided.
        """
        mode = runner_config.get('mode', 'windows')
        if runner_config and runner_config.get('use_wsl', False):
            mode = 'wsl'
        
        use_wsl = (mode == 'wsl')
        
        # Default files
        current_py = os.path.join(target_dir, 'main.py')
        current_c = os.path.join(target_dir, 'main.c')
        
        # Override if specific file requested
        if target_file:
            tf_path = os.path.join(target_dir, target_file)
            if target_file.endswith('.py'):
                current_py = tf_path
                current_c = ""
            elif target_file.endswith('.c'):
                current_c = tf_path
                current_py = ""
        
        cmd = []
        cleanup_file = None
        
        # Determine Language
        lang = None
        target_filename = "" # basename
        
        if os.path.exists(current_py):
            lang = 'python'
            target_filename = os.path.basename(current_py)
        elif os.path.exists(current_c):
            lang = 'c'
            target_filename = os.path.basename(current_c)
        else:
            return False, f"Source file not found (Target: {target_file if target_file else 'main.py/c'})", ""

        if mode == 'docker':
            # Persistent Docker Execution (using 'grader-container')
            docker_dir = self.to_docker_path(target_dir)
            
            # Base command: docker exec -i --workdir <dir> grader-container ...
            base_cmd = ['docker', 'exec', '-i', '--workdir', docker_dir, 'grader-container']
            
            if lang == 'python':
                cmd = base_cmd + ['python3', target_filename] + args
            elif lang == 'c':
                # Compile ALL .c files in the directory to handle dependencies (linking)
                # This fixes 'undefined reference' errors if helper functions are in other files.
                shell_cmd = "gcc -o main *.c && ./main"
                if args:
                    shell_cmd += " " + " ".join(args)
                cmd = base_cmd + ['sh', '-c', shell_cmd]

        elif mode == 'wsl':
            # WSL Execution
            wsl_dir = self.to_wsl_path(target_dir)
            
            if lang == 'python':
                cmd = ['wsl', 'python3', f"{wsl_dir}/{target_filename}"] + args
            elif lang == 'c':
                # Compile *.c
                wsl_out = f"{wsl_dir}/main"
                # Use bash -c to expand wildcard *.c
                compile_cmd = ['wsl', 'bash', '-c', f'gcc -o {wsl_out} {wsl_dir}/*.c']
                try:
                    subprocess.run(compile_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                except subprocess.CalledProcessError as e:
                    return False, "", f"Compilation Failed (WSL):\n{e.stderr.decode('utf-8')}"
                
                cmd = ['wsl', wsl_out] + args
        
        else: # Windows (Default)
            if lang == 'python':
                cmd = ['python', current_py] + args
            elif lang == 'c':
                 exe_out = os.path.join(target_dir, 'main.exe')
                 # Use shell=True for wildcard expansion on Windows
                 compile_txt = f'gcc -o "{exe_out}" "{target_dir}\\*.c"'
                 try:
                    subprocess.run(compile_txt, check=True, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    cleanup_file = exe_out
                    cmd = [exe_out] + args
                 except FileNotFoundError:
                     return False, "", "GCC not found on Windows PATH."
                 except subprocess.CalledProcessError as e:
                     return False, "", f"Compilation Failed (Win):\n{e.stderr.decode('utf-8', errors='ignore')}"

        # Execution
        # Execution
        t_out = tempfile.TemporaryFile()
        t_err = tempfile.TemporaryFile()

        try:
            # Popen with temp files
            # Note: text=False (binary) to handle buffering safely manually
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=t_out,
                stderr=t_err,
                cwd=target_dir if not use_wsl else None
            )
            
            # Write input
            try:
                if input_data:
                    process.stdin.write(input_data.encode('utf-8'))
                process.stdin.close()
            except Exception:
                pass # Stdin might be broken if process exited immediately
            
            process.wait(timeout=10) # 10s timeout
            
            t_out.seek(0)
            t_err.seek(0)
            
            # Limit output to 1MB prevents crash
            stdout_bytes = t_out.read(1024 * 1024)
            stderr_bytes = t_err.read(1024 * 1024)
            
            stdout = stdout_bytes.decode('utf-8', errors='replace')
            stderr = stderr_bytes.decode('utf-8', errors='replace')
            
            if cleanup_file and os.path.exists(cleanup_file):
                try: os.remove(cleanup_file)
                except: pass

            if process.returncode != 0:
                return False, stdout, stderr
            
            return True, stdout, stderr

        except subprocess.TimeoutExpired:
            process.kill()
            t_out.seek(0)
            t_err.seek(0)
            stdout = t_out.read(1024*1024).decode('utf-8', errors='replace') + "\n[Timeout Truncated]"
            stderr = t_err.read(1024*1024).decode('utf-8', errors='replace')
            
            if cleanup_file and os.path.exists(cleanup_file):
                try: os.remove(cleanup_file)
                except: pass
            return False, stdout, stderr # Return what we have
        
        except Exception as e:
            if cleanup_file and os.path.exists(cleanup_file):
                try: os.remove(cleanup_file)
                except: pass
            return False, "", str(e)
            
        finally:
            t_out.close()
            t_err.close()

    def check_result(self, actual, expected):
        if actual is None: actual = ""
        if expected is None: expected = ""
        # Normalize newlines
        actual = actual.replace('\r\n', '\n').strip()
        expected = expected.replace('\r\n', '\n').strip()
        return actual == expected

    def load_test_cases(self, test_case_dir):
        cases = []
        if not os.path.exists(test_case_dir):
            return cases

        # 1. Check for flat structure (files directly in folder)
        root_output = os.path.join(test_case_dir, 'output.txt')
        if os.path.exists(root_output):
            input_file = os.path.join(test_case_dir, 'input.txt')
            args_file = os.path.join(test_case_dir, 'args.txt')

            input_data = None
            if os.path.exists(input_file):
                with open(input_file, 'r', encoding='utf-8') as f:
                    input_data = f.read()

            args = []
            if os.path.exists(args_file):
                with open(args_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    args = content.split()

            with open(root_output, 'r', encoding='utf-8') as f:
                expected_output = f.read()

            cases.append({
                'name': 'Default',
                'path': test_case_dir,
                'input': input_data,
                'args': args,
                'expected': expected_output
            })

        # 2. Check for subdirectories
        for case_name in os.listdir(test_case_dir):
            case_path = os.path.join(test_case_dir, case_name)
            if os.path.isdir(case_path):
                input_file = os.path.join(case_path, 'input.txt')
                args_file = os.path.join(case_path, 'args.txt')
                output_file = os.path.join(case_path, 'output.txt')

                if not os.path.exists(output_file):
                    continue

                input_data = None
                if os.path.exists(input_file):
                    with open(input_file, 'r', encoding='utf-8') as f:
                        input_data = f.read()

                args = []
                if os.path.exists(args_file):
                    with open(args_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        args = content.split()

                with open(output_file, 'r', encoding='utf-8') as f:
                    expected_output = f.read()

                cases.append({
                    'name': case_name,
                    'path': case_path,
                    'input': input_data,
                    'args': args,
                    'expected': expected_output
                })
        return cases

    def grade_student(self, student_path, test_cases, runner_config=None):
        results = []
        
        # Determine target directory (Student Root + Chapter + Problem)
        target_dir = student_path
        if runner_config:
            chap = runner_config.get('chapter')
            prob = runner_config.get('problem')
            if chap: target_dir = os.path.join(target_dir, chap)
            if prob: target_dir = os.path.join(target_dir, prob)
        
        if not os.path.exists(target_dir):
             return [{'case': 'Setup', 'passed': False, 'message': f"Directory not found: {target_dir}"}]

        for case in test_cases:
            # Copy auxiliary files (e.g. data files for cat command)
            copied_files = []
            if 'path' in case:
                for f in os.listdir(case['path']):
                    if f not in ['input.txt', 'output.txt', 'args.txt']:
                        src_f = os.path.join(case['path'], f)
                        dst_f = os.path.join(target_dir, f)
                        if os.path.isfile(src_f):
                            try:
                                shutil.copy(src_f, dst_f)
                                copied_files.append(dst_f)
                            except: pass

            success, stdout, stderr = self.run_code(target_dir, case['input'], case['args'], runner_config)
            
            # Cleanup auxiliary files
            for f in copied_files:
                try: os.remove(f)
                except: pass
            
            if not success:
                results.append({
                    'case': case['name'],
                    'passed': False,
                    'message': f"Execution Failed: {stderr if stderr else 'Unknown Error'}"
                })
                continue

            passed = self.check_result(stdout, case['expected'])
            results.append({
                'case': case['name'],
                'passed': passed,
                'actual': stdout,
                'expected': case['expected']
            })
            
        return results
