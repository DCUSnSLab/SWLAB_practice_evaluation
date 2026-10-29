from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from qualitative_rubric import (AXES, LEGACY_SCORING_VERSION, RESOURCE_IDS, SCORING_VERSION, compute_scores,
                                resource_scope)


class QualitativeRubricTests(unittest.TestCase):
    def scores(self, core=(8, 6, 4, 10), **resources):
        return [dict(id=axis, score=score, applicable=True) for axis, score in zip(AXES, core)] + [
            dict(id=rid, score=resources.get(kind), applicable=kind in resources)
            for kind, rid in RESOURCE_IDS.items()]

    def test_no_resources_uses_exact_dcucode_formulas(self):
        for points in (5, 10, 20, 75, 100):
            result = compute_scores(self.scores(), points)
            self.assertEqual(result['overall'], 70)
            self.assertEqual(result['suggested_partial_score'], -(-points * (8 + 10) // 20))
            self.assertIsNone(result['resource_score'])
            self.assertEqual(result['partial_denominator'], 20)

    def test_only_applicable_resources_are_averaged_and_affect_partial_points(self):
        result = compute_scores(self.scores(files=2), 75)
        self.assertEqual(result['resource_score'], 2)
        self.assertEqual(result['overall'], 60)
        self.assertEqual(result['suggested_score'], 50)
        self.assertEqual(result['partial_denominator'], 30)
        result = compute_scores(self.scores(files=2, memory=10), 75)
        self.assertEqual(result['resource_score'], 6)
        self.assertEqual(result['suggested_score'], 60)
        self.assertEqual(result['overall'], 68)

    def test_algorithm_readability_affect_quality_but_not_partial_score(self):
        low = compute_scores(self.scores(core=(8, 0, 0, 10), files=6), 75)
        high = compute_scores(self.scores(core=(8, 10, 10, 10), files=6), 75)
        self.assertEqual(low['suggested_score'], high['suggested_score'])
        self.assertLess(low['overall'], high['overall'])

    def test_zero_full_and_rounding(self):
        for core, resource, expected in [((0,)*4, 0, 0), ((10,)*4, 10, 75)]:
            result = compute_scores(self.scores(core=core, files=resource), 75)
            self.assertEqual(result['suggested_score'], expected)
        result = compute_scores(self.scores(core=(1, 10, 10, 0)), 10)
        self.assertEqual(result['suggested_score'], 1)
        for points in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError): compute_scores(self.scores(), points)

    def test_every_fraction_rounds_up_without_float_error(self):
        # 22/40*100 is 55.00000000000001 in floating point; a naive ceil would give 56.
        self.assertEqual(compute_scores(self.scores(core=(6, 5, 5, 6)), 100)['overall'], 55)
        self.assertEqual(compute_scores(self.scores(core=(6, 5, 5, 6)), 100)['suggested_score'], 60)
        result = compute_scores(self.scores(core=(8, 5, 5, 7), files=7), 10)
        self.assertEqual((result['suggested_score'], result['scoring_version']), (8, SCORING_VERSION))
        result = compute_scores(self.scores(core=(8, 5, 5, 7), files=6, memory=7), 100)
        self.assertEqual((result['resource_score'], result['suggested_score'], result['overall']), (7, 74, 64))
        result = compute_scores(self.scores(core=(8, 6, 4, 9), files=7), 100)
        self.assertEqual((result['overall'], result['suggested_score']), (68, 80))

    def test_legacy_version_reproduces_half_to_even_rounding(self):
        legacy = compute_scores(self.scores(core=(8, 5, 5, 7), files=6, memory=7), 100, LEGACY_SCORING_VERSION)
        self.assertEqual((legacy['resource_score'], legacy['suggested_score'], legacy['overall'], legacy['scoring_version']),
                         (6, 70, 62, LEGACY_SCORING_VERSION))
        self.assertEqual(compute_scores(self.scores(core=(1, 10, 10, 0)), 10, LEGACY_SCORING_VERSION)['suggested_score'], 0)
        with self.assertRaises(ValueError):
            compute_scores(self.scores(), 100, 'unknown')

    def test_required_resource_cannot_be_exempted_by_missing_implementation(self):
        examples = [('파일을 읽고 복사한다.', 'files'),
                    ('동적 할당으로 배열을 생성하고 해제한다.', 'memory'),
                    ('자식 프로세스를 만들고 종료를 기다린다.', 'processes')]
        for problem, kind in examples:
            with self.subTest(problem=problem):
                scope = resource_scope(problem, {'main.c':'int main(){return 0;}'})
                self.assertEqual([k for k, v in scope.items() if v['applicable']], [kind])

    def test_console_only_and_explicit_nonuse_are_excluded(self):
        for problem in ('정수를 입력받아 합을 화면에 출력한다.',
                        '파일을 읽지 않는다. 동적 할당을 하지 않는다. 프로세스를 만들지 않는다.',
                        'Do not read files. Print the sum.'):
            scope = resource_scope(problem, {'main.c':'scanf("%d", &n); printf("%d", n);'})
            self.assertFalse(any(v['applicable'] for v in scope.values()), problem)

    def test_error_condition_does_not_cancel_required_file_management(self):
        scope = resource_scope('파일을 읽고 파일이 없으면 오류를 출력한다.', {})
        self.assertTrue(scope['files']['applicable'])

    def test_actual_use_is_checked_but_comments_and_strings_are_ignored(self):
        code = '// malloc(32); fork();\n/* free(p); */\nprintf("fopen(x) fork() malloc(2)");'
        self.assertFalse(any(v['applicable'] for v in resource_scope('합을 출력', {'main.c':code}).values()))
        for code, kind in [('fopen("data", "r");', 'files'), ('p=malloc(32);', 'memory'),
                           ('pid=fork(); waitpid(pid, 0, 0);', 'processes')]:
            scope = resource_scope('합을 출력', {'main.c':code})
            self.assertEqual([k for k, v in scope.items() if v['applicable']], [kind])

    def test_overrides_and_validation(self):
        scope = resource_scope('파일을 읽는다.', {'main.c':'malloc(10);'},
                               {'files':'exclude','memory':'exclude','processes':'include'})
        self.assertEqual([k for k, v in scope.items() if v['applicable']], ['processes'])
        self.assertIn('교수자 지정', scope['files']['reason'])
        for policy in ({'files':'bogus'}, {'unknown':'auto'}, ['auto']):
            with self.assertRaises(ValueError): resource_scope('', {}, policy)


if __name__ == '__main__': unittest.main()
