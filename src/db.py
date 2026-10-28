"""Single SQLite store for rosters, grading runs, case results and score adjustments.

The database is the durable copy; run.json / CSV files remain exports. Set SWLAB_DB
to relocate the file (tests point it at a temporary folder).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from peewee import (BooleanField, CharField, DoubleField, ForeignKeyField, IntegerField, Model,
                    SqliteDatabase, TextField)

database = SqliteDatabase(None)


class BaseModel(Model):
    class Meta:
        database = database


class Roster(BaseModel):
    """One row per enrolled student per class; the folder name (ID) is the key everywhere else."""
    class_name = CharField()
    student = CharField()
    name = CharField()
    updated_at = CharField()

    class Meta:
        indexes = ((('class_name', 'student'), True),)


class GradingRun(BaseModel):
    """A batch grading execution; `id` is the report folder name so files and rows match."""
    id = CharField(primary_key=True)
    class_name = CharField(null=True, index=True)
    chapter = CharField(null=True)
    problem = CharField(null=True)
    mode = CharField(null=True)
    state = CharField()
    created_at = CharField(null=True)
    updated_at = CharField()
    directory = CharField(null=True)
    error = TextField(null=True)
    context = TextField()


class CaseResult(BaseModel):
    run = ForeignKeyField(GradingRun, backref='results', on_delete='CASCADE')
    position = IntegerField()
    student = CharField(index=True)
    student_name = CharField(default='')
    case = CharField()
    status = CharField()
    passed = BooleanField()
    data = TextField()


class ScoreOverride(BaseModel):
    run = ForeignKeyField(GradingRun, backref='overrides', on_delete='CASCADE')
    student = CharField()
    target = CharField()
    previous_score = DoubleField(null=True)
    score = DoubleField()
    reviewer = CharField()
    reason = TextField()
    at = CharField()


class QualitativeRun(BaseModel):
    """A Qwen qualitative review batch; `id` is the archive stem (qualitative_<time>_<hex>)."""
    id = CharField(primary_key=True)
    class_name = CharField(null=True, index=True)
    chapter = CharField(null=True)
    problem = CharField(null=True)
    model = CharField(null=True)
    state = CharField(null=True)
    version = IntegerField(default=2)
    created_at = CharField(null=True)
    updated_at = CharField()
    archive = CharField(null=True)
    context = TextField()


class QualitativeReview(BaseModel):
    run = ForeignKeyField(QualitativeRun, backref='reviews', on_delete='CASCADE')
    position = IntegerField()
    student = CharField(index=True)
    student_name = CharField(default='')
    status = CharField()
    overall = DoubleField(null=True)
    suggested_score = DoubleField(null=True)
    max_score = DoubleField(null=True)
    final_score = DoubleField(null=True)
    data = TextField()


MODELS = [Roster, GradingRun, CaseResult, ScoreOverride, QualitativeRun, QualitativeReview]


def default_path():
    import paths
    custom = os.environ.get('SWLAB_DB')
    return Path(custom) if custom else paths.ROOT / 'data' / 'swlab.db'


_ready = None


def connect(path=None):
    """Bind the store to its file and create the tables once; connections are opened per operation."""
    global _ready
    path = Path(path or default_path())
    if database.database != str(path) or _ready != str(path):
        if not database.is_closed():
            database.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        database.init(str(path), pragmas={'journal_mode': 'wal', 'foreign_keys': 1}, timeout=5)
        with database.connection_context():
            database.create_tables(MODELS, safe=True)
        _ready = str(path)
    return database


def session():
    """A short-lived connection; worker threads must not keep the file open after they finish."""
    connect()
    return database.connection_context()


def close():
    if not database.is_closed():
        database.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


# --- roster ---------------------------------------------------------------

def save_roster(class_name, rows):
    """Replace the names of the given students; rows carry student_id and name."""
    stamp = now()
    with session(), database.atomic():
        for row in rows:
            student, name = str(row['student_id']), str(row['name']).strip()
            if not name:
                continue
            (Roster.insert(class_name=class_name, student=student, name=name, updated_at=stamp)
             .on_conflict(conflict_target=[Roster.class_name, Roster.student],
                          update={Roster.name: name, Roster.updated_at: stamp}).execute())


def roster_names(class_name):
    with session():
        return {row.student: row.name for row in Roster.select().where(Roster.class_name == class_name)}


# --- grading runs ---------------------------------------------------------

def save_run(run_id, context, rows, state, error=None, overrides=None, created_at=None, directory=None):
    """Upsert a run and replace its case rows and score adjustments in one transaction."""
    stamp = now()
    with session(), database.atomic():
        values = dict(class_name=context.get('class_name'), chapter=context.get('chapter'),
                      problem=context.get('problem'), mode=context.get('mode'), state=state,
                      updated_at=stamp, directory=str(directory) if directory else None,
                      error=error, context=dumps(context))
        existing = GradingRun.get_or_none(GradingRun.id == run_id)
        if existing is None:
            GradingRun.create(id=run_id, created_at=created_at or stamp, **values)
        else:
            GradingRun.update(**values).where(GradingRun.id == run_id).execute()
        CaseResult.delete().where(CaseResult.run == run_id).execute()
        ScoreOverride.delete().where(ScoreOverride.run == run_id).execute()
        results = [dict(run=run_id, position=index, student=str(row.get('student', '')),
                        student_name=row.get('student_name') or '', case=str(row.get('case', '')),
                        status=str(row.get('status', '')), passed=bool(row.get('passed')), data=dumps(row))
                   for index, row in enumerate(rows)]
        for start in range(0, len(results), 200):
            CaseResult.insert_many(results[start:start + 200]).execute()
        adjustments = [dict(run=run_id, student=student, target=target, previous_score=entry.get('previous_score'),
                            score=entry['score'], reviewer=entry.get('reviewer', ''), reason=entry.get('reason', ''),
                            at=entry.get('at', stamp))
                       for student, targets in (overrides or {}).items()
                       for target, history in targets.items() for entry in history]
        if adjustments:
            ScoreOverride.insert_many(adjustments).execute()


def load_run(run_id):
    """Rebuild the run.json document from the database, or None when the run is unknown."""
    with session():
        run = GradingRun.get_or_none(GradingRun.id == run_id)
        if run is None:
            return None
        rows = [json.loads(result.data) for result in
                CaseResult.select().where(CaseResult.run == run_id).order_by(CaseResult.position)]
        overrides = {}
        for entry in ScoreOverride.select().where(ScoreOverride.run == run_id).order_by(ScoreOverride.id):
            overrides.setdefault(entry.student, {}).setdefault(entry.target, []).append(
                dict(previous_score=entry.previous_score, score=entry.score, reviewer=entry.reviewer,
                     reason=entry.reason, at=entry.at))
    context = json.loads(run.context)
    document = {'kind': 'case_grading', 'created_at': run.created_at, 'updated_at': run.updated_at,
                'state': run.state, 'context': context, 'results': rows, 'error': run.error,
                'directory': run.directory}
    if 'midterm_scoring' in context:
        from midterm_scoring import score_students
        document['score_overrides'] = overrides
        document['scores'] = score_students(rows, context, run.state, overrides)
    return document


def list_runs(class_name=None, chapter=None, problem=None, limit=100):
    """Most recent runs first, with counts so the GUI can label them without loading results."""
    query = GradingRun.select()
    for field, value in ((GradingRun.class_name, class_name), (GradingRun.chapter, chapter), (GradingRun.problem, problem)):
        if value:
            query = query.where(field == value)
    query = query.order_by(GradingRun.created_at.desc(), GradingRun.id.desc()).limit(limit)
    runs = []
    with session():
        for run in query:
            results = CaseResult.select().where(CaseResult.run == run.id)
            runs.append(dict(id=run.id, class_name=run.class_name, chapter=run.chapter, problem=run.problem,
                             mode=run.mode, state=run.state, created_at=run.created_at, updated_at=run.updated_at,
                             directory=run.directory, error=run.error, result_count=results.count(),
                             student_count=results.select(CaseResult.student).distinct().count(),
                             scored='midterm_scoring' in json.loads(run.context)))
    return runs


def delete_run(run_id):
    with session():
        return GradingRun.delete().where(GradingRun.id == run_id).execute()


def import_reports(root=None):
    """Load run.json archives that are not in the database yet; returns the imported run IDs."""
    import paths
    root = Path(root or paths.ROOT / 'reports' / 'case-grading')
    with session():  # a run still marked running was captured mid-way: read its file again
        known = {run.id for run in GradingRun.select(GradingRun.id).where(GradingRun.state != 'running')}
    imported = []
    for path in sorted(root.glob('*/run.json')) if root.is_dir() else []:
        run_id = path.parent.name
        if run_id in known:
            continue
        try:
            document = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict) or document.get('kind') != 'case_grading':
            continue
        if not isinstance(document.get('context'), dict) or not isinstance(document.get('results'), list):
            continue
        save_run(run_id, document['context'], document['results'], document.get('state', 'completed'),
                 document.get('error'), document.get('score_overrides', {}), document.get('created_at'),
                 path.parent)
        imported.append(run_id)
    return imported


# --- qualitative reviews ----------------------------------------------------

def _review_scope(context, rows):
    """class / chapter / problem of a review batch, from its submissions or its rows."""
    for item in [*context.get('submissions', []), *rows]:
        if isinstance(item, dict) and item.get('class_name'):
            return item.get('class_name'), item.get('chapter'), item.get('problem')
    return None, None, None


def save_qualitative(run_id, context, rows, version=2, archive=None, created_at=None):
    """Upsert a review batch and replace its per-student rows in one transaction."""
    stamp = now()
    class_name, chapter, problem = _review_scope(context, rows)
    with session(), database.atomic():
        values = dict(class_name=class_name, chapter=chapter, problem=problem, model=context.get('model'),
                      state=context.get('run_state'), version=version, updated_at=stamp,
                      archive=str(archive) if archive else None, context=dumps(context))
        if QualitativeRun.get_or_none(QualitativeRun.id == run_id) is None:
            QualitativeRun.create(id=run_id, created_at=created_at or stamp, **values)
        else:
            QualitativeRun.update(**values).where(QualitativeRun.id == run_id).execute()
        QualitativeReview.delete().where(QualitativeReview.run == run_id).execute()
        def number(value):
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        reviews = [dict(run=run_id, position=index, student=str(row.get('student', '')),
                        student_name=row.get('student_name') or '', status=str(row.get('status', '')),
                        overall=number(row.get('overall')), suggested_score=number(row.get('suggested_score')),
                        max_score=number(row.get('max_score')), final_score=number(row.get('final_score')), data=dumps(row))
                   for index, row in enumerate(rows)]
        for start in range(0, len(reviews), 200):
            QualitativeReview.insert_many(reviews[start:start + 200]).execute()


def load_qualitative(run_id):
    """The review batch as the qualitative JSON document, or None when unknown."""
    with session():
        run = QualitativeRun.get_or_none(QualitativeRun.id == run_id)
        if run is None:
            return None
        rows = [json.loads(review.data) for review in
                QualitativeReview.select().where(QualitativeReview.run == run_id).order_by(QualitativeReview.position)]
    return {'version': run.version, 'context': json.loads(run.context), 'results': rows,
            'archive': run.archive, 'created_at': run.created_at, 'updated_at': run.updated_at}


def list_qualitative(class_name=None, chapter=None, problem=None, limit=100):
    """Most recent review batches first with status counts for labels."""
    query = QualitativeRun.select()
    for field, value in ((QualitativeRun.class_name, class_name), (QualitativeRun.chapter, chapter), (QualitativeRun.problem, problem)):
        if value:
            query = query.where(field == value)
    query = query.order_by(QualitativeRun.created_at.desc(), QualitativeRun.id.desc()).limit(limit)
    runs = []
    with session():
        for run in query:
            reviews = QualitativeReview.select().where(QualitativeReview.run == run.id)
            runs.append(dict(id=run.id, class_name=run.class_name, chapter=run.chapter, problem=run.problem,
                             model=run.model, state=run.state, version=run.version, created_at=run.created_at,
                             updated_at=run.updated_at, archive=run.archive, student_count=reviews.count(),
                             confirmed=reviews.where(QualitativeReview.status == 'confirmed').count(),
                             proposed=reviews.where(QualitativeReview.status == 'ai_proposed').count(),
                             failed=reviews.where(QualitativeReview.status == 'error').count()))
    return runs


def latest_qualitative_reviews(class_name, chapter, problems):
    """Latest usable assessment per student/problem, across all batches in this exact scope.

    A failed retry must not erase an existing score. Rank by the row's evaluation/
    confirmation time, not the batch time: batches may carry unchanged older rows.
    """
    problems = list(problems)
    if not class_name or not chapter or not problems:
        return []
    problem_filter = QualitativeRun.problem.in_([problem for problem in problems if problem is not None])
    if None in problems:
        problem_filter |= QualitativeRun.problem.is_null()
    query = (QualitativeReview.select(QualitativeReview, QualitativeRun).join(QualitativeRun)
             .where((QualitativeRun.class_name == class_name) & (QualitativeRun.chapter == chapter)
                    & problem_filter))
    latest = {}
    def timestamp(value):
        try:
            return datetime.fromisoformat(value).timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            return 0
    with session():
        for review in query:
            row = json.loads(review.data)
            run = review.run
            # Imported archives can contain rows from more than one assignment.
            if (row.get('class_name', run.class_name), row.get('chapter', run.chapter),
                    row.get('problem', run.problem)) != (class_name, chapter, run.problem):
                continue
            usable = row.get('status') in ('ai_proposed', 'confirmed') and review.suggested_score is not None
            stamp = row.get('reviewed_at') or row.get('created_at') or run.created_at
            rank = (usable, timestamp(stamp), timestamp(run.updated_at), run.id, review.position)
            key = (review.student, run.problem)
            if key not in latest or rank > latest[key][0]:
                latest[key] = (rank, dict(row, student=review.student, problem=run.problem,
                                         run_id=run.id, saved_at=stamp))
    return [value[1] for value in latest.values()]


def import_qualitative(root=None):
    """Load qualitative_*.json archives not yet in the database; returns the imported run IDs."""
    import paths
    root = Path(root or paths.ROOT / 'reports')
    with session():  # a batch still marked running was captured mid-way: read its file again
        known = {run.id for run in QualitativeRun.select(QualitativeRun.id).where(QualitativeRun.state != 'running')}
    imported = []
    for path in sorted(root.glob('qualitative_*.json')) if root.is_dir() else []:
        if path.stem in known:
            continue
        try:
            document = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict) or document.get('version') not in (1, 2):
            continue
        if not isinstance(document.get('context'), dict) or not isinstance(document.get('results'), list):
            continue
        created = next((row.get('created_at') for row in document['results']
                        if isinstance(row, dict) and isinstance(row.get('created_at'), str)), None)
        save_qualitative(path.stem, document['context'], document['results'], document['version'], path,
                         created or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
        imported.append(path.stem)
    return imported


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='SWLAB SQLite store')
    commands = parser.add_subparsers(dest='command', required=True)
    load = commands.add_parser('import', help='reports 의 run.json 과 qualitative_*.json 을 DB로 가져오기')
    load.add_argument('--root', type=Path, help='reports 폴더 경로 (기본: reports)')
    commands.add_parser('runs', help='저장된 채점 실행 목록')
    commands.add_parser('reviews', help='저장된 정성평가 실행 목록')
    options = parser.parse_args(argv)
    if options.command == 'import':
        root = options.root
        imported = import_reports(root / 'case-grading' if root else None) + import_qualitative(root)
        print(f'{len(imported)}개 실행을 가져왔습니다 -> {default_path()}')
        for run_id in imported:
            print('  ' + run_id)
    elif options.command == 'runs':
        for run in list_runs():
            print(f"{run['id']}  {run['class_name']}  {run['chapter']}/{run['problem']}  {run['state']}  "
                  f"학생 {run['student_count']}명 · 결과 {run['result_count']}건")
    elif options.command == 'reviews':
        for run in list_qualitative():
            print(f"{run['id']}  {run['class_name']}  {run['chapter']}/{run['problem']}  {run['state']}  "
                  f"학생 {run['student_count']}명 · 확정 {run['confirmed']}명 · 제안 {run['proposed']}명 · 실패 {run['failed']}명")


if __name__ == '__main__':
    main()
