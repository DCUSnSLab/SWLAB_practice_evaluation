"""One CSV record per student, using fresh evidence from the live gradebook."""
import csv
import io

import db
from core.record import atomic_text
from latest_gradebook import LatestGradebook
from paths import natural_key
from qualitative_rubric import AXES, RESOURCE_IDS


def load_latest(scope, students=(), names=None):
    book = LatestGradebook(scope, students, names)
    problems = [*book.targets, '__all__'] if scope.get('problem') == '__all__' else book.targets
    reviews = db.latest_qualitative_reviews(scope.get('class_name'), scope.get('chapter'), problems)
    book.context['students'] = sorted(dict.fromkeys([*book.context['students'], *(r['student'] for r in reviews)]),
                                      key=natural_key)
    for review in reviews:
        if review.get('student_name') and not book.context['student_names'].get(review['student']):
            book.context['student_names'][review['student']] = review['student_name']
    return book, reviews


def prefix(problem):
    return 'exam' if problem == '__all__' else str(problem or 'problem')


def csv_rows(book, reviews):
    """Keep execution marks, AI proposals and instructor approvals in distinct columns."""
    columns = ['student', 'student_name', 'status', 'auto_score', 'final_score', 'max_score', 'reason',
               'passed_cases', 'total_cases', 'class_name', 'chapter', 'problem']
    for target in book.targets:
        columns += [f'{prefix(target)}_{key}' for key in ('auto', 'final', 'max', 'adjusted')]
    review_problems = list(dict.fromkeys([*book.targets, *(r.get('problem') for r in reviews)]))
    review_fields = ['status', 'overall', 'suggested_score', 'max_score', 'final_score', 'resource_score',
                     'summary', 'reviewer_note', 'message', 'run_id', 'saved_at', 'submission_issue']
    criterion_ids = list(dict.fromkeys([*AXES, *RESOURCE_IDS.values(),
        *(c['id'] for r in reviews for c in r.get('criteria', []))]))
    for problem in review_problems:
        base = prefix(problem) + '_qualitative_'
        columns += [base + key for key in review_fields]
        columns += [base + cid + '_' + key for cid in criterion_ids for key in ('score', 'applicable')]
    for target in book.targets:
        columns += [f'{prefix(target)}_adjustment_{key}' for key in ('reason', 'reviewer', 'at')]
    by_student = {}
    for review in reviews:
        by_student.setdefault(review['student'], []).append(review)
    rows = []
    for score in book.scores() if book.midterm else book.summaries():
        student = score['student']
        row = {key: score.get(key) for key in columns[:9]}
        row.update({key: book.context.get(key) for key in ('class_name', 'chapter', 'problem')})
        for target, problem in score.get('problems', {}).items():
            base = prefix(target)
            row.update({base + '_auto': problem['auto_score'], base + '_final': problem['final_score'],
                        base + '_max': problem['max_score']})
            history = book.overrides.get(student, {}).get(target, [])
            if history:
                latest = history[-1]
                row[base + '_adjusted'] = latest['score']
                row.update({base + '_adjustment_' + key: latest.get(key) for key in ('reason', 'reviewer', 'at')})
        for problem in review_problems:
            row[prefix(problem) + '_qualitative_status'] = 'not_reviewed'
        for review in by_student.get(student, []):
            base = prefix(review.get('problem')) + '_qualitative_'
            row.update({base + key: review.get(key) for key in review_fields})
            if review['status'] not in ('confirmed', 'submission_zero'):
                row[base + 'final_score'] = None
            if review['status'] not in ('ai_proposed', 'confirmed', 'submission_zero'):
                for key in ('overall', 'suggested_score', 'resource_score'):
                    row[base + key] = None
                continue
            for criterion in review.get('criteria', []):
                applicable = criterion.get('applicable', True)
                row[base + criterion['id'] + '_score'] = criterion.get('score') if applicable else None
                row[base + criterion['id'] + '_applicable'] = applicable
        rows.append(row)
    return columns, rows


def cell(value):
    if isinstance(value, str):
        # Feedback must not add physical lines or become an Excel formula.
        value = ' '.join(value.split())
        if value.startswith(('=', '+', '-', '@')):
            value = "'" + value
    return value


def export_latest_csv(path, scope, students=(), names=None):
    book, reviews = load_latest(scope, students, names)
    columns, rows = csv_rows(book, reviews)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow([cell(column) for column in columns])
    for row in rows:
        writer.writerow([cell(row.get(column)) for column in columns])
    atomic_text(path, '\ufeff' + stream.getvalue())
    return len(rows)
