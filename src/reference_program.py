"""Snapshot the explicitly selected files of one instructor reference program."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from paths import safe_path


@dataclass(frozen=True)
class ReferenceFile:
    name: str
    content: bytes


@dataclass(frozen=True)
class ReferenceProgram:
    root: Path
    files: tuple[ReferenceFile, ...]
    entry: str

    @property
    def manifest(self):
        return [{'path': file.name, 'sha256': hashlib.sha256(file.content).hexdigest()}
                for file in self.files]

    @property
    def digest(self):
        value = {'entry': self.entry, 'files': self.manifest}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()

    @property
    def runner_config(self):
        config = {'mode': 'docker', 'timeout': 15}
        if self.entry.endswith('.c'):
            headers = sorted({str(Path(file.name).parent.as_posix())
                              for file in self.files if file.name.endswith('.h')})
            config['sources'] = [file.name for file in self.files if file.name.endswith('.c')]
            config['cflags'] = ['-Wall', '-Wextra', '-I.', *['-I' + path for path in headers if path != '.']]
        return config

    def copy_to(self, directory):
        root = Path(directory)
        root.mkdir(parents=True)
        for file in self.files:
            target = safe_path(root, file.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.content)


def snapshot_reference(solution, entry=None):
    if isinstance(solution, ReferenceProgram):
        return solution
    selected = [solution] if isinstance(solution, (str, Path)) else list(solution)
    if not selected:
        raise ValueError('교수자 기준 코드 파일을 선택하세요.')
    paths = []
    for value in selected:
        path = Path(value)
        if path.is_symlink() or not path.is_file() or path.suffix not in ('.c', '.h', '.py'):
            raise ValueError('기준 코드는 존재하는 .c, .h, .py 파일을 선택하세요. 심볼릭 링크는 지원하지 않습니다.')
        path = path.resolve()
        if path not in paths:
            paths.append(path)
    languages = {path.suffix for path in paths if path.suffix in ('.c', '.py')}
    if len(languages) != 1:
        raise ValueError('한 프로그램의 C 소스와 헤더 또는 Python 파일들을 함께 선택하세요. 헤더만 선택하거나 C/Python을 섞을 수 없습니다.')
    try:
        root = Path(os.path.commonpath([str(path.parent) for path in paths]))
    except ValueError as error:
        raise ValueError('기준 코드 파일은 같은 드라이브에 두세요.') from error
    names = {path.relative_to(root).as_posix(): path for path in paths}
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('대소문자만 다른 기준 코드 파일 이름은 지원하지 않습니다.')
    executable = [name for name in names if Path(name).suffix in ('.c', '.py')]
    if entry is None:
        entry = next((name for name in executable if Path(name).name in ('main.c', 'main.py')), executable[0])
    if entry not in executable:
        raise ValueError('실행 기준 파일은 선택한 C 또는 Python 소스여야 합니다.')
    files = tuple(ReferenceFile(name, path.read_bytes()) for name, path in sorted(names.items()))
    return ReferenceProgram(root, files, entry)
