# 명세 파일로 배점 채점 사용법

메인 화면의 **고급 → 명세 파일로 배점 채점…**에서 여는 선택 기능이다.
AI 생성 케이스는 일반 **채점 시작**으로 실행한다. 이 문서의 YAML 명세를 작성할 필요가 없다.

## 실행 준비

`python -m pip install -r requirements.txt`로 PyYAML을 포함한 의존성을 설치한다.
권장 실행 환경은 Docker이며 `docker compose build grader`로 이미지를 준비한다.
GUI는 `python src/main.py`로 연다.

## 문제 명세

`assignments/` 아래 원하는 디렉터리에 `problem.yaml`을 만든다.
GUI에서 임의 위치의 YAML 파일을 열 수도 있다. 다음은 최소 예시다.

```yaml
version: 1
id: sum-practice
title: 두 정수의 합
statement: 표준입력의 두 정수를 더해 출력한다.
submit:
  language: python
  files: [main.py, answer.py]
  paths: [chap1/sum, '.']
run:
  timeout_sec: 10
  compare: tokens
scoring:
  total: 10
  cases:
    positive: 6
    negative: 4
  manual_override: allowed
```

- `id`: 영문·숫자·하이픈·밑줄, 최대 100자. 실행 기록의 문제 식별자다.
- `submit.language`: `c` 또는 `python`.
- `submit.paths`: 학생 저장소 안의 상대 경로 후보. 생략하면 `['.']`.
- `submit.files`: 경로별로 시도할 진입 파일 후보. 앞에 적은 경로와 파일이 우선한다.
- `build.sources`: C 링크 소스 목록. 생략하면 선택된 소스와 같은 디렉터리의 모든 `.c` 파일.
- `build.flags`: C 컴파일·링크 옵션 목록. 예: `[-Wall, -Wextra, -lm]`.
- `run.timeout_sec`: 0.01~300초. Docker에서는 컨테이너 시작·컴파일·실행을 포함한다.
  네이티브 실행은 컴파일 최대 30초와 프로그램 실행 제한을 각각 적용한다.
- `run.compare`: `exact`, `trimmed`, `tokens`, `numeric`. 기본 `trimmed`.
- `run.tolerance`: numeric 비교의 절대 오차, 기본 `1e-6`. 숫자 토큰 개수가 같아야 하며 NaN/Infinity는 실패한다.
- `scoring.cases`: 케이스 폴더명과 배점. 배점 합은 `total`과 같아야 한다.
- `scoring.manual_override`: `allowed`(기본) 또는 `forbidden`.
- `due`: 선택적인 시간대 포함 ISO 시각. 예: `2026-10-15T23:59:00+09:00`.
- `source`: 선택적인 문제 출처 문자열.

중복 YAML 키와 알려지지 않은 필드는 오류다. 잘못된 배점·시간 제한·경로·빈 검사항목은 채점 전에 거부한다.

## 케이스

```text
problem.yaml
cases/
  positive/
    stdin.txt
    expected.txt
  negative/
    stdin.txt
    expected.txt
```

`stdin.txt`는 표준입력, `expected.txt`는 기대 표준출력이다. 인자는 `args.txt`에 적거나
`case.yaml`의 문자열 배열로 작성한다. 동일 항목을 파일과 YAML에 중복 정의하지 않는다.
케이스마다 실행 전 복사할 자료는 `files/` 안에 둔다. 소스/실행 파일을 보조 자료로 덮어쓸 수 없다.

파일 복사 문제의 `case.yaml` 예:

```yaml
args: [source.txt, destination.txt]
files:
  destination.txt: "Hello\n"
exit_code: 0
```

`files/source.txt`에는 입력 내용을 저장한다. 위의 `files` 키는 **검사할 출력 파일과 기대 내용**이며,
보조 자료 디렉터리 `files/`와 역할이 다르다. `expected`와 `stderr`도 YAML 문자열로 지정할 수 있다.
표준출력·오류출력·결과 파일 중 하나 이상의 검사가 필요하다. 결과 파일은 완전일치,
오류출력은 앞뒤 공백을 제거해 비교한다. 결과 파일 읽기는 파일당 1MB로 제한한다.

이전 `case.json`의 설정을 새 경로에 그대로 넣지 않는다. 새 명세는 `case.yaml`만 읽는다.
실제로 변환한 예시는 `assignments/system/2026/chap4/prob2/`를 참고한다.
제공된 두 문제의 배점은 기능 검증용 예시다.

## 제출물 매핑

기본 경로 후보는 명세에서 읽는다. 문제 옆 `layout.local.yaml`로 공통 후보와 학생별 보정을 추가한다.
GUI의 **선택 학생 제출 경로 지정**은 해당 파일을 저장하며, 다음 실행에서 재사용한다.

```yaml
candidates:
  sum-practice: [chap1/sum, chapter1/task1]
overrides:
  '20260001':
    sum-practice: 과제1/합계
```

학생별 보정이 있으면 보정 경로만 검사한다. 잘못된 보정에 대해 다른 후보로 조용히 대체하지 않는다.
절대 경로와 `..` 경로는 허용하지 않는다. 이름이 같은 다른 학생과 섞이지 않도록 수업별 문제 디렉터리를 사용한다.
CLI의 `--layout`으로 분반별 매핑 파일을 따로 지정할 수도 있다.

**명단 기준 대상 선택**은 기존 CSV 형식 `학번,이름,GitHub URL`을 읽는다.
CSV에 있지만 저장소 폴더가 없는 학생도 미확정으로 기록한다. 명단을 읽는 작업은 네트워크 수집을 하지 않는다.
기존 수집기와 동일하게 학번을 정수 형태의 디렉터리명으로 정규화한다.

## CLI

```powershell
# 가상 학생 세 명으로 전체 흐름 확인
python src/cli.py examples/manifest_students --batch --manifest assignments/demo/sum/problem.yaml --mode windows

# 실제 분반 디렉터리 + 명단 전체를 대상으로 채점 (경로는 수업에 맞게 변경)
python src/cli.py src/origin/system_3_2026 --batch --roster testdata/2026/system_3.csv --manifest assignments/system/2026/chap4/prob2/problem.yaml --mode docker

# 별도 보관 위치 및 성적표 추가 내보내기
python src/cli.py examples/manifest_students --batch --manifest assignments/demo/sum/problem.yaml --mode windows --records records --output reports/demo.csv
```

`--output`은 추가 JSON/CSV 내보내기다. 지정 여부와 관계없이 실행 기록은 자동 저장된다.
`--manifest`와 `--cases`는 함께 사용할 수 없다. 명세 모드에서는 `--chapter`, `--problem`,
`--source`, `--timeout` 대신 명세/매핑을 수정한다.
종료 코드: 전원 모든 케이스 통과 0, 미통과·미확정·학생별 오류 포함 1, 설정/환경/저장 오류 2.

## 기록과 검토

```text
records/<문제ID>/<실행ID>/
  run.json             # 점수·근거·조정 이력의 원본
  summary.csv          # Excel용 BOM CSV; JSON에서 재생성 가능
  inputs/
    problem.yaml
    cases/
    layout.yaml        # 존재할 때만
  submissions/
    0001/              # 채점한 제출 폴더의 사본 (.git 제외)
    0003/
```

JSON에는 문제 계약, 환경과 Docker 이미지 ID, 도구 커밋/변경 여부/소스 해시,
제출 경로·파일·커밋·사본 해시, 케이스 출력·기대값·파일 검사·실행 시간·점수가 남는다.
학생별 저장이 끝난 후 다음 학생을 처리한다. 중지는 현재 학생을 마친 뒤 적용한다.
강제 종료로 `running` 상태가 남았다면 미완료 기록이며, 정상 완료로 간주하지 않는다.

상태별 점수:

| 상태 | 의미 | 점수 |
|---|---|---|
| graded | 모든 케이스의 판정 완료 | 통과 케이스 배점 합 |
| unresolved | 허용된 제출 경로/파일을 찾지 못함 | 공란 |
| error | 채점기/파일 접근 등의 오류 | 공란 |
| not_run | 중지로 처리하지 않음 | 공란 |

컴파일 오류·실행 오류·시간 초과는 판정 가능한 케이스 실패이므로 해당 케이스는 0점이다.
시작 전 Docker/이미지/컴파일러 확인 실패는 전체 작업 오류로 끝난다.

**최종 점수 저장**에는 검토자와 사유가 필요하다. 자동 점수는 유지되며, 이전/새 점수·시각이 이력에 쌓인다.
수동으로 미확정 학생의 점수를 정할 수도 있지만 원래 미확정 상태와 수동 조정 표시는 보존한다.
CSV에서 점수가 빈 행과 0점인 행을 구분한다.

`due`는 변경 사항이 없는 Git 저장소의 최신 커밋 시각으로 지연 시간을 계산한다.
이는 실제 서버 제출 시각을 증명하지 않으며 자동 감점도 하지 않는다.

## 검증 명령

```powershell
python -m unittest discover -s tests -v
$env:SWLAB_TEST_DOCKER = '1'
python -m unittest discover -s tests -v
```

실제 학생 저장소 대신 임시 디렉터리와 `examples/`의 가상 제출물로 검증한다.
채점 기록·제출 사본·로컬 매핑은 Git 무시 대상이다. 기록 보관 기간과 디스크 정리는 운영자가 관리한다.
