"""Distinguish absent/blank submissions from failures to read or evaluate them."""
from pathlib import Path


class SubmissionAbsent(ValueError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def usable_sources(sources, required=()):
    if required:
        primary = {name: sources[name] for name in required if name in sources}
        if not primary:
            raise SubmissionAbsent('missing_file', '평가 대상 파일이 없습니다: ' + ', '.join(required))
    else:
        primary = {name: text for name, text in sources.items() if Path(name).suffix.lower() not in ('.h', '.hpp')}
        if not primary:
            raise SubmissionAbsent('no_sources', '평가할 C/Python 소스 파일이 없습니다.')
    if not any(text.strip() for text in primary.values()):
        raise SubmissionAbsent('empty_file', '평가 대상 파일이 비어 있습니다: ' + ', '.join(primary))
    # Never ask the model to cite lines from empty auxiliary files either.
    return {name: text for name, text in sources.items() if text.strip()}


def source_is_blank(path):
    """Check whitespace/BOM-only files without decoding valid legacy source encodings."""
    with Path(path).open('rb') as stream:
        first = True
        while chunk := stream.read(65536):
            if first:
                chunk = chunk.removeprefix(b'\xef\xbb\xbf')
                first = False
            if chunk.strip():
                return False
    return True
