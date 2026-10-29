"""Paths shared by the GUI, importer and command line interface."""
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = ROOT / 'src' / 'origin'
TESTCASES = ROOT / 'testcase'


def natural_key(value):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', value)]


def safe_path(root, *parts):
    root = Path(root).resolve()
    result = root.joinpath(*(str(p) for p in parts if p)).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Path must stay inside the selected directory.')
    return result


def parse_args(value):
    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    lexer.escape = ''
    return list(lexer)


def lecture_name(class_name):
    match = re.fullmatch(r'(.+?)_\d+(?:_\d{4})?', class_name)
    return match[1] if match else class_name


def case_path(class_name, chapter, problem=None):
    return safe_path(TESTCASES, lecture_name(class_name), chapter, problem)
