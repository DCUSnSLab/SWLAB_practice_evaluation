"""Validate instructor-authored problem contracts before running student code."""
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path, PureWindowsPath
import re
import stat

import yaml
from paths import safe_path, parse_args


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int)) or key in result:
            raise ValueError(f'Duplicate or invalid YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_yaml(path):
    try:
        value = yaml.load(Path(path).read_text(encoding='utf-8-sig'), Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid YAML: {exc}') from exc
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected a YAML object')
    return value


def fields(value, allowed, name):
    if not isinstance(value, dict):
        raise ValueError(f'{name}: expected an object')
    extra = set(value) - set(allowed.split())
    if extra:
        raise ValueError(f'{name}: unknown fields {sorted(map(str, extra))}')
    return value


def number(value, name, minimum=0, maximum=1_000_000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name}: expected a finite number between {minimum} and {maximum}')
    return float(value)


def relative_path(value):
    if not isinstance(value, str) or not value.strip() or '\x00' in value or ':' in value:
        raise ValueError('Expected a nonempty relative path')
    path = Path(value.replace('\\', '/'))
    if path.is_absolute() or PureWindowsPath(value).drive or '..' in path.parts:
        raise ValueError(f'Path must be relative and cannot contain ..: {value}')
    return path.as_posix()


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def strings(value, name, paths=False):
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise ValueError(f'{name}: expected a nonempty string list')
    return [relative_path(v) for v in value] if paths else value


@dataclass
class Problem:
    path: Path
    data: dict
    cases: list
    config: dict

    @property
    def id(self):
        return self.data['id']

    @property
    def total(self):
        return self.data['scoring']['total']

    @property
    def layout_path(self):
        return self.path.parent / 'layout.local.yaml'


def load_problem(path):
    path = Path(path).resolve()
    data = read_yaml(path)
    fields(data, 'version id title statement source submit build run scoring due', 'problem')
    if type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('problem.version must be 1')
    if not isinstance(data.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}', data['id']):
        raise ValueError('problem.id: use 1–100 letters, numbers, hyphens or underscores')
    for key in ('title', 'statement'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'problem.{key} is required')
    if 'source' in data and not isinstance(data['source'], str):
        raise ValueError('problem.source must be text')
    submit = fields(data.get('submit'), 'language files paths', 'submit')
    language = submit.get('language')
    suffix = {'c': '.c', 'python': '.py'}.get(language) if isinstance(language, str) else None
    if not suffix:
        raise ValueError('submit.language must be c or python')
    submit['files'] = strings(submit.get('files'), 'submit.files', paths=True)
    if any(Path(f).suffix != suffix for f in submit['files']):
        raise ValueError('submit.files must match submit.language')
    submit['paths'] = strings(submit.get('paths', ['.']), 'submit.paths', paths=True)
    build = fields(data.get('build', {}), 'sources flags', 'build')
    config = {}
    if 'sources' in build:
        config['sources'] = strings(build['sources'], 'build.sources', paths=True)
    if 'flags' in build:
        if not isinstance(build['flags'], list) or not all(isinstance(f, str) for f in build['flags']):
            raise ValueError('build.flags must be a string list')
        config['cflags'] = build['flags']
    run = fields(data.get('run', {}), 'timeout_sec compare tolerance', 'run')
    config['timeout'] = number(run.get('timeout_sec', 10), 'timeout_sec', .01, 300)
    comparison = run.get('compare', 'trimmed')
    if comparison not in ('exact', 'trimmed', 'tokens', 'numeric'):
        raise ValueError('run.compare must be exact, trimmed, tokens or numeric')
    tolerance = number(run.get('tolerance', 1e-6), 'tolerance', 0, 1)
    scoring = fields(data.get('scoring'), 'total cases manual_override', 'scoring')
    total = number(scoring.get('total'), 'scoring.total', .01)
    points = scoring.get('cases')
    if not isinstance(points, dict) or not points:
        raise ValueError('scoring.cases must contain at least one named case')
    for name, weight in points.items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', name):
            raise ValueError('Case names must contain letters, numbers, hyphens or underscores')
        number(weight, f'points for {name}')
    if not math.isclose(math.fsum(points.values()), total, rel_tol=0, abs_tol=1e-8):
        raise ValueError('Case points must add up to scoring.total')
    if scoring.get('manual_override', 'allowed') not in ('allowed', 'forbidden'):
        raise ValueError('scoring.manual_override must be allowed or forbidden')
    if data.get('due') is not None:
        due = data['due'] if isinstance(data['due'], datetime) else datetime.fromisoformat(str(data['due']))
        if due.tzinfo is None:
            raise ValueError('due must include a timezone, e.g. +09:00')
        data['due'] = due.isoformat()
    cases = []
    for name, weight in points.items():
        folder = safe_path(path.parent, 'cases', name)
        if not folder.is_dir():
            raise ValueError(f'Missing case directory: {name}')
        metadata = folder / 'case.yaml'
        case = read_yaml(metadata) if metadata.is_file() else {}
        fields(case, 'args expected stderr files exit_code', f'case {name}')
        for key, filename in (('input', 'stdin.txt'), ('expected', 'expected.txt')):
            file = folder / filename
            if file.is_file():
                if key in case:
                    raise ValueError(f'{name}: specify {key} once, in a file or in YAML')
                case[key] = file.read_text(encoding='utf-8-sig')
        args_file = folder / 'args.txt'
        if args_file.is_file():
            if 'args' in case:
                raise ValueError(f'{name}: specify args once')
            case['args'] = parse_args(args_file.read_text(encoding='utf-8-sig'))
        args = case.get('args', [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f'{name}: args must be a string list')
        for key in ('expected', 'stderr'):
            if key in case and not isinstance(case[key], str):
                raise ValueError(f'{name}: {key} must be text')
        if comparison == 'numeric' and 'expected' in case:
            tokens = case['expected'].split()
            try:
                valid = bool(tokens) and all(math.isfinite(float(t)) for t in tokens)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f'{name}: numeric expected output must contain finite numbers')
        if 'exit_code' in case and (type(case['exit_code']) is not int or not 0 <= case['exit_code'] <= 255):
            raise ValueError(f'{name}: exit_code must be an integer from 0 to 255')
        files = case.get('files', {})
        if not isinstance(files, dict):
            raise ValueError(f'{name}: files must be a mapping of paths to expected text')
        for filename, expected in files.items():
            relative_path(filename)
            if not isinstance(expected, str):
                raise ValueError(f'{name}: expected file content must be text')
        if 'expected' not in case and 'stderr' not in case and not files:
            raise ValueError(f'{name}: at least one output, stderr or file assertion is required')
        fixture = folder / 'files'
        if fixture.exists():
            if not fixture.is_dir() or is_link(fixture):
                raise ValueError(f'{name}: files must be a directory')
            for item in fixture.rglob('*'):
                if is_link(item):
                    raise ValueError(f'{name}: fixture symlinks are not supported')
                if item.suffix.lower() in ('.c', '.h', '.py', '.cpp', '.hpp', '.exe', '.dll'):
                    raise ValueError(f'{name}: fixture cannot replace executable/source files: {item.name}')
            case.update(path=str(folder), fixture_root='files')
        case.update(name=name, points=weight, args=args, comparison='trim' if comparison == 'trimmed' else comparison, tolerance=tolerance)
        cases.append(case)
    return Problem(path, data, cases, config)
