"""A read-only view composed from independent student/problem grading executions."""
from collections import defaultdict
from datetime import datetime

import db
from reports import summarize_cases


def timestamp(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return 0


class LatestGradebook:
    def __init__(self, scope, students=(), names=None):
        from midterm_scoring import POINTS, settings
        problem = scope.get('problem')
        self.midterm = scope.get('chapter') == 'midterm' and problem in (*POINTS, '__all__')
        targets = list(POINTS) if problem == '__all__' else [problem]
        self.targets = targets
        query_problems = [*POINTS, '__all__'] if self.midterm else [problem]
        records = db.gradebook_records(scope.get('class_name'), scope.get('chapter'), query_problems)
        self.context = dict(scope, students=list(students), student_names=dict(names or {}))
        self.sources = {}
        self.overrides = {}
        self.rows = []
        self.records = records
        definitions = {}
        histories = defaultdict(list)
        # Run creation time identifies a new execution. Later edits to an old run
        # must not make its automatic results newer than a subsequent execution.
        for record in sorted(records, key=lambda r: (timestamp(r['created_at']), r['id'])):
            context = record['context']
            if self.midterm and 'midterm_scoring' not in context:
                continue
            cases = context.get('midterm_suite', {}).get('cases', [])
            by_target = {target: [c for c in cases if c['target_file'] == target] for target in targets}
            definitions.update({target: cases for target, cases in by_target.items() if cases})
            grouped = defaultdict(list)
            for row in record['results']:
                grouped[row['student']].append(row)
            for student, rows in grouped.items():
                for target in targets:
                    if self.midterm:
                        if not by_target[target]:
                            continue
                        own = [r for r in rows if r.get('target_file') == target or
                               r['case'].startswith(target + ' / ') or
                               (not r.get('target_file') and not any(r['case'].startswith(t + ' / ') for t in POINTS))]
                    else:
                        own = rows
                    if own:
                        self.sources[student, target] = dict(record=record, rows=own, cases=by_target[target])
                        for row in own:
                            if row.get('student_name'):
                                self.context['student_names'].setdefault(student, row['student_name'])
            for student, problems in record['score_overrides'].items():
                for target, entries in problems.items():
                    if target in targets:
                        histories[student, target].extend(entries)
        for (student, target), entries in histories.items():
            self.overrides.setdefault(student, {})[target] = sorted(entries,
                key=lambda entry: (timestamp(entry['at']), entry['source_run']))
        student_ids = dict.fromkeys([*students, *(s for s, _ in self.sources), *self.overrides])
        self.context['students'] = list(student_ids)
        seen = set()
        for (student, target), source in self.sources.items():
            for row in source['rows']:
                if id(row) not in seen:
                    seen.add(id(row))
                    self.rows.append(dict(row, source_run=source['record']['id'],
                                          graded_at=source['record']['created_at']))
        if self.midterm:
            from midterm import load_suite
            defaults = load_suite(problem)['cases']
            for target in targets:
                definitions.setdefault(target, [c for c in defaults if c['target_file'] == target])
            self.context.update(midterm_scoring=settings(), midterm_suite={'cases': [
                c for target in targets for c in definitions[target]]}, student_cases={})
            for student in student_ids:
                self.context['student_cases'][student] = {target: self.sources[student, target]['cases']
                    for target in targets if (student, target) in self.sources}

    def summaries(self):
        result = []
        for student in self.context['students']:
            source = self.sources.get((student, self.targets[0]))
            context = source['record']['context'] if source else {}
            result.extend(summarize_cases(source['rows'] if source else [], [student], context.get('case_count', 0),
                source['record']['state'] if source else 'completed', self.context['student_names']))
        return result

    def scores(self, state='completed'):
        from midterm_scoring import score_students
        return score_students(self.rows, self.context, state, self.overrides)

    def adjust(self, student, target, score, reviewer, reason):
        from reports import CaseReport
        source = self.sources.get((student, target))
        if source is None:
            raise ValueError('실행 근거가 있는 학생·문제의 점수를 조정하세요.')
        report, _ = CaseReport.load(source['record']['id'])
        report.override_midterm_score(student, target, score, reviewer, reason)

    def document(self):
        return dict(kind='latest_gradebook', context=self.context, results=self.rows,
                    score_overrides=self.overrides, source_runs=[r['id'] for r in self.records])
