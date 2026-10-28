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


MODELS = [Roster, GradingRun, CaseResult, ScoreOverride]


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
    with session():
        known = {run.id for run in GradingRun.select(GradingRun.id)}
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


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='SWLAB SQLite store')
    commands = parser.add_subparsers(dest='command', required=True)
    load = commands.add_parser('import', help='reports/case-grading 의 run.json 을 DB로 가져오기')
    load.add_argument('--root', type=Path, help='run.json 폴더들의 상위 경로 (기본: reports/case-grading)')
    commands.add_parser('runs', help='저장된 채점 실행 목록')
    options = parser.parse_args(argv)
    if options.command == 'import':
        imported = import_reports(options.root)
        print(f'{len(imported)}개 실행을 가져왔습니다 -> {default_path()}')
        for run_id in imported:
            print('  ' + run_id)
    elif options.command == 'runs':
        for run in list_runs():
            print(f"{run['id']}  {run['class_name']}  {run['chapter']}/{run['problem']}  {run['state']}  "
                  f"학생 {run['student_count']}명 · 결과 {run['result_count']}건")


if __name__ == '__main__':
    main()
