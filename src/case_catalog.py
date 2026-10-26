"""Discover grading problems independently of student submission folders."""
from pathlib import Path
import re
from grader import Grader
from paths import case_path, natural_key


def is_case(folder):
    return (folder / 'case.json').is_file() or (folder / 'output.txt').is_file()


def problem_catalog(class_name, chapter, submissions=()):
    root = case_path(class_name, chapter)
    names = set(submissions)
    if root.is_dir():
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name.startswith('.'):
                continue
            if re.fullmatch(r'(?:prob|prod|hw)\d+', folder.name, re.I) or (
                    not is_case(folder) and any(is_case(p) for p in folder.iterdir() if p.is_dir())):
                names.add(folder.name)
    rows = []
    for name in names:
        folder = root / name
        total = sum(is_case(p) for p in [folder, *[p for p in folder.iterdir() if p.is_dir()]]) if folder.is_dir() else 0
        error = ''
        try:
            active = len(Grader().load_test_cases(folder))
        except (OSError, ValueError, TypeError) as exc:
            active, error = 0, str(exc)
        rows.append(dict(name=name, active=active, drafts=max(0, total-active), error=error, path=str(folder)))
    return sorted(rows, key=lambda row: (0 if row['active'] else 1 if row['drafts'] else 2, natural_key(row['name'])))


def target_label(chapter, problem):
    chap = re.fullmatch(r'chap(\d+)', chapter, re.I)
    prob = re.fullmatch(r'(prob|prod|hw)(\d+)', problem, re.I)
    return ' · '.join([f'{int(chap[1])}장' if chap else chapter or '장 미선택',
        (f'{"과제" if prob[1].lower() == "hw" else "문제"} {int(prob[2])}번 [{problem}]') if prob else problem or '문제 미선택'])
