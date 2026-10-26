"""Portable result exports; UTF-8 BOM supports Excel's CSV importer."""
import csv
import json
import io
import uuid
from pathlib import Path
from datetime import datetime, timezone
from core.record import atomic_text
from paths import ROOT


def save_report(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == '.json':
        atomic_text(path, json.dumps({'created_at': datetime.now(timezone.utc).isoformat(),
                                    'results': records}, ensure_ascii=False, indent=2))
        return
    columns = ['class_name', 'student', 'chapter', 'problem', 'case', 'status', 'passed', 'returncode', 'actual', 'expected', 'stderr', 'message']
    with io.StringIO(newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            # Do not interpret student output as a spreadsheet formula.
            writer.writerow({k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v)
                             for k, v in record.items()})
        atomic_text(path, '\ufeff' + stream.getvalue())


class CaseReport:
    """Automatic archive for the main screen's reviewed test-case workflow."""
    def __init__(self, context, root=None):
        self.directory = Path(root or ROOT / 'reports' / 'case-grading') / (
            datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
        self.context = context
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.score_overrides = {}
        self.save([], 'running')

    @classmethod
    def open(cls, path):
        path = Path(path)
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        if path.name != 'run.json' or not isinstance(document, dict) or document.get('kind') != 'case_grading' or not isinstance(document.get('context'), dict) or not isinstance(document.get('results'), list):
            raise ValueError('메인 화면에서 자동 저장한 run.json을 선택하세요.')
        for row in document['results']:
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('student', 'case', 'status')) or type(row.get('passed')) is not bool:
                raise ValueError('채점 기록의 결과 형식이 잘못되었습니다.')
        report = cls.__new__(cls)
        report.directory = path.parent
        report.context = document['context']
        report.created_at = document.get('created_at')
        report.state = document.get('state', 'completed')
        report.score_overrides = document.get('score_overrides', {})
        return report, document

    def save(self, rows, state='running', error=None):
        document = {'kind': 'case_grading', 'created_at': self.created_at,
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                    'state': state, 'context': self.context, 'results': rows, 'error': error}
        if 'midterm_scoring' in self.context:
            from midterm_scoring import score_students, export_scores
            document['score_overrides'] = self.score_overrides
            document['scores'] = score_students(rows, self.context, state, self.score_overrides)
        atomic_text(self.directory / 'run.json', json.dumps(document, ensure_ascii=False, indent=2))
        self.state = state
        save_report(self.directory / 'cases.csv', rows)
        if 'scores' in document:
            export_scores(self.directory / 'summary.csv', document['scores'])
            return
        summary = summarize_cases(rows, self.context.get('students', []), self.context.get('case_count', 0), state)
        with io.StringIO(newline='') as stream:
            columns = ['student', 'status', 'passed_cases', 'total_cases']
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for row in summary:
                writer.writerow({k: ("'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value) for k, value in row.items()})
            atomic_text(self.directory / 'summary.csv', '\ufeff' + stream.getvalue())

    def override_midterm_score(self, student, target, score, reviewer, reason):
        from midterm_scoring import score_students, POINTS
        from core.manifest import number
        if self.state == 'running' or 'midterm_scoring' not in self.context:
            raise ValueError('배점 채점이 끝난 기록에서 점수를 조정하세요.')
        if not reviewer.strip() or not reason.strip():
            raise ValueError('검토자와 조정 사유를 입력하세요.')
        _, saved = self.open(self.directory / 'run.json')
        scores = score_students(saved['results'], self.context, self.state, saved.get('score_overrides', {}))
        row = next((s for s in scores if s['student'] == student), None)
        if row is None or target not in row['problems']:
            raise ValueError('이 기록에서 채점한 학생과 문제를 선택하세요.')
        score = number(score, 'score', 0, POINTS[target])
        if round(score, 2) != score:
            raise ValueError('점수는 소수 둘째 자리까지 입력하세요.')
        self.score_overrides = saved.get('score_overrides', {})
        history = self.score_overrides.setdefault(student, {}).setdefault(target, [])
        history.append(dict(previous_score=row['problems'][target]['final_score'], score=score,
                            reviewer=reviewer.strip(), reason=reason.strip(),
                            at=datetime.now(timezone.utc).isoformat()))
        self.save(saved['results'], self.state, saved.get('error'))


def summarize_cases(rows, students=None, case_count=0, state='completed'):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['student'], []).append(row)
    summaries = []
    for student in dict.fromkeys([*(students or []), *grouped]):
        cases = [r for r in grouped.get(student, []) if not r['status'].startswith('manual_')]
        unavailable = any(r['status'] in ('missing', 'error', 'no_tests', 'needs_review') for r in cases)
        status = 'ungraded' if unavailable else ('graded' if cases else ('pending' if state == 'running' else 'not_run'))
        if any(r['status'] == 'needs_review' for r in cases):
            status = 'needs_review'
        if not cases and grouped.get(student):
            status = 'manual_review'
        summaries.append({'student': student, 'status': status,
                          'passed_cases': sum(r['passed'] for r in cases) if status == 'graded' else None,
                          'total_cases': case_count or len(cases)})
    return summaries
