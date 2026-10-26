"""Resolve explicit candidate paths; persist instructor corrections."""
from pathlib import Path
import yaml
from core.manifest import read_yaml, fields, strings, relative_path
from core.record import atomic_text
from paths import safe_path


def load_layout(path):
    if path is None or not Path(path).exists():
        return {'candidates': {}, 'overrides': {}}
    data = fields(read_yaml(path), 'candidates overrides', 'layout')
    for key in ('candidates', 'overrides'):
        if not isinstance(data.get(key, {}), dict):
            raise ValueError(f'layout.{key} must be a mapping')
    for problem, candidates in data.get('candidates', {}).items():
        strings(candidates, f'candidates.{problem}', paths=True)
    for student, overrides in data.get('overrides', {}).items():
        if not isinstance(overrides, dict):
            raise ValueError(f'overrides.{student} must be a mapping')
        for path_value in overrides.values():
            relative_path(path_value)
    # YAML may parse numeric student IDs as integers.
    data['overrides'] = {str(k): v for k, v in data.get('overrides', {}).items()}
    return data


def resolve_submission(root, student, problem, layout=None):
    root = Path(root).resolve()
    layout = layout or {}
    override = layout.get('overrides', {}).get(str(student), {}).get(problem.id)
    paths = [override] if override is not None else layout.get('candidates', {}).get(problem.id, problem.data['submit']['paths'])
    attempted = []
    for candidate in paths:
        candidate = relative_path(candidate)
        folder = safe_path(root, candidate)
        attempted.append(candidate)
        if folder.is_dir():
            for filename in problem.data['submit']['files']:
                if safe_path(folder, filename).is_file():
                    return {'status': 'resolved', 'path': str(folder), 'resolved_path': candidate,
                            'matched_file': filename, 'method': 'override' if override is not None else 'candidate'}
    return {'status': 'unresolved', 'message': f'No allowed source file found in: {", ".join(attempted)}', 'attempted': attempted}


def save_override(path, student, problem, relative):
    relative = relative_path(relative)
    data = load_layout(path)
    data.setdefault('overrides', {}).setdefault(str(student), {})[problem.id] = relative
    atomic_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
