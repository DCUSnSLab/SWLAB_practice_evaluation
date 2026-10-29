import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401  isolates the SQLite store
from grader import Grader
from paths import parse_args, safe_path, case_path
from evaluator import Evaluator
from lecture import Lecture
from reports import save_report


class GradingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.student = self.root / 'student'
        self.student.mkdir()
        self.grader = Grader()

    def tearDown(self):
        self.temp.cleanup()

    def source(self, text, name='main.py'):
        (self.student / name).write_text(text, encoding='utf-8')

    def test_default_runner_input_and_quoted_args(self):
        self.source('import sys; print(input()); print(sys.argv[1])')
        ok, out, err = self.grader.run_code(self.student, 'hello\n', ['two words'])
        self.assertTrue(ok, err)
        self.assertEqual(out, 'hello\ntwo words\n')

    def test_case_isolation_and_file_assertions(self):
        self.source("from pathlib import Path; p=Path('data.txt'); print(p.read_text()); p.write_text('changed'); Path('result.txt').write_text('done')")
        (self.student / 'data.txt').write_text('original')
        fixture = self.root / 'case'
        fixture.mkdir()
        (fixture / 'data.txt').write_text('fixture')
        case = {'name': 'one', 'path': str(fixture), 'expected': 'fixture', 'files': {'result.txt': 'done'}}
        rows = self.grader.grade_student(self.student, [case, case])
        self.assertTrue(all(r['passed'] for r in rows), rows)
        self.assertEqual((self.student / 'data.txt').read_text(), 'original')
        self.assertFalse((self.student / 'result.txt').exists())

    def test_timeout_is_failure(self):
        self.source('while True: pass')
        row = self.grader.grade_student(self.student, [{'name': 'loop', 'expected': '', 'timeout': .2}])[0]
        self.assertEqual(row['status'], 'timeout')

    def test_expected_nonzero_stderr(self):
        self.source("import sys; print('bad input', file=sys.stderr); sys.exit(2)")
        row = self.grader.grade_student(self.student, [{'name': 'error', 'expected': '', 'exit_code': 2, 'stderr': 'bad input'}])[0]
        self.assertTrue(row['passed'], row)

    def test_no_assertions_does_not_pass(self):
        self.source('pass')
        self.assertFalse(self.grader.grade_student(self.student, [{'name': 'empty'}])[0]['passed'])

    def test_load_flat_and_nested_and_disabled(self):
        (self.root / 'output.txt').write_text('one')
        (self.root / 'args.txt').write_text('"two words" C:\\data\\file.txt')
        nested = self.root / 'case2'
        nested.mkdir()
        (nested / 'case.json').write_text(json.dumps({'files': {'copy.txt': 'x'}}))
        disabled = self.root / 'case3'
        disabled.mkdir()
        (disabled / 'case.json').write_text('{"enabled":false}')
        cases = self.grader.load_test_cases(self.root)
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0]['args'], ['two words', 'C:\\data\\file.txt'])

    def test_comparisons_and_path_escape(self):
        self.assertTrue(self.grader.check_result('1  2\n', '1\n2', 'tokens'))
        self.assertTrue(self.grader.check_result('pid=123\n', r'pid=\d+\n', 'regex'))
        self.assertFalse(self.grader.check_result('a\n', 'a', 'exact'))
        with self.assertRaises(ValueError):
            safe_path(self.root, '../escape')

    def test_stale_result_cannot_pass(self):
        self.source('pass')
        (self.student / 'result.txt').write_text('done')
        row = self.grader.grade_student(self.student, [{'name': 'stale', 'files': {'result.txt': 'done'}}])[0]
        self.assertFalse(row['passed'])
        self.assertEqual((self.student / 'result.txt').read_text(), 'done')

    def test_output_limit(self):
        self.source("import sys; sys.stdout.write('x' * 2000000)")
        row = self.grader.grade_student(self.student, [{'name': 'output', 'expected': ''}])[0]
        self.assertEqual(row['status'], 'output_limit')
        self.assertLessEqual(len(row['actual']), self.grader.OUTPUT_LIMIT)

    def test_invalid_metadata(self):
        (self.root / 'case.json').write_text('{broken')
        with self.assertRaises(ValueError):
            self.grader.load_test_cases(self.root)

    def test_missing_source(self):
        self.assertFalse(self.grader.run_code(self.student)[0])

    def test_selected_source(self):
        self.source("print('right')", 'special.py')
        self.source("print('wrong')")
        self.assertEqual(self.grader.run_code(self.student, target_file='special.py')[1], 'right\n')

    def test_csv_header_bom_and_repeated_import(self):
        roster = self.root / 'system_3.csv'
        roster.write_text('학번,이름,github\n20260001,홍길동,https://github.com/example/one.git\n\n', encoding='utf-8-sig')
        evaluator = Evaluator()
        for _ in range(2):
            lecture = evaluator.getDatafromCSV(roster, Lecture(2026, 'system', 3))
            self.assertEqual(len(lecture.students), 1)
            self.assertEqual(evaluator.max, 1)
        roster.write_text('1,A,https://github.com/a/b\n1,B,https://github.com/c/d')
        with self.assertRaises(ValueError):
            evaluator.getDatafromCSV(roster, Lecture(2026, 'system', 3))

    def test_export_csv_escapes_formulas(self):
        path = self.root / 'result.csv'
        save_report(path, [{'student': '1', 'actual': '=1+1', 'passed': False}])
        with path.open(encoding='utf-8-sig') as stream:
            self.assertEqual(next(csv.DictReader(stream))['actual'], "'=1+1")

    def test_case_archive_keeps_partial_results_and_ungraded_students(self):
        from reports import CaseReport
        report = CaseReport({'students': ['1', '2', '3'], 'case_count': 2}, root=self.root / 'reports')
        rows = [{'student': '1', 'case': 'one', 'passed': True, 'status': 'passed'},
                {'student': '1', 'case': 'two', 'passed': False, 'status': 'wrong_answer'},
                {'student': '2', 'case': 'Setup', 'passed': False, 'status': 'missing'}]
        report.save(rows, 'error', 'interrupted')
        _, saved = CaseReport.open(report.directory / 'run.json')
        self.assertEqual(saved['results'], rows)
        with (report.directory / 'summary.csv').open(encoding='utf-8-sig') as stream:
            summary = list(csv.DictReader(stream))
        self.assertEqual(summary[0]['passed_cases'], '1')
        self.assertEqual(summary[1]['passed_cases'], '')
        self.assertEqual(summary[1]['status'], 'ungraded')
        self.assertEqual(summary[2]['status'], 'not_run')


class GitSyncTests(unittest.TestCase):
    def test_clone_pull_and_preserve_local_changes(self):
        from git import Repo, Actor
        from gitmanager import gitManager
        from student import Student
        with tempfile.TemporaryDirectory() as temp, Repo.init(Path(temp) / 'upstream') as upstream:
            root = Path(temp)
            file = root / 'upstream' / 'main.py'
            actor = Actor('SWLAB Test', 'test@example.invalid')
            file.write_text("print('first')")
            upstream.index.add(['main.py'])
            upstream.index.commit('initial', author=actor, committer=actor)
            lecture = Lecture(2026, 'system', 3)
            student = Student(1, 'Demo', 1)
            student.insertGithubLink(lecture, str(root / 'upstream'))
            manager = gitManager(student, lecture)
            manager.origindir = str(root / 'origin')
            self.assertTrue(manager.syncCode())
            clone = root / 'origin' / 'system_3_2026' / '1' / 'main.py'
            file.write_text("print('second')")
            upstream.index.add(['main.py'])
            upstream.index.commit('update', author=actor, committer=actor)
            self.assertTrue(manager.syncCode())
            self.assertEqual(clone.read_text(), "print('second')")
            clone.write_text('local edit')
            self.assertFalse(manager.syncCode())
            self.assertEqual(clone.read_text(), 'local edit')
            upstream.close()
            # Windows Git marks loose objects read-only; TemporaryDirectory handles cleanup.


@unittest.skipUnless(os.environ.get('SWLAB_TEST_DOCKER') == '1', 'Set SWLAB_TEST_DOCKER=1 for Docker integration')
class DockerTests(unittest.TestCase):
    setUp = GradingTests.setUp
    tearDown = GradingTests.tearDown
    source = GradingTests.source

    def test_c_multiple_files_and_arguments(self):
        self.source('#include <stdio.h>\nint value(void); int main(int argc,char**argv){printf("%d %s\\n",value(),argv[1]);}', 'main.c')
        self.source('int value(void){return 42;}', 'helper.c')
        row = self.grader.grade_student(self.student, [{'name': 'link', 'args': ['hello; echo injected'], 'expected': '42 hello; echo injected'}], {'mode': 'docker'})[0]
        self.assertTrue(row['passed'], row)
        self.assertEqual(sorted(p.name for p in self.student.iterdir()), ['helper.c', 'main.c'])

    def test_docker_stdin(self):
        self.source('import sys; print(sys.stdin.read(), end="")')
        ok, out, err = self.grader.run_code(self.student, 'two lines\nlast', runner_config={'mode': 'docker'})
        self.assertTrue(ok, err)
        self.assertEqual(out, 'two lines\nlast')

    def test_docker_compile_error(self):
        self.source('invalid C;', 'main.c')
        row = self.grader.grade_student(self.student, [{'name': 'compile', 'expected': ''}], {'mode': 'docker'})[0]
        self.assertEqual(row['status'], 'compile_error', row)

    def test_docker_fork_timeout_cleanup(self):
        self.source('#include <unistd.h>\nint main(){fork(); for(;;) sleep(1);}', 'main.c')
        row = self.grader.grade_student(self.student, [{'name': 'fork', 'expected': '', 'timeout': 2}], {'mode': 'docker'})[0]
        self.assertEqual(row['status'], 'timeout', row)
        names = subprocess.run(['docker', 'ps', '-a', '--filter', 'name=swlab-run-', '--format', '{{.Names}}'], capture_output=True, text=True, check=True).stdout
        self.assertEqual(names.strip(), '')


if __name__ == '__main__':
    unittest.main()
