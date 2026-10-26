"""One grading pipeline shared by the desktop and command line."""
from copy import deepcopy
from datetime import datetime
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from core.manifest import load_problem, is_link
from core.record import now, save_run
from core.resolver import load_layout, resolve_submission
from grader import Grader
from paths import ROOT


def command_output(command):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'Command failed: {command[0]}')
    return result.stdout.strip()


def environment(mode, image, language):
    if mode not in ('docker', 'windows', 'linux', 'wsl'):
        raise ValueError(f'Unknown execution mode: {mode}')
    result = {'mode': mode, 'host_python': sys.version.split()[0]}
    if mode == 'docker':
        command_output(['docker', 'info', '--format', '{{.ServerVersion}}'])
        result['image'] = image
        result['image_id'] = command_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'])
        result['runtime'] = command_output(['docker', 'run', '--rm', '--network', 'none',
            result['image_id'], 'gcc' if language == 'c' else 'python3', '--version'])
    elif mode == 'wsl':
        result['runtime'] = command_output(['wsl', '--', 'gcc' if language == 'c' else 'python3', '--version'])
    elif language == 'c':
        result['runtime'] = command_output(['gcc', '--version'])
    else:
        result['runtime'] = sys.version
    return result


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlinks are not supported: {path.name}')
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
            file_hash = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    file_hash.update(block)
            digest.update(file_hash.digest())
    return digest.hexdigest()


def copy_submission(source, destination):
    # Reject links before copying, including directory links/junctions on Windows.
    if is_link(Path(source)):
        raise ValueError('Submission root links are not supported')
    for folder, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__')]
        for name in dirs + files:
            path = Path(folder) / name
            if is_link(path):
                raise ValueError(f'Submission links are not supported: {name}')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.git', '__pycache__'))


def git_details(root):
    if not (Path(root) / '.git').exists():
        return {}
    try:
        prefix = ['git', '-C', str(root)]
        return {'commit': command_output(prefix + ['rev-parse', 'HEAD']),
                'committed_at': command_output(prefix + ['log', '-1', '--format=%cI']),
                'dirty': bool(command_output(prefix + ['status', '--porcelain']))}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'metadata_error': str(exc)}


def tool_fingerprint():
    digest = hashlib.sha256()
    # Do not descend into local student repositories under src/origin.
    for path in sorted([*(ROOT / 'src').glob('*.py'), *(ROOT / 'src/core').glob('*.py')]):
        digest.update(path.relative_to(ROOT).as_posix().encode('utf-8') + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_batch(problem_path, submissions, records_dir=None, mode='docker', image='grader-image',
              layout_path=None, progress=None, cancelled=None):
    problem = load_problem(problem_path)
    layout_path = Path(layout_path) if layout_path else problem.layout_path
    layout = load_layout(layout_path)
    if not submissions:
        raise ValueError('No students selected')
    ids = [str(s['student_id']) for s in submissions]
    if len(set(ids)) != len(ids) or any(not i.strip() for i in ids):
        raise ValueError('Student IDs must be nonempty and unique')
    # Infrastructure errors abort before assigning any student score.
    env = environment(mode, image, problem.data['submit']['language'])
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:10]
    directory = Path(records_dir or ROOT / 'records').resolve() / problem.id / run_id
    if any(directory.is_relative_to(Path(s['path']).resolve()) for s in submissions) or directory.is_relative_to(problem.path.parent / 'cases'):
        raise ValueError('Records must be stored outside submission and case directories')
    directory.mkdir(parents=True, exist_ok=False)
    archive = directory / 'run.json'
    inputs = directory / 'inputs'
    inputs.mkdir()
    shutil.copy2(problem.path, inputs / 'problem.yaml')
    # Retain exact grading inputs so later edits cannot change this run.
    copy_submission(problem.path.parent / 'cases', inputs / 'cases')
    if layout_path.exists():
        shutil.copy2(layout_path, inputs / 'layout.yaml')
        layout = load_layout(inputs / 'layout.yaml')
    problem = load_problem(inputs / 'problem.yaml')
    run = {'schema_version': 1, 'run_id': run_id, 'state': 'running', 'created_at': now(),
           'problem': problem.data, 'inputs_sha256': tree_hash(inputs), 'environment': env,
           'tool': {**git_details(ROOT), 'source_sha256': tool_fingerprint()}, 'layout': layout, 'results': []}
    for student_id, submission in zip(ids, submissions):
        run['results'].append({'student_id': student_id, 'class_name': submission.get('class_name', Path(submission['path']).parent.name),
                               'problem_id': problem.id, 'submission_root': str(Path(submission['path']).resolve()),
                               'status': 'pending', 'auto_score': None,
                               'final_score': None, 'max_score': problem.total, 'cases': [],
                               'case_count': len(problem.cases), 'passed_cases': 0})
    save_run(archive, run)
    grader = Grader()
    config = {**problem.config, 'mode': mode, 'image': env.get('image_id', image)}
    try:
        for index, submission in enumerate(submissions):
            if cancelled and cancelled():
                run['state'] = 'cancelled'
                break
            row = run['results'][index]
            try:
                resolution = resolve_submission(submission['path'], row['student_id'], problem, layout)
                row['submission'] = resolution
                if resolution['status'] != 'resolved':
                    row.update(status='unresolved', message=resolution['message'])
                else:
                    provenance = git_details(submission['path'])
                    snapshot = directory / 'submissions' / f'{index + 1:04d}'
                    snapshot.parent.mkdir(exist_ok=True)
                    copy_submission(resolution['path'], snapshot)
                    resolution.update(provenance, sha256=tree_hash(snapshot), snapshot=snapshot.relative_to(directory).as_posix())
                    if problem.data.get('due') and provenance.get('committed_at') and not provenance.get('dirty'):
                        seconds = (datetime.fromisoformat(provenance['committed_at']) - datetime.fromisoformat(problem.data['due'])).total_seconds()
                        resolution['late_hours'] = max(0, seconds / 3600)
                        resolution['lateness_basis'] = 'repository_commit_time'
                    results = grader.grade_student(snapshot, problem.cases, {**config, 'target_file': resolution['matched_file']})
                    row['cases'] = results
                    weights = {c['name']: c['points'] for c in problem.cases}
                    for case in results:
                        case['max_score'] = weights.get(case['case'], 0)
                        case['points'] = case['max_score'] if case['passed'] else 0
                    row['passed_cases'] = sum(c['passed'] for c in results)
                    if any(c['status'] in ('error', 'missing', 'no_tests') for c in results):
                        row.update(status='error', message='Grading could not be completed. Inspect case details.')
                    else:
                        score = round(math.fsum(c['points'] for c in results), 8)
                        row.update(status='graded', auto_score=score, final_score=score)
            except Exception as exc:
                row.update(status='error', message=str(exc), auto_score=None, final_score=None)
            row['graded_at'] = now()
            # Persistence is outside the per-student exception boundary: failed writes stop the run.
            save_run(archive, run)
            if progress:
                progress(index + 1, deepcopy(row), archive)
        else:
            run['state'] = 'completed'
        for row in run['results']:
            if row['status'] == 'pending':
                row['status'] = 'not_run'
        run['finished_at'] = now()
        save_run(archive, run)
    except Exception as exc:
        run.update(state='error', error=str(exc), finished_at=now())
        try:
            save_run(archive, run)
        except OSError:
            pass
        raise OSError(f'{exc} (record: {archive})') from exc
    return archive, run
