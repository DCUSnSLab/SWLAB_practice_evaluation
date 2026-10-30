"""Point the SQLite store at a throwaway file so tests never touch data/swlab.db."""
import atexit
import os
from pathlib import Path
import tempfile
import unittest

_directory = tempfile.TemporaryDirectory(prefix='swlab-test-db-')
os.environ['SWLAB_DB'] = os.path.join(_directory.name, 'swlab.db')


def _cleanup():
    try:
        import db
        db.close()
    except Exception:
        pass
    try:
        _directory.cleanup()
    except OSError:
        pass


atexit.register(_cleanup)


def isolate(case):
    """Give one test its own database file so saved rows never leak between tests."""
    directory = tempfile.TemporaryDirectory(prefix='swlab-test-db-')
    previous = os.environ.get('SWLAB_DB')
    os.environ['SWLAB_DB'] = os.path.join(directory.name, 'swlab.db')

    def restore():
        try:
            import db
            db.close()
        except Exception:
            pass
        if previous is None:
            os.environ.pop('SWLAB_DB', None)
        else:
            os.environ['SWLAB_DB'] = previous
        try:
            directory.cleanup()
        except OSError:
            pass
    case.addCleanup(restore)


# The exam suite is kept off the public repo, so a fresh clone has no copy of it.
MIDTERM_SUITE = Path(__file__).resolve().parents[1] / 'assignments/system/2026/midterm'
needs_midterm_suite = unittest.skipUnless((MIDTERM_SUITE / 'scenarios.json').exists(),
                                          'assignments/system/ midterm suite is not in this checkout')
