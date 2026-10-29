"""Read a full roster before side effects; include students without local folders."""
import csv
from pathlib import Path


def read_roster(path):
    students = []
    seen = set()
    with open(path, encoding='utf-8-sig', newline='') as stream:
        for line, row in enumerate(csv.reader(stream), 1):
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].strip().lower() in ('학번', 'student_id', 'sid'):
                continue
            if len(row) < 3:
                raise ValueError(f'CSV row {line}: expected student ID, name, repository URL.')
            sid, name, url = (value.strip() for value in row[:3])
            if not sid.isascii() or not sid.isdigit() or not name or not url.startswith(('https://', 'http://', 'git@')):
                raise ValueError(f'CSV row {line}: invalid ID, name or repository URL.')
            # Preserve the existing importer's numeric directory convention.
            sid = str(int(sid))
            if sid in seen:
                raise ValueError(f'CSV row {line}: duplicate student ID {sid}.')
            seen.add(sid)
            students.append({'student_id': sid, 'name': name, 'url': url})
    if not students:
        raise ValueError('CSV contains no students.')
    return students


def roster_submissions(roster, directory):
    root = Path(directory).resolve()
    return [{'student_id': row['student_id'], 'class_name': root.name,
             'path': str(root / row['student_id'])} for row in read_roster(roster)]
