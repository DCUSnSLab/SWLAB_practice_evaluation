# 처음 설치하기 (Windows)

SWLAB 실습 평가 시스템을 새 컴퓨터에 처음 설치하는 순서입니다. 끝까지 따라 하면 바탕화면 아이콘으로 앱을 열 수 있습니다.
설치 후 화면 사용법은 [사용법](user-guide.md)을 보세요.

## 1. 미리 설치할 프로그램

| 프로그램 | 용도 | 확인 명령 |
|---|---|---|
| [Python 3.10 이상](https://www.python.org/downloads/) (3.11 권장) | 앱 실행 | `python --version` |
| [Git for Windows](https://git-scm.com/download/win) | 이 저장소와 학생 제출 저장소 내려받기 | `git --version` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 학생 코드를 격리된 컨테이너에서 컴파일·실행 | `docker --version` |

- **Python:** 설치 첫 화면에서 **Add python.exe to PATH**를 반드시 체크합니다.
- **Docker Desktop:** 설치 중 WSL 2 사용을 권장하는 안내가 나오면 그대로 따릅니다. 설치 후 재부팅이 필요할 수 있습니다.
- **Docker 실행 상태:** 채점할 때마다 Docker Desktop이 켜져 있어야 합니다. 작업 표시줄 고래 아이콘이 *Engine running* 상태인지 확인하세요.

## 2. 저장소 내려받기

PowerShell을 열고 작업할 폴더에서 실행합니다. 경로에 한글·공백이 없는 위치(예: `C:\dev`)를 권장합니다.

```powershell
cd C:\dev
git clone https://github.com/DCUSnSLab/SWLAB_practice_evaluation.git
cd SWLAB_practice_evaluation
```

이후 명령은 모두 이 폴더(`SWLAB_practice_evaluation`)에서 실행합니다.

## 3. Python 가상환경과 패키지 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

PyQt6, peewee(SQLite), GitPython, PyYAML이 `.venv` 안에만 설치됩니다. 시스템 Python은 바뀌지 않습니다.

## 4. 채점용 Docker 이미지 만들기

Docker Desktop을 켠 상태에서 한 번만 실행합니다.

```powershell
docker compose build grader
```

`grader-image`(Ubuntu 22.04 + gcc, make, python3)가 만들어집니다. 앱은 채점할 때마다 이 이미지로 컨테이너를 만들고 끝나면 지웁니다. 컨테이너를 계속 켜 둘 필요는 없습니다.

## 5. 앱 실행

```powershell
.\.venv\Scripts\python src\main.py
```

매번 명령을 입력하지 않으려면 바탕화면 바로가기를 한 번 만들어 둡니다. **SWLAB 실습 채점** 아이콘을 두 번 클릭하면 콘솔 창 없이 열립니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
```

오류 메시지를 보고 싶을 때는 콘솔이 남는 `scripts\launch_gui.cmd`로 실행합니다.

## 6. 학생 명단 준비

저장소 동기화에는 학생 명단 CSV가 필요합니다. 명단은 개인정보라 새 명단은 Git에 올라가지 않으므로 직접 복사해 둡니다.

- **위치:** `testdata\<연도>\<과목>_<분반>.csv`. 예: `testdata\2026\system_3.csv`.
- **파일 이름:** `system_<분반>.csv` 또는 `python_<분반>.csv` 형식이어야 합니다. 연도는 상위 폴더 이름(4자리)에서 읽습니다.
- **내용:** `학번,이름,GitHub URL` 세 열입니다. UTF-8 또는 UTF-8 BOM이면 되고, 헤더 행은 있어도 없어도 됩니다.

```csv
24115186,홍길동,https://github.com/example/syspro.git
```

학생 저장소가 비공개라면 이 컴퓨터의 Git에 해당 GitHub 계정으로 먼저 로그인해 두어야 합니다. 예를 들어 비공개 저장소 하나를 `git clone`으로 한 번 받아 보면 Git Credential Manager 로그인 창이 뜹니다. 앱은 동기화 중에 비밀번호를 묻지 않으므로, 로그인이 안 되어 있으면 해당 학생은 실패로 표시됩니다.

## 7. (선택) Qwen 서버 설정

AI 케이스 생성과 정성평가를 쓸 때만 필요합니다. 일반 채점은 설정 없이 동작합니다.

```powershell
Copy-Item settings.example.json settings.local.json
```

`settings.local.json`의 `llm.url`(OpenAI 호환 API 주소, 예: `https://llm.example.com/v1`)과 `llm.model`을 채웁니다. 인증이 필요한 서버만 `llm.api_key`를 넣습니다. 이 파일은 Git에 올라가지 않습니다. 화면의 **서버 연결 확인** 버튼으로 연결을 확인할 수 있습니다.

## 8. (선택) 강의 자료

슬라이드에서 문제를 고르는 기능을 쓰려면 강의 원본 PPTX/PDF를 프로젝트 루트의 `강의자료\` 폴더에 넣습니다. 이 폴더는 Git에 올라가지 않습니다.

## 9. 다른 컴퓨터의 기록 옮기기

채점 결과, 정성평가, 점수 조정, 학생 이름은 모두 `data\swlab.db` 파일 하나에 들어 있고 Git에는 올라가지 않습니다.

| 옮길 것 | 방법 |
|---|---|
| 채점·정성평가 기록 | 기존 컴퓨터의 `data\swlab.db`를 같은 위치에 복사합니다. **앱을 모두 닫은 뒤** 복사하세요. |
| 학생 제출물 | 복사하지 않아도 됩니다. 명단으로 **저장소 동기화**를 다시 하면 `src\origin\`에 새로 받습니다. |
| DB 이전의 예전 결과 폴더 | `reports\`를 복사한 뒤 앱의 **도구 / 고급 → 이전 채점·정성평가 기록을 DB로 가져오기**를 한 번 실행합니다. |
| Qwen 설정·강의 자료 | `settings.local.json`, `강의자료\`를 복사합니다. |

## 10. 설치 확인

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
```

마지막 줄이 `OK`(일부 `skipped`는 정상)이면 설치가 끝난 것입니다. Docker 실제 실행까지 확인하려면 다음처럼 실행합니다.

```powershell
$env:SWLAB_TEST_DOCKER = '1'
.\.venv\Scripts\python -m unittest discover -s tests
```

## 업데이트 받기

```powershell
git pull
.\.venv\Scripts\python -m pip install -r requirements.txt
```

`Dockerfile`이 바뀐 경우에만 `docker compose build grader`를 다시 실행합니다. **업데이트 후에는 열려 있던 앱을 닫고 다시 실행하세요.** 켜 둔 채로 코드를 바꾸면 일부 기능이 옛 코드와 섞여 오류가 납니다.

## 자주 생기는 문제

| 증상 | 확인할 것 |
|---|---|
| `python`을 찾을 수 없음 | Python 설치 시 PATH 체크를 빠뜨렸습니다. 다시 설치하거나 `py -3.11 -m venv .venv`를 사용합니다. |
| `create_shortcut.ps1`에서 `.venv 이 없습니다` | 3단계를 먼저 실행합니다. |
| 모든 학생이 컴파일·실행 오류 | Docker Desktop이 꺼져 있거나 4단계 이미지가 없습니다. `docker images`에 `grader-image`가 있는지 확인합니다. |
| 저장소 동기화에서 일부 학생 실패 | 완료 창의 사유를 봅니다. 주소 오류·비공개 저장소 권한·로컬 수정 파일(동기화 건너뜀)이 흔한 원인입니다. |
| 연도·분반 목록이 비어 있음 | 아직 동기화한 제출물이 없습니다. **저장소 동기화**로 명단 CSV를 먼저 불러옵니다. |
| `CSV filename must be system_3.csv ...` | 명단 파일 이름을 6단계 형식으로 바꿉니다. |
| Qwen 기능에서 URL·모델 안내가 뜸 | 7단계 설정 또는 화면 입력이 필요합니다. |
