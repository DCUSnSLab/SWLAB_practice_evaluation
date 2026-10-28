"""Exam points come from the paper; partial credit uses required-case ratios."""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
import csv
import io

from core.record import atomic_text


POINTS = {'copy.c': 10, 'bookcreate.c': 5, 'bookquery.c': 10, 'bookupdate.c': 10,
          'sortedbookquery.c': 10, 'searchbook.c': 10, 'sortedbookcreate.c': 20}
POLICY = 'required_case_ratio'
KNOWN_FAILURES = {'wrong_answer', 'compile_error', 'runtime_error', 'timeout', 'output_limit', 'missing_source', 'empty_source'}
PROBLEM_LABELS = dict(zip(POINTS, ['1번', '2-(1)', '2-(2)', '2-(3)', '3-(1)', '3-(2)', '3-(3)']))
FAILURE_LABELS = {'wrong_answer': '출력·파일 불일치', 'compile_error': '컴파일 오류',
                  'runtime_error': '실행 오류', 'timeout': '시간 초과', 'output_limit': '출력 제한 초과',
                  'missing_source': '지정 파일 없음', 'empty_source': '빈 제출 파일'}


def problem_reason(matches, passed, total, known):
    if not known:
        if any(not group for group in matches):
            return '필수 검사 결과 없음'
        if any(len(group) != 1 for group in matches):
            return '중복 검사 결과 확인 필요'
        rows = [group[0] for group in matches]
        review = next((row for row in rows if row['status'] not in KNOWN_FAILURES and row['status'] != 'passed'), None)
        if review:
            message = review.get('message', '')
            if 'Seed/readback mismatch' in message:
                return '등록·조회 결과 불일치로 검토 필요'
            if 'Required source missing:' in message:
                return '연계 파일 없음: ' + message.split('Required source missing:', 1)[1].strip()
            if 'did not create a nonempty database' in message:
                return '등록 입력·DB 생성 확인 필요'
            trace = review.get('trace', [])
            if trace and trace[-1].get('compile_error'):
                return '연계 프로그램 컴파일 오류'
            if trace and trace[-1].get('timed_out'):
                return '연계 프로그램 시간 초과'
            return '입력 형식·연계 실행 검토 필요'
        return '검사 판정 불일치 확인 필요'
    if passed == total:
        return '필수 케이스 모두 통과'
    counts = Counter(group[0]['status'] for group in matches if group[0]['status'] != 'passed')
    failures = ', '.join(f'{FAILURE_LABELS[status]} {count}건' for status, count in counts.items())
    return f'{failures} (필수 {passed}/{total} 통과)'


def settings():
    return dict(policy=POLICY, points=dict(POINTS), decimals=2, rounding='half_up', extra_cases='diagnostic_only')


def validate_settings(config):
    if config != settings():
        raise ValueError('Unsupported midterm scoring settings')


def score_students(rows, context, state='completed', overrides=None):
    """Missing/ambiguous evidence is ungraded; extra cases never change points."""
    validate_settings(context['midterm_scoring'])
    bundle = context['midterm_suite']
    definitions = defaultdict(list)
    for case in bundle['cases']:
        definitions[case['target_file']].append(case)
    selected = [target for target in POINTS if target in definitions]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['student']].append(row)
    result = []
    for student in dict.fromkeys([*context.get('students', []), *grouped]):
        own = grouped[student]
        by_id = defaultdict(list)
        for row in own:
            if not row['status'].startswith('manual_'):
                by_id[row['case']].append(row)
        problems = {}
        for target in selected:
            own_definitions = context.get('student_cases', {}).get(student, {}).get(target, definitions[target])
            required = [c for c in own_definitions if c.get('category') != 'extra']
            required_rows = [by_id[f'{target} / {c["name"]}'] for c in required]
            known = bool(required) and all(len(matches) == 1 and (
                matches[0]['status'] == 'passed' and matches[0]['passed'] is True or
                matches[0]['status'] in KNOWN_FAILURES and matches[0]['passed'] is False)
                for matches in required_rows)
            passed = sum(len(matches) == 1 and matches[0]['status'] == 'passed' and matches[0]['passed'] is True
                         for matches in required_rows)
            auto = float((Decimal(POINTS[target]) * passed / len(required)).quantize(
                Decimal('.01'), rounding=ROUND_HALF_UP)) if known else None
            history = (overrides or {}).get(student, {}).get(target, [])
            final = history[-1]['score'] if history else auto
            auto_reason = problem_reason(required_rows, passed, len(required), known)
            reason = '수동 조정: ' + ' '.join(history[-1]['reason'].split()) if history else auto_reason
            problems[target] = dict(auto_score=auto, final_score=final, max_score=POINTS[target],
                                    passed_required=passed, required_cases=len(required),
                                    status='adjusted' if history else ('graded' if known else 'needs_review'),
                                    overrides=history, auto_reason=auto_reason, reason=reason)
        auto_scores = [p['auto_score'] for p in problems.values()]
        final_scores = [p['final_score'] for p in problems.values()]
        def total(values):
            return float(sum((Decimal(str(v)) for v in values), Decimal(0))) if all(v is not None for v in values) else None
        final = total(final_scores)
        status = ('adjusted' if any(p['overrides'] for p in problems.values()) else 'graded') if final is not None else 'needs_review'
        if not own and not any(p['overrides'] for p in problems.values()):
            status = 'pending' if state == 'running' else 'not_run'
        reasons = [f'{PROBLEM_LABELS[target]}: {p["reason"]}' for target, p in problems.items()
                   if p['overrides'] or p['auto_score'] is None or p['auto_score'] < p['max_score']]
        if status in ('pending', 'not_run'):
            reasons = ['채점 대기' if status == 'pending' else '미실행']
        elif any(r['status'] == 'missing' for r in own):
            reasons = ['제출 경로를 찾을 수 없음']
        if not reasons:
            reasons = ['필수 케이스 모두 통과']
        own_cases = [c for target in selected for c in
                     context.get('student_cases', {}).get(student, {}).get(target, definitions[target])]
        extra_ids = {c['target_file'] + ' / ' + c['name'] for c in own_cases if c.get('category') == 'extra'}
        extra_issues = sum(r['case'] in extra_ids and not r['passed'] for r in own)
        if extra_issues:
            reasons.append(f'추가 {extra_issues}건 미통과·점수 제외')
        brief = ' / '.join(reasons[:2]) + (f' 외 {len(reasons) - 2}건' if len(reasons) > 2 else '')
        if len(brief) > 120:
            brief = brief[:117] + '…'
        result.append(dict(student=student, student_name=context.get('student_names', {}).get(student, ''),
                           status=status, auto_score=total(auto_scores), final_score=final,
                           max_score=sum(POINTS[t] for t in selected), problems=problems,
                           known_score=float(sum(Decimal(str(v)) for v in final_scores if v is not None)),
                           passed_cases=sum(r.get('passed') is True for r in own if not r['status'].startswith('manual_')),
                           total_cases=len(own_cases), reason='\n'.join(reasons), reason_short=brief))
    return result


def export_scores(path, scores):
    columns = ['student', 'student_name', 'status', 'auto_score', 'final_score', 'max_score', 'reason']
    for target in POINTS:
        columns.extend([target + '_auto', target + '_final', target + '_max'])
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for score in scores:
        row = {key: score.get(key, '') for key in columns[:7]}
        for target, problem in score['problems'].items():
            row.update({target + '_auto': problem['auto_score'], target + '_final': problem['final_score'],
                        target + '_max': problem['max_score']})
        writer.writerow({key: ("'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value)
                         for key, value in row.items()})
    atomic_text(path, '\ufeff' + stream.getvalue())
