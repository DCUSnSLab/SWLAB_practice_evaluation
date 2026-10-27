"""Exam statements and DCUCode review presets for midterm files."""
from copy import deepcopy
import json

from midterm import ALL_TARGETS, SUITE, TARGETS
from midterm_scoring import POINTS, PROBLEM_LABELS
from qualitative import DEFAULT_RUBRIC, validate_rubric

PROBLEMS = SUITE / 'problems.json'
HEADER_PATTERN = '*.h'


def load_problems(path=PROBLEMS):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    shared = data.get('shared', {})
    problems = data.get('problems')
    if not isinstance(shared, dict) or not isinstance(problems, dict) or set(problems) != set(TARGETS):
        raise ValueError('problems.json must describe exactly the seven exam files')
    for target, item in problems.items():
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip():
            raise ValueError(f'problems.json: empty statement for {target}')
        if not all(isinstance(key, str) and isinstance(shared.get(key), str) for key in item.get('shared', [])):
            raise ValueError(f'problems.json: unknown shared section for {target}')
        if not isinstance(item.get('pages'), list) or not all(type(page) is int and page > 0 for page in item['pages']):
            raise ValueError(f'problems.json: pages for {target} must be positive integers')
    return data


def check_target(target):
    if target != ALL_TARGETS and target not in TARGETS:
        raise ValueError(f'Unknown midterm target: {target}')
    return list(TARGETS) if target == ALL_TARGETS else [target]


def problem_statement(target, problems=None):
    data = problems or load_problems()
    parts, shown = [], set()
    if any(name != 'copy.c' for name in check_target(target)):
        parts.append('[교수자 보정 기준 — 시험지의 상충하는 설명·예시보다 우선 적용]\n'
                     '대출 유무 True/1은 대출 가능, False/0은 대출 중이다. '
                     '대출 성공 시 False/0으로 바꾸고 대출 횟수를 1 증가시킨다. '
                     '반납 시 True/1로 바꾸며 대출 횟수는 유지한다.')
    for name in check_target(target):
        item = data['problems'][name]
        # Problems 2 and 3 share requirements and data tables; state them once, before the first sub-problem.
        for key in item.get('shared', []):
            if key not in shown:
                shown.add(key)
                parts.append(data['shared'][key].strip())
        parts.append(f'[{PROBLEM_LABELS[name]} · {name} · {POINTS[name]}점]\n{item["text"].strip()}')
    return '\n\n'.join(parts)


def scaled_rubric(points, rubric=DEFAULT_RUBRIC):
    """Keep DCUCode axes at 0–10; exam points belong to the separate partial score."""
    return validate_rubric(deepcopy(rubric))


def source_patterns(target):
    """Only the exam file(s) and the student's headers; other scratch sources stay local."""
    return [*check_target(target), HEADER_PATTERN]


def qualitative_preset(target, problems=None):
    files = check_target(target)
    data = problems or load_problems()
    points = sum(POINTS[name] for name in files)
    if target == ALL_TARGETS:
        title = '중간고사 전체 문제 · 7개 파일'
    else:
        title = f'중간고사 {PROBLEM_LABELS[target]} · {target}'
    pages = sorted({page for name in files for page in data['problems'][name]['pages']})
    patterns = source_patterns(target)
    return dict(title=title, problem=problem_statement(target, data), rubric=scaled_rubric(points),
                sources=patterns, points=points,
                summary=f'{title} · 시험지 {", ".join(map(str, pages))}쪽 · 배점 {points:g}점 · '
                        f'전송 파일: {", ".join(patterns)}')
