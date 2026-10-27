"""File-based 2026 midterm cases; library steps share an isolated database."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from core.service import copy_submission, environment
from grader import Grader
from paths import ROOT, natural_key, safe_path, lecture_name


SUITE = ROOT / 'assignments/system/2026/midterm'
COPY_CASES = ROOT / 'testcase/system/midterm'
ALL_TARGETS = '__all__'
TARGETS = {
    'copy.c': '1 · 파일 복사',
    'bookcreate.c': '2-(1) · 도서 등록',
    'bookquery.c': '2-(2) · 도서 조회',
    'bookupdate.c': '2-(3) · 대출·반납',
    'sortedbookquery.c': '3-(1) · 대출 횟수 정렬',
    'searchbook.c': '3-(2) · 제목 검색',
    'sortedbookcreate.c': '3-(3) · 연도 정렬 저장',
}
FIELDS = ('id', 'title', 'author', 'year', 'count', 'available')
# Match complete records, including a prompt immediately before the first row.
ROW = (r'(?<!\w)(?P<id>\d+)\s+(?P<title>\S+)\s+(?P<author>\S+)\s+'
       r'(?P<year>\d{4})\s+(?P<count>\d+)\s+(?P<available>True|False|0|1)(?!\w)')


class ReviewRequired(ValueError):
    """A dependency or an unspecified interface needs instructor review."""


class ProgramFailure(ReviewRequired):
    def __init__(self, source, status, message):
        super().__init__(message)
        self.source, self.status = source, status


def is_midterm(class_name, chapter):
    return bool(class_name and lecture_name(class_name) == 'system' and (chapter or '').lower() == 'midterm')


def load_suite(target=ALL_TARGETS, profile_path=None, include_extra=True):
    """Snapshot all case inputs before a GUI batch starts."""
    if target != ALL_TARGETS and target not in TARGETS:
        raise ValueError(f'Unknown midterm target: {target}')
    suite = json.loads((SUITE / 'scenarios.json').read_text(encoding='utf-8'))
    profile_path = Path(profile_path) if profile_path else SUITE / 'profile.json'
    profile = json.loads(profile_path.read_text(encoding='utf-8-sig'))
    pattern = re.compile(profile.get('row_regex', ROW), re.I)
    if not set(FIELDS).issubset(pattern.groupindex):
        raise ValueError('row_regex requires named groups: ' + ', '.join(FIELDS))
    re.compile(profile['error_regex'], re.I)
    cases = []
    if target in (ALL_TARGETS, 'copy.c'):
        cases.extend(dict(c, midterm_kind='copy') for c in Grader().load_test_cases(COPY_CASES))
    for case in suite['cases']:
        if case.get('enabled', True) is False:
            continue
        if target not in (ALL_TARGETS, case['target_file']) or (not include_extra and case.get('category') == 'extra'):
            continue
        cases.append(dict(case, midterm_kind='copy_error' if case['target_file'] == 'copy.c' else 'library'))
    return dict(cases=cases, datasets=suite['datasets'], profile=profile,
                profile_path=str(profile_path.resolve()), available_policy='true_means_available')


def problem_rows():
    from midterm_scoring import POINTS
    # Discovery must remain usable while the teacher corrects an invalid profile.
    error = ''
    cases = []
    try:
        cases = [*Grader().load_test_cases(COPY_CASES),
                 *[c for c in json.loads((SUITE / 'scenarios.json').read_text(encoding='utf-8'))['cases']
                   if c.get('enabled', True) is not False]]
        counts = Counter(c['target_file'] for c in cases)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        counts = Counter()
        error = str(exc)
    return [dict(name=target, label=label, active=count, drafts=0, error=error, path=str(SUITE))
            for target, label, count in [(ALL_TARGETS, '전체 문제 · 75점 · 7개 파일', len(cases) if not error else 0),
                                        *[(name, f'{label} [{name}] · {POINTS[name]}점', counts[name]) for name, label in TARGETS.items()]]]


def grade_suite(submission, bundle, runner_config=None):
    """Run a GUI selection directly in midterm/, never in a filename directory."""
    submission = Path(submission)
    if not submission.is_dir():
        return [dict(case='Setup', status='missing', passed=False, message=f'Directory not found: {submission}')]
    config = {k: v for k, v in (runner_config or {}).items() if k not in ('chapter', 'problem')}
    grader = Grader()
    results = []
    filenames = {p.name for p in submission.iterdir() if p.is_file()}
    for case in bundle['cases']:
        if case['target_file'] not in filenames:
            row = dict(passed=False, status='missing_source', message=f'Required exam file missing: {case["target_file"]}')
        elif case['midterm_kind'] == 'copy':
            row = grader.grade_student(submission, [case], config)[0]
        elif case['midterm_kind'] == 'copy_error':
            row = copy_error_case(submission, case, config)
        else:
            row = library_case(submission, case, bundle['datasets'], bundle['profile'], config)
        results.append(dict(row, case=f'{case["target_file"]} / {case["name"]}',
                            target_file=case['target_file'], available_policy=bundle['available_policy']))
    return results


def parse_records(output, profile):
    records = []
    for match in re.finditer(profile.get('row_regex', ROW), output, re.I):
        row = match.groupdict()
        records.append((int(row['id']), row['title'], row['author'], int(row['year']),
                        int(row['count']), row['available'].lower() in ('true', '1')))
    return records


def compare_records(actual, expected, order=None):
    actual = [tuple(row) for row in actual]
    expected = [tuple(row) for row in expected]
    if Counter(actual) != Counter(expected):
        return False
    if order:
        index = FIELDS.index(order)
        return [row[index] for row in actual] == sorted((row[index] for row in actual), reverse=True)
    return True


def registration_input(records, profile):
    lines = [profile.get('record_template', '{id} {title} {author} {year} {count} {available}').format(
        **dict(zip(FIELDS, [*row[:5], int(row[5])]))) for row in records]
    return profile.get('create_prefix', '').format(n=len(records)) + '\n'.join(lines) + '\n' + profile.get('create_suffix', '')


def execute_step(grader, work, source, data, profile, config, trace, allow_error=False):
    if not safe_path(work, source).is_file():
        raise ReviewRequired(f'Required source missing: {source}')
    result = grader.execute(work, data, profile.get('args', {}).get(source, []),
                            {**config, 'sources': [source]}, target_file=source)
    trace.append(dict(source=source, input=data, **result))
    for flag, status in [('timed_out', 'timeout'), ('output_limit', 'output_limit'), ('compile_error', 'compile_error')]:
        if result.get(flag):
            raise ProgramFailure(source, status, f'{source}: {status}; inspect trace')
    if result['returncode'] is None:
        raise ReviewRequired(f'{source}: runtime environment unavailable; inspect trace')
    if not allow_error and result['returncode'] != 0:
        raise ProgramFailure(source, 'runtime_error', f'{source}: exit {result["returncode"]}; inspect trace')
    return result


def library_case(submission, case, datasets, profile, config):
    trace = []
    row = dict(case=case['name'], target_file=case['target_file'], passed=False,
               status='needs_review', trace=trace, category=case.get('category', 'required'))
    grader = Grader()
    try:
        with tempfile.TemporaryDirectory(prefix='swlab-midterm-') as temporary:
            work = Path(temporary) / 'work'
            copy_submission(submission, work)
            database = safe_path(work, profile.get('database', 'db.dat'))
            if database.exists():
                if not database.is_file():
                    raise ReviewRequired('Database path is not a regular file')
                database.unlink()
            records = datasets[case['dataset']]

            def run(source, data='', allow_error=False):
                return execute_step(grader, work, source, data, profile, config, trace, allow_error)

            def query():
                output = run('bookquery.c', '0\n')['stdout']
                return parse_records(output, profile)

            creator = case['target_file'] if case['target_file'] in ('bookcreate.c', 'sortedbookcreate.c') else 'bookcreate.c'
            run(creator, registration_input(records, profile))
            if not database.is_file() or database.stat().st_size == 0:
                raise ReviewRequired(f'{creator} did not create a nonempty database; check registration profile')
            # Establish that the student's writer and reader agree before testing another program.
            if creator == 'bookcreate.c' and case['target_file'] != 'bookcreate.c':
                if not compare_records(query(), records):
                    raise ReviewRequired('Seed/readback mismatch: check bookcreate.c, bookquery.c or input/row profile')

            expected = [list(record) for record in records]
            target = case['target_file']
            if target in ('bookcreate.c', 'sortedbookcreate.c'):
                actual = query()
                passed = compare_records(actual, expected, case.get('order'))
            elif target == 'bookquery.c':
                output = run(target, f'{case["option"]}\n')['stdout']
                if case['option'] == 1:
                    expected = [r for r in expected if r[5]]
                actual = parse_records(output, profile)
                passed = compare_records(actual, expected)
            elif target == 'bookupdate.c':
                for operation, book_id in case['operations']:
                    rejected = operation == 0 and any(r[0] == book_id and not r[5] for r in expected)
                    run(target, f'{operation} {book_id}\n', allow_error=rejected)
                    for record in expected:
                        if record[0] == book_id:
                            if operation == 0 and record[5]:
                                record[4] += 1
                                record[5] = False
                            elif operation == 1:
                                record[5] = True
                    # Check every transition, so a later operation cannot conceal an earlier error.
                    actual = query()
                    if not compare_records(actual, expected):
                        row.update(status='wrong_answer', actual=actual, expected=expected,
                                   message=f'State mismatch after operation {operation} {book_id}')
                        return row
                passed = True
            elif target == 'sortedbookquery.c':
                actual = parse_records(run(target, profile.get('sorted_query_input', '0\n'))['stdout'], profile)
                passed = compare_records(actual, expected, 'count')
                # Sorting a display must preserve all stored values.
                passed = compare_records(query(), expected) and passed
            elif target == 'searchbook.c':
                result = run(target, case['search'] + '\n', allow_error=True)
                actual = parse_records(result['stdout'], profile)
                expected = [r for r in expected if r[1] == case['search']]
                passed = compare_records(actual, expected)
                if expected:
                    passed = passed and result['returncode'] == 0
                else:
                    passed = passed and bool(re.search(profile['error_regex'], result['stdout'] + '\n' + result['stderr'], re.I))
            else:
                raise ValueError(f'Unknown target {target}')
            row.update(passed=passed, status='passed' if passed else 'wrong_answer', actual=actual, expected=expected)
    except ProgramFailure as exc:
        row.update(message=str(exc), status=exc.status if exc.source == case['target_file'] else 'needs_review')
    except (OSError, ValueError) as exc:
        row['message'] = str(exc)
    return row


def copy_error_case(submission, case, config):
    trace = []
    row = dict(case=case['name'], target_file='copy.c', passed=False, status='needs_review', trace=trace)
    profile = {'args': {'copy.c': case['args']}}
    try:
        with tempfile.TemporaryDirectory(prefix='swlab-midterm-') as temporary:
            work = Path(temporary) / 'work'
            copy_submission(submission, work)
            source = work / 'source.txt'
            if source.exists():
                source.unlink()
            destination = work / 'destination.txt'
            if destination.exists():
                if destination.is_dir():
                    raise ReviewRequired('Unexpected destination directory in submission')
                destination.unlink()
            if case['kind'] == 'destination_directory':
                source.write_text('Hello World\n', encoding='utf-8')
                destination.mkdir()
            result = execute_step(Grader(), work, 'copy.c', '', profile, config, trace, allow_error=True)
            passed = bool(re.search(case['error_regex'], result['stdout'] + '\n' + result['stderr'], re.I))
            row.update(passed=passed, status='passed' if passed else 'wrong_answer')
    except ProgramFailure as exc:
        row.update(message=str(exc), status=exc.status)
    except (OSError, ValueError) as exc:
        row['message'] = str(exc)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('submissions', type=Path, nargs='?')
    parser.add_argument('--batch', action='store_true', help='Directory containing student repositories')
    parser.add_argument('--chapter', default='midterm', help='Submission directory relative to each repository; use . for midterm itself')
    parser.add_argument('--target', choices=['copy.c', 'bookcreate.c', 'bookquery.c', 'bookupdate.c',
                                           'sortedbookquery.c', 'searchbook.c', 'sortedbookcreate.c'])
    parser.add_argument('--profile', type=Path, default=SUITE / 'profile.json')
    parser.add_argument('--mode', choices=['docker', 'windows', 'linux', 'wsl'], default='docker')
    parser.add_argument('--image', default='grader-image')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--include-extra', action='store_true', help='Include robustness cases beyond explicit examples')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--output', type=Path, help='JSON report (default: a new reports/midterm/<run>.json)')
    options = parser.parse_args(argv)
    try:
        bundle = load_suite(options.target or ALL_TARGETS, options.profile, options.include_extra)
        if options.list:
            for case in bundle['cases']:
                print(f'{case["target_file"]}: {case["name"]}')
            return 0
        if options.submissions is None or not options.submissions.is_dir():
            raise ValueError('Provide an existing submission repository or --batch directory')
        students = sorted((p for p in options.submissions.iterdir() if p.is_dir() and not p.name.startswith('.')),
                          key=lambda p: natural_key(p.name)) if options.batch else [options.submissions]
        if not students:
            raise ValueError('No student directories found')
        options.output = (options.output or ROOT / 'reports/midterm' / (
            datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8] + '.json')).resolve()
        if options.output.suffix.lower() != '.json':
            raise ValueError('--output must end in .json to preserve step evidence')
        if any(options.output.is_relative_to(student.resolve()) for student in students):
            raise ValueError('Save reports outside student repositories')
        env = environment(options.mode, options.image, 'c')
        rows = []
        from midterm_scoring import settings, score_students, export_scores
        from core.record import atomic_text
        context = dict(students=[s.name for s in students], midterm_scoring=settings(),
                       midterm_suite=bundle)
        def save_scores(state='running'):
            scores = score_students(rows, context, state)
            atomic_text(options.output, json.dumps(dict(created_at=datetime.now().astimezone().isoformat(),
                state=state, context=context, results=rows, scores=scores), ensure_ascii=False, indent=2))
            export_scores(options.output.with_suffix('.csv'), scores)
        config = dict(mode=options.mode, image=env.get('image_id', options.image), timeout=options.timeout)
        save_scores()
        for student in students:
            submission = safe_path(student, options.chapter)
            rows.extend(dict(row, student=student.name) for row in grade_suite(submission, bundle, config))
            save_scores()
            own = [r for r in rows if r['student'] == student.name]
            score = next(s for s in score_students(rows, context) if s['student'] == student.name)
            value = 'review required' if score['final_score'] is None else f'{score["final_score"]:g}/{score["max_score"]:g}'
            print(f'{student.name}: {value} points; {sum(r["passed"] for r in own)}/{len(own)} passed', flush=True)
        save_scores('completed')
        print(f'Report: {options.output}')
        return 0 if all(r['passed'] for r in rows) else 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
