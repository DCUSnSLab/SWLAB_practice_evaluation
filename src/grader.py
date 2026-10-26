"""C/Python execution and reproducible, per-case grading."""
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from PyQt6.QtCore import QObject, pyqtSignal as Signal
from paths import safe_path, natural_key, parse_args


class Grader(QObject):
    log_message = Signal(str)
    OUTPUT_LIMIT = 1024 * 1024

    def to_wsl_path(self, path):
        path = str(Path(path).resolve())
        drive, tail = os.path.splitdrive(path)
        return '/mnt/' + drive[0].lower() + tail.replace('\\', '/')

    def _kill(self, process):
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait()

    def _execute(self, command, cwd, data, timeout):
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as stdin:
            stdin.write((data or '').encode('utf-8'))
            stdin.seek(0)
            process = subprocess.Popen(command, cwd=cwd, stdin=stdin,
                                       stdout=out, stderr=err, start_new_session=os.name != 'nt')
            timed_out = output_limit = False
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                output_limit = max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size) > self.OUTPUT_LIMIT
                timed_out = time.monotonic() >= deadline
                if timed_out or output_limit:
                    self._kill(process)
                    break
                time.sleep(.02)
            output_limit = output_limit or max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size) > self.OUTPUT_LIMIT
            out.seek(0)
            err.seek(0)
            stdout = out.read(self.OUTPUT_LIMIT).decode('utf-8', errors='replace').replace('\r\n', '\n')
            stderr = err.read(self.OUTPUT_LIMIT).decode('utf-8', errors='replace').replace('\r\n', '\n')
            return dict(stdout=stdout, stderr=stderr, returncode=process.returncode,
                        timed_out=timed_out, output_limit=output_limit)

    def execute(self, target_dir, input_data=None, args=None, runner_config=None, target_file=None):
        config = dict(runner_config or {})
        mode = 'wsl' if config.get('use_wsl') else config.get('mode', 'windows' if os.name == 'nt' else 'linux')
        target = Path(target_dir).resolve()
        error = dict(stdout='', stderr='', returncode=None, timed_out=False, output_limit=False)
        container = None
        executable = None
        try:
            timeout = float(config.get('timeout', 10))
            if not 0 < timeout <= 300:
                raise ValueError('Timeout must be between 0 and 300 seconds.')
            requested = target_file or config.get('target_file')
            if requested:
                source = safe_path(target, requested)
            else:
                candidates = [p for p in (target / 'main.py', target / 'main.c') if p.is_file()]
                if not candidates:
                    candidates = list(target.glob('*.py')) + list(target.glob('*.c'))
                if len(candidates) != 1:
                    raise ValueError('Select a source file (main.py/main.c missing or ambiguous).')
                source = candidates[0]
            if not source.is_file() or source.suffix not in ('.py', '.c'):
                raise ValueError(f'Source file not found or unsupported: {source.name}')
            relative = source.relative_to(target).as_posix()
            sources = config.get('sources') or [p.relative_to(target).as_posix() for p in sorted(source.parent.glob('*.c'))]
            for name in sources:
                if not safe_path(target, name).is_file():
                    raise ValueError(f'Source file not found: {name}')
            flags = config.get('cflags', ['-Wall', '-Wextra'])
            arguments = list(args or [])
            if not all(isinstance(a, str) for a in arguments + sources + flags):
                raise ValueError('Arguments, sources and cflags must be string lists.')
            binary_name = '.swlab-' + uuid.uuid4().hex + ('.exe' if mode == 'windows' else '')
            executable = target / binary_name
            if mode in ('docker', 'wsl'):
                script = ('python3 ' + shlex.quote(relative)) if source.suffix == '.py' else (
                    shlex.join(['gcc', *sources, *flags, '-o', binary_name]) + ' || { echo __SWLAB_COMPILE_ERROR__ >&2; exit 125; }; ' + shlex.quote('./' + binary_name))
                script += ' ' + shlex.join(arguments)
                if mode == 'docker':
                    container = 'swlab-run-' + uuid.uuid4().hex
                    command = ['docker', 'run', '-i', '--rm', '--init', '--name', container,
                               '--network', 'none', '--memory', '256m', '--cpus', '1',
                               '--pids-limit', '64', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                               '--ulimit', 'fsize=8388608:8388608', '--mount', f'type=bind,source={target},target=/work',
                               '--workdir', '/work', config.get('image', 'grader-image'),
                               'sh', '-c', script]
                else:
                    command = ['wsl', '--cd', self.to_wsl_path(target), '--', 'timeout', '-k', '1',
                               str(timeout), 'sh', '-c', script]
            elif mode in ('windows', 'linux'):
                if source.suffix == '.c':
                    compiled = self._execute(['gcc', *sources, *flags, '-o', str(executable)], target, '', min(timeout, 30))
                    if compiled['returncode'] != 0 or compiled['timed_out']:
                        compiled['stderr'] = 'Compilation failed: ' + compiled['stderr']
                        compiled['compile_error'] = True
                        return compiled
                    command = [str(executable), *arguments]
                else:
                    command = [sys.executable, str(source), *arguments]
            else:
                raise ValueError(f'Unknown execution environment: {mode}')
            result = self._execute(command, target, input_data, timeout + (2 if mode == 'wsl' else 0))
            if mode == 'docker' and result['returncode'] == 125 and result['stderr'].lstrip().lower().startswith('docker:'):
                result['returncode'] = None
            if '__SWLAB_COMPILE_ERROR__' in result['stderr'] and result['returncode'] == 125:
                result['compile_error'] = True
                result['stderr'] = result['stderr'].replace('__SWLAB_COMPILE_ERROR__', '').strip()
            if mode == 'wsl' and result['returncode'] == 124:
                result['timed_out'] = True
            return result
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
            error['stderr'] = str(exc)
            return error
        finally:
            if container:
                try:
                    subprocess.run(['docker', 'rm', '-f', container], capture_output=True, timeout=15)
                except (OSError, subprocess.SubprocessError):
                    pass
            if executable and executable.exists():
                executable.unlink(missing_ok=True)

    def run_code(self, target_dir, input_data=None, args=None, runner_config=None, target_file=None):
        result = self.execute(target_dir, input_data, args, runner_config, target_file)
        message = result['stderr']
        if result['timed_out']:
            message += '\nExecution timed out.'
        if result['output_limit']:
            message += '\nOutput limit exceeded.'
        success = result['returncode'] == 0 and not result['timed_out'] and not result['output_limit']
        return success, result['stdout'], message

    def check_result(self, actual, expected, comparison='trim', tolerance=1e-6):
        actual = (actual or '').replace('\r\n', '\n')
        expected = (expected or '').replace('\r\n', '\n')
        if comparison == 'exact':
            return actual == expected
        if comparison == 'tokens':
            return actual.split() == expected.split()
        if comparison == 'numeric':
            try:
                left, right = [float(x) for x in actual.split()], [float(x) for x in expected.split()]
                return bool(right) and len(left) == len(right) and all(
                    math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance
                    for a, b in zip(left, right))
            except ValueError:
                return False
        if comparison == 'regex':
            return re.fullmatch(expected, actual, re.DOTALL) is not None
        if comparison != 'trim':
            raise ValueError(f'Unknown comparison: {comparison}')
        return actual.strip() == expected.strip()

    def load_test_cases(self, test_case_dir):
        root = Path(test_case_dir)
        if not root.is_dir():
            return []
        cases = []
        for folder in [root, *sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: natural_key(p.name))]:
            metadata = folder / 'case.json'
            if not (folder / 'output.txt').is_file() and not metadata.is_file():
                continue
            config = json.loads(metadata.read_text(encoding='utf-8-sig')) if metadata.is_file() else {}
            if not isinstance(config, dict):
                raise ValueError(f'{metadata}: expected a JSON object')
            if config.get('enabled', True) is False:
                continue
            def read(name, default=None):
                path = folder / name
                return path.read_text(encoding='utf-8-sig') if path.is_file() else default
            cases.append({**config, 'name': config.get('name', 'Default' if folder == root else folder.name),
                          'path': str(folder), 'input': read('input.txt', ''),
                          'args': config['args'] if 'args' in config else parse_args(read('args.txt', '')),
                          'expected': read('output.txt', config.get('expected'))})
        return cases

    def grade_student(self, student_path, test_cases, runner_config=None):
        config = dict(runner_config or {})
        target = safe_path(student_path, config.get('chapter'), config.get('problem'))
        if not target.is_dir():
            return [{'case': 'Setup', 'passed': False, 'status': 'missing', 'message': f'Directory not found: {target}'}]
        if not test_cases:
            return [{'case': 'Setup', 'passed': False, 'status': 'no_tests', 'message': 'No enabled test cases found.'}]
        results = []
        for case in test_cases:
            started = time.monotonic()
            row = {'case': case['name'], 'passed': False, 'status': 'error',
                   'case_path': case.get('path'),
                   'expected_stderr': case.get('stderr'), 'expected_returncode': case.get('exit_code', 0),
                   'comparison': case.get('comparison', 'trim'), 'tolerance': case.get('tolerance', 1e-6)}
            try:
                with tempfile.TemporaryDirectory(prefix='swlab-case-') as temp:
                    work = Path(temp) / 'work'
                    for link in target.rglob('*'):
                        if link.is_symlink() and not link.resolve().is_relative_to(target):
                            raise ValueError(f'External submission symlink is not supported: {link.name}')
                    shutil.copytree(target, work, ignore=shutil.ignore_patterns('.git', '__pycache__'))
                    # A stale result in the submission must not satisfy a file assertion.
                    # Explicit fixture files are applied afterwards to test overwrite behavior.
                    for filename in case.get('files', {}):
                        stale = safe_path(work, filename)
                        if stale.is_file():
                            stale.unlink()
                    if case.get('path'):
                        fixture = safe_path(case['path'], case.get('fixture_root'))
                        for entry in fixture.iterdir():
                            if not case.get('fixture_root') and entry.name in ('input.txt', 'output.txt', 'args.txt', 'case.json', 'expected_files'):
                                continue
                            destination = safe_path(work, entry.name)
                            if entry.is_dir():
                                shutil.copytree(entry, destination, dirs_exist_ok=True)
                            else:
                                shutil.copy2(entry, destination)
                    run_config = {**config, **{k: case[k] for k in ('timeout', 'target_file', 'sources', 'cflags') if k in case}}
                    run = self.execute(work, case.get('input'), case.get('args'), run_config)
                    row.update(actual=run['stdout'], expected=case.get('expected'), stderr=run['stderr'], returncode=run['returncode'])
                    if run['timed_out']:
                        row.update(status='timeout', message='Execution timed out.')
                    elif run['output_limit']:
                        row.update(status='output_limit', message='Output limit exceeded.')
                    elif run.get('compile_error'):
                        row.update(status='compile_error', message=run['stderr'])
                    elif run['returncode'] is None:
                        row.update(status='error', message=run['stderr'])
                    elif run['returncode'] != case.get('exit_code', 0):
                        row.update(status='runtime_error', message=f"Exit code {run['returncode']}: {run['stderr']}")
                    else:
                        checks = []
                        if case.get('expected') is not None:
                            checks.append(self.check_result(run['stdout'], case['expected'], case.get('comparison', 'trim'), case.get('tolerance', 1e-6)))
                        if 'stderr' in case:
                            checks.append(self.check_result(run['stderr'], case['stderr'], case.get('stderr_comparison', 'trim')))
                        files = {}
                        file_results = {}
                        for filename, expected in case.get('files', {}).items():
                            actual_file = safe_path(work, filename)
                            # Bound result-file reads as well as stdout/stderr.
                            actual = None
                            oversized = actual_file.is_file() and actual_file.stat().st_size > self.OUTPUT_LIMIT
                            if actual_file.is_file() and not oversized:
                                actual = actual_file.read_text(encoding='utf-8', errors='replace')
                            files[filename] = actual is not None and self.check_result(actual, expected, case.get('file_comparison', 'exact'))
                            file_results[filename] = {'actual': actual, 'expected': expected, 'passed': files[filename], 'output_limit': oversized}
                        row['files'] = files
                        row['file_results'] = file_results
                        checks.extend(files.values())
                        if not checks:
                            raise ValueError('Case has no output, stderr or file assertion.')
                        passed = all(checks)
                        row.update(passed=passed, status='passed' if passed else 'wrong_answer')
            except (OSError, ValueError, TypeError, re.error) as exc:
                row['message'] = str(exc)
            row['duration_ms'] = round((time.monotonic() - started) * 1000)
            results.append(row)
        return results
