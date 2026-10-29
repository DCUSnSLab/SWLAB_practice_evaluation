# SWLAB 실습 평가 시스템

학생 GitHub 제출물을 모아 C/Python 실습을 한 번에 채점하는 Windows 데스크톱 앱(PyQt6)입니다.

## 문서

| 문서 | 내용 |
|---|---|
| [처음 설치하기](docs/getting-started.md) | 새 컴퓨터에 설치, 학생 명단 준비, Qwen 서버 설정, 기록 옮기기 |
| [사용법](docs/user-guide.md) | 화면 순서대로 따라 하는 사용 방법 |

## 빠른 시작

Python 3.10 이상, Git, Docker Desktop이 설치되어 있어야 합니다. 자세한 순서는 [처음 설치하기](docs/getting-started.md)를 보세요.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
docker compose build grader
.\.venv\Scripts\python src\main.py
```

바탕화면 바로가기를 만들면 다음부터는 아이콘을 두 번 클릭해 실행할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
```

## 주요 기능

| 기능 | 설명 |
|---|---|
| 저장소 동기화 | 학생 명단 CSV로 학생별 GitHub 저장소를 내려받고 최신 상태로 갱신합니다. |
| 일괄 채점 | 선택한 학생들의 코드를 Docker 컨테이너에서 실행해 한 번에 채점합니다. |
| AI 케이스 생성 | 강의 슬라이드의 문제를 골라 Qwen으로 테스트 케이스를 만들고 검증합니다. |
| Qwen 정성평가 | AI가 코드를 검토해 점수를 제안하고, 교수자가 확인해 확정합니다. |
| 최신 점수표 | 학생·문제별 최신 결과를 한 표로 모아 보여 주고, 점수를 조정할 수 있습니다. |
| CSV 내보내기 | 현재 화면 또는 원하는 장만 골라 학생당 한 행으로 저장합니다. |

## 데이터 저장 위치

| 경로 | 내용 | Git |
|---|---|---|
| `data/swlab.db` | 학생 명단, 채점·정성평가 기록, 점수 조정 (모든 결과가 여기에 저장됨) | 제외 |
| `src/origin/` | 동기화한 학생 제출물 | 제외 |
| `reports/` | 채점·정성평가 결과 사본(JSON, CSV) | 제외 |
| `testdata/<연도>/` | 학생 명단 CSV | 새 파일 제외 |
| `settings.local.json` | Qwen 서버 주소·모델명 | 제외 |
| `강의자료/` | 강의 원본 PPTX/PDF | 제외 |

다른 컴퓨터로 옮길 때는 앱을 닫고 `data/swlab.db`를 복사하면 됩니다.

## 명령행 도구

| 명령 | 용도 |
|---|---|
| `.\.venv\Scripts\python src\db.py runs` | 저장된 채점 실행 목록 |
| `.\.venv\Scripts\python src\db.py reviews` | 저장된 정성평가 목록 |
| `.\.venv\Scripts\python src\db.py import` | 예전 `reports/` 결과를 DB로 가져오기 |
| `.\.venv\Scripts\python src\cli.py --help` | 화면 없이 채점하기 |

## 테스트

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
```

Docker 실행까지 확인하려면 먼저 `$env:SWLAB_TEST_DOCKER = '1'`을 설정합니다.

## 개인정보와 보안

- 학생 코드는 네트워크가 차단된 Docker 컨테이너 안에서만 실행합니다.
- Qwen 정성평가를 쓰면 선택한 문제의 학생 소스 코드가 설정한 Qwen 서버로 전송됩니다. 학번·이름 명단은 따로 보내지 않습니다.
- 학생 명단, DB, 결과 파일, 서버 설정은 Git에 올라가지 않습니다.
