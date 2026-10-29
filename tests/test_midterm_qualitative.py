from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support  # noqa: E401,F401  isolates the SQLite store
from midterm import ALL_TARGETS, TARGETS
from midterm_scoring import POINTS
from midterm_qualitative import load_problems, problem_statement, scaled_rubric, source_patterns, qualitative_preset
from qualitative import DEFAULT_RUBRIC, collect_sources


class MidtermQualitativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_problems()

    def test_statements_cover_every_exam_file_and_share_context_once(self):
        self.assertEqual(set(self.data['problems']), set(TARGETS))
        for target in TARGETS:
            text = problem_statement(target, self.data)
            self.assertIn(f'· {target} · {POINTS[target]}점]', text)
        full = problem_statement(ALL_TARGETS, self.data)
        for target in TARGETS:
            self.assertIn(f'· {target} ·', full)
        self.assertEqual(full.count(self.data['shared']['library'].strip()), 1)
        self.assertEqual(full.count(self.data['shared']['extension'].strip()), 1)
        self.assertLess(len(full), 30000)
        update = problem_statement('bookupdate.c', self.data)
        self.assertLess(update.index('도서 레코드 정보'), update.index('bookupdate.c'))
        self.assertNotIn('sortedbookquery.c', update)
        self.assertIn('옵션은 명령어의 인자값으로 전달', problem_statement('copy.c', self.data))
        with self.assertRaises(ValueError):
            problem_statement('main.c', self.data)

    def test_rubric_keeps_dcucode_axes_separate_from_exam_points(self):
        for points in [*POINTS.values(), sum(POINTS.values())]:
            rules = scaled_rubric(points)
            self.assertEqual([r['max_score'] for r in rules], [10] * 7)
            self.assertEqual([r['id'] for r in rules], [r['id'] for r in DEFAULT_RUBRIC])
            self.assertTrue(all(r['max_score'] > 0 for r in rules))
        self.assertEqual([r['max_score'] for r in DEFAULT_RUBRIC], [10] * 7)
        self.assertIn('대출 유무 True/1은 대출 가능', problem_statement('bookupdate.c', self.data))

    def test_preset_limits_sources_to_exam_files_and_headers(self):
        preset = qualitative_preset('copy.c', self.data)
        self.assertEqual(preset['sources'], ['copy.c', '*.h'])
        self.assertEqual(preset['points'], 10)
        self.assertIn('2쪽', preset['summary'])
        self.assertIn('copy.c', preset['title'])
        everything = qualitative_preset(ALL_TARGETS, self.data)
        self.assertEqual(everything['sources'], [*TARGETS, '*.h'])
        self.assertEqual(everything['points'], 75)
        self.assertIn('2, 3, 4, 5, 6쪽', everything['summary'])
        with self.assertRaises(ValueError):
            qualitative_preset('main.c', self.data)

    def test_collect_sources_sends_only_the_selected_exam_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('copy.c', 'bookcreate.c', 'bookcreate1.c', 'book.h', 'fscan.c', 'Searchbook.c'):
                (root / name).write_text(name, encoding='utf-8')
            (root / 'main').write_bytes(b'\x7fELF')
            (root / 'db.dat').write_bytes(b'records')
            self.assertEqual(set(collect_sources(root, source_patterns('copy.c'))), {'copy.c', 'book.h'})
            self.assertEqual(set(collect_sources(root, source_patterns(ALL_TARGETS))), {'copy.c', 'bookcreate.c', 'book.h'})
            # Headers alone, or a file whose case differs from the paper, are not a submission of that problem.
            with self.assertRaises(ValueError) as error:
                collect_sources(root, source_patterns('searchbook.c'))
            self.assertIn('searchbook.c', str(error.exception))
            self.assertEqual(set(collect_sources(root)), {'copy.c', 'bookcreate.c', 'bookcreate1.c', 'book.h', 'fscan.c', 'Searchbook.c'})

    def test_problem_file_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'problems.json'
            path.write_text('{"shared": {}, "problems": {"copy.c": {"pages": [2], "text": "x"}}}', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_problems(path)
            broken = dict(self.data)
            broken['problems'] = {**self.data['problems'], 'copy.c': {'pages': [2], 'shared': ['missing'], 'text': 'x'}}
            import json
            path.write_text(json.dumps(broken, ensure_ascii=False), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_problems(path)


if __name__ == '__main__':
    unittest.main()
