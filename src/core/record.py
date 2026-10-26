"""An atomic run.json is authoritative; summary.csv is a derived export."""
from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile

from core.manifest import number


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def export_summary(path, run):
    stream = io.StringIO(newline='')
    columns = ['class_name', 'student_id', 'problem_id', 'status', 'auto_score', 'final_score', 'max_score', 'passed_cases', 'case_count', 'message', 'graded_at']
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in run['results']:
        writer.writerow({k: ("'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value)
                         for k, value in row.items() if k in columns})
    atomic_text(path, '\ufeff' + stream.getvalue())


def save_run(path, run):
    atomic_text(path, json.dumps(run, ensure_ascii=False, indent=2, allow_nan=False))
    export_summary(Path(path).with_name('summary.csv'), run)


def load_run(path):
    run = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(run, dict) or run.get('schema_version') != 1 or not isinstance(run.get('results'), list) or not isinstance(run.get('problem'), dict):
        raise ValueError('Not a supported grading run')
    if run.get('state') not in ('running', 'completed', 'cancelled', 'error'):
        raise ValueError('Invalid run state')
    for key in ('id', 'title', 'statement'):
        if not isinstance(run['problem'].get(key), str):
            raise ValueError(f'Invalid saved problem: {key}')
    ids = set()
    for row in run['results']:
        if not isinstance(row, dict) or not isinstance(row.get('student_id'), str) or row['student_id'] in ids:
            raise ValueError('Invalid or duplicate student record')
        ids.add(row['student_id'])
        if row.get('status') not in ('pending', 'graded', 'unresolved', 'error', 'not_run') or not isinstance(row.get('cases'), list):
            raise ValueError('Invalid student grading state')
        if not isinstance(row.get('submission', {}), dict) or not isinstance(row.get('overrides', []), list):
            raise ValueError('Invalid student record details')
        for case in row['cases']:
            if not isinstance(case, dict) or not isinstance(case.get('case'), str) or not isinstance(case.get('status'), str):
                raise ValueError('Invalid saved case')
        total = number(row.get('max_score'), 'max_score', .01)
        for key in ('auto_score', 'final_score'):
            if row.get(key) is not None:
                number(row[key], key, 0, total)
    return run


def override_score(path, student_id, score, reviewer, reason):
    run = load_run(path)
    if run.get('state') not in ('completed', 'cancelled', 'error'):
        raise ValueError('Cannot adjust a run while grading is in progress')
    if run['problem'].get('scoring', {}).get('manual_override', 'allowed') == 'forbidden':
        raise ValueError('This problem does not allow manual score changes')
    if not reviewer.strip() or not reason.strip():
        raise ValueError('Reviewer and reason are required')
    row = next((r for r in run['results'] if r['student_id'] == student_id), None)
    if row is None:
        raise ValueError('Student record not found')
    score = number(score, 'final_score', 0, row['max_score'])
    history = row.setdefault('overrides', [])
    history.append({'previous_score': row.get('final_score'), 'score': score, 'by': reviewer.strip(), 'reason': reason.strip(), 'at': now()})
    row['final_score'] = score
    row['review_state'] = 'adjusted'
    save_run(path, run)
    return deepcopy(run)
