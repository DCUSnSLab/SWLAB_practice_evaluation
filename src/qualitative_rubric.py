"""DCUCode's four axes, extended with applicable resource lifecycle checks."""
import re

SCORING_VERSION = 'dcucode_resources_v1'
AXES = ('correctness', 'algorithm', 'readability', 'problem_understanding')
RESOURCE_IDS = {'files': 'resource_files', 'memory': 'resource_memory', 'processes': 'resource_processes'}
AXIS_CHECKLISTS = {
    'correctness': ['변수·배열의 초기화 완전성', '리턴값·종료 조건 처리',
                    '입출력 형식·공백·개행·정밀도 정확성', 'scanf 포맷·포인터·인덱스 범위',
                    '배열 경계·미초기화·0 나눗셈·오버플로우 등 미정의 동작', '빈 입력·최솟값·최댓값·동일값 반복'],
    'algorithm': ['문제 의도에 맞는 접근 방식', '입력 규모에 적합한 시간·공간 복잡도',
                  '불필요한 연산·중복 계산', '자료구조 선택의 합리성'],
    'readability': ['의도를 드러내는 변수·함수 이름', '일관된 들여쓰기·중괄호·공백',
                    '도움이 되는 함수·루프 분리와 중복 제거', '의도 전달에 필요한 주석'],
    'problem_understanding': ['입력 형식·개수·타입', '출력 형식·단위·정밀도',
                              '특수 조건 누락 여부', '예제 입출력과의 일치', '범위·시간·메모리 제약조건 반영'],
}
DEFAULT_RUBRIC = [
    dict(id='correctness', name='정확성', max_score=10, description='정상 입출력과 코너케이스를 처리하는 코드 단위 정합성. ' + '; '.join(AXIS_CHECKLISTS['correctness'])),
    dict(id='algorithm', name='알고리즘', max_score=10, description='문제 의도에 맞는 로직과 시간·공간 적합성. ' + '; '.join(AXIS_CHECKLISTS['algorithm'])),
    dict(id='readability', name='가독성', max_score=10, description='네이밍·들여쓰기·함수 분리·주석. 입문 문제는 함수 분리 부재를 크게 감점하지 않으며, 자명한 코드에 주석을 강요하지 않는다.'),
    dict(id='problem_understanding', name='문제 이해도', max_score=10, description='요구사항·제약조건 반영도. ' + '; '.join(AXIS_CHECKLISTS['problem_understanding'])),
    dict(id='resource_files', name='자원 관리 · 파일', max_score=10, description='파일/FD 열기 성공과 실패 반환값 확인, 성공적으로 연 파일의 fclose/close, 정상·오류 경로의 누락 및 중복 닫기 확인. 표준입출력만 사용하는 문제는 제외.'),
    dict(id='resource_memory', name='자원 관리 · 동적 메모리', max_score=10, description='malloc/calloc/realloc/new 등의 성공·실패 처리, 소유권과 free/delete, 누수·중복 해제·해제 후 접근 확인. 동적 할당을 요구하거나 사용하지 않으면 제외.'),
    dict(id='resource_processes', name='자원 관리 · 프로세스', max_score=10, description='fork/프로세스 생성 실패, 부모·자식 실행 흐름과 종료, wait/waitpid 등 자식 회수 및 좀비·고아 프로세스 방지 확인. 생성·회수가 필요하거나 사용되지 않으면 제외.'),
]

CALL_PATTERNS = {
    'files': r'\b(?:fopen|freopen|fclose|open|openat|creat|close|fdopen|popen|pclose)\s*\(',
    'memory': r'\b(?:malloc|calloc|realloc|aligned_alloc|free)\s*\(|\bnew\s+\w|\bdelete\b',
    'processes': r'\b(?:fork|vfork|wait|waitpid|waitid|posix_spawn|posix_spawnp|execve|execvp|execl|Popen)\s*\(|\bsubprocess\.(?:run|call|check_call|check_output)\s*\(',
}
PROBLEM_PATTERNS = {
    'files': r'\b(?:source|destination|db)\.(?:txt|dat)\b|파일.{0,24}(?:열|읽|쓰|저장|복사|닫)|(?:입력|출력|데이터)\s*파일|\b(?:read|write|copy|open|close)\s+(?:\w+\s+){0,3}files?\b|\b(?:fopen|open|fclose|close)\s*\(',
    'memory': r'동적\s*(?:메모리|할당)|메모리.{0,16}(?:할당|해제)|\b(?:malloc|calloc|realloc|free|new|delete)\b',
    'processes': r'(?:자식|프로세스).{0,24}(?:생성|만들|종료|회수|대기)|\b(?:fork|vfork|waitpid|posix_spawn|execve)\b',
}
NEGATIVE_PATTERNS = {
    'files': r'파일[^\n.;,]{0,18}(?:읽지\s*않|쓰지\s*않|열지\s*않|사용하지\s*않|사용\s*안|불필요|사용.{0,4}없|제외)|(?:do\s+not|no\s+need\s+to)\s+(?:read|write|copy|open|close)\s+(?:\w+\s+){0,3}files?\b',
    'memory': r'(?:동적\s*(?:할당|메모리)|메모리)[^\n.;,]{0,18}(?:할당하지\s*않|해제하지\s*않|사용하지\s*않|하지\s*않|불필요|사용.{0,4}없|제외)',
    'processes': r'프로세스[^\n.;,]{0,18}(?:생성하지\s*않|만들지\s*않|사용하지\s*않|불필요|사용.{0,4}없|제외)',
}


def code_without_comments_or_strings(code):
    pattern = r'/\*.*?\*/|//[^\n]*|\#[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    return re.sub(pattern, ' ', code, flags=re.S)


def resource_scope(problem, sources, policy=None):
    policy = policy or {}
    if not isinstance(policy, dict) or set(policy) - set(RESOURCE_IDS) or any(v not in ('auto', 'include', 'exclude') for v in policy.values()):
        raise ValueError('자원 적용 설정은 파일/동적 메모리/프로세스별 auto/include/exclude여야 합니다.')
    code = '\n'.join(code_without_comments_or_strings(text) for text in sources.values())
    scope = {}
    for kind in RESOURCE_IDS:
        mode = policy.get(kind, 'auto')
        positive = re.sub(NEGATIVE_PATTERNS[kind], ' ', problem, flags=re.I)
        required = bool(re.search(PROBLEM_PATTERNS[kind], positive, re.I))
        used = bool(re.search(CALL_PATTERNS[kind], code))
        applicable = mode == 'include' or mode == 'auto' and (required or used)
        reason = ('교수자 지정: 평가' if mode == 'include' else '교수자 지정: 제외' if mode == 'exclude' else
                  '문제 요구사항에 해당 자원이 포함됨' if required else '제출 코드에서 해당 자원을 사용함' if used else '문제 요구와 코드 사용이 없어 제외')
        scope[kind] = dict(applicable=applicable, reason=reason, mode=mode)
    return scope


def validate_dcucode_rubric(rubric):
    expected = {r['id'] for r in DEFAULT_RUBRIC}
    if len(rubric) != len(expected) or {r['id'] for r in rubric} != expected or any(r['max_score'] != 10 for r in rubric):
        raise ValueError('새 평가는 DCUCode 4축과 자원 관리 3문항을 각 10점으로 사용합니다.')
    return rubric


def compute_scores(criteria, total_score=100):
    if isinstance(total_score, bool) or not isinstance(total_score, int) or not 1 <= total_score <= 10000:
        raise ValueError('문제 배점은 1–10,000의 정수여야 합니다.')
    by_id = {c['id']: c for c in criteria}
    core = {axis: by_id[axis]['score'] for axis in AXES}
    for value in core.values():
        if type(value) is not int or not 0 <= value <= 10:
            raise ValueError('DCUCode 평가축 점수는 0–10의 정수여야 합니다.')
    active = [by_id[rid]['score'] for rid in RESOURCE_IDS.values() if by_id[rid].get('applicable', True)]
    if any(type(v) is not int or not 0 <= v <= 10 for v in active):
        raise ValueError('적용 자원 문항 점수는 0–10의 정수여야 합니다.')
    resources = round(sum(active) / len(active)) if active else None
    overall_denominator = 50 if active else 40
    partial_denominator = 30 if active else 20
    overall = round((sum(core.values()) + (resources or 0)) / overall_denominator * 100)
    partial = max(0, min(total_score, round(total_score * (core['correctness'] + core['problem_understanding'] + (resources or 0)) / partial_denominator)))
    return dict(overall=overall, suggested_partial_score=partial, suggested_score=partial, max_score=total_score,
                resource_score=resources, resource_max=10 if active else 0,
                overall_denominator=overall_denominator, partial_denominator=partial_denominator,
                scoring_version=SCORING_VERSION)
