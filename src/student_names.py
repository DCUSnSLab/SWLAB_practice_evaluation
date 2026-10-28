"""Local roster names, kept separate from submission identity and model requests.

Names live in the SQLite store (see db.py). Roster CSV files and the older
.student_names.json cache are still read so existing folders keep their names.
"""
import json
import re

from core.roster import read_roster
from paths import safe_path

CACHE_NAME = '.student_names.json'


def save_student_names(class_name, rows):
    import db
    db.save_roster(class_name, rows)


def read_student_names(class_name):
    import db
    from paths import ORIGIN, ROOT
    names = {}
    match = re.fullmatch(r'(.+)_(\d+)_(\d{4})', class_name)
    if match:
        course, division, year = match.groups()
        # Match numeric divisions too, e.g. system_02.csv -> system_2_2023.
        filename = re.compile(re.escape(course) + r'(?:_test)?_(\d+)\.csv', re.I)
        for directory in (ROOT / 'testdata' / year, ROOT / 'testdata'):
            candidates = []
            for path in directory.glob('*.csv'):
                found = filename.fullmatch(path.name)
                if found and int(found[1]) == int(division): candidates.append(path)
            for path in sorted(candidates, key=lambda p: ('_test_' in p.name.lower(), p.name)):
                try:
                    names = {row['student_id']: row['name'] for row in read_roster(path)}
                except (OSError, ValueError):
                    continue
                break
            if names: break
    try:
        data = json.loads(safe_path(ORIGIN, class_name, CACHE_NAME).read_text(encoding='utf-8-sig'))
        cached = data.get('names') if isinstance(data, dict) and data.get('version') == 1 else None
        if isinstance(cached, dict) and all(isinstance(sid, str) and sid.isascii() and sid.isdigit() and
                                           isinstance(name, str) and name.strip() for sid, name in cached.items()):
            names.update(cached)
    except (OSError, ValueError):
        pass
    try:
        names.update(db.roster_names(class_name))
    except Exception:  # peewee errors share no useful base; a broken DB must not hide the list
        pass
    return names


def fill_student_names(rows):
    by_class = {}
    for row in rows:
        class_name = row.get('class_name')
        if row.get('student_name') or not class_name: continue
        if class_name not in by_class: by_class[class_name] = read_student_names(class_name)
        name = by_class[class_name].get(str(row.get('student', '')))
        if name: row['student_name'] = name


def student_label(row):
    sid = str(row.get('student', ''))
    name = row.get('student_name')
    return f'{sid} · {name}' if name else sid
