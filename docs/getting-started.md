# 처음 설치하기 (Windows)

새 컴퓨터에 처음 설치하는 순서입니다. 다 끝나면 바탕화면 아이콘으로 앱을 열 수 있습니다.
설치한 뒤 화면 사용법은 [사용법](user-guide.md)을 보세요.

## 설치 순서 한눈에 보기

| 단계 | 할 일 | 필수 |
|---|---|---|
| 1 | Python, Git, Docker Desktop 설치 | 필수 |
| 2 | 이 저장소 내려받기 | 필수 |
| 3 | 패키지 설치 | 필수 |
| 4 | Docker 이미지 만들기 | 필수 |
| 5 | 앱 실행, 바로가기 만들기 | 필수 |
| 6 | 학생 명단, 채점 케이스 넣기 | 필수 |
| 7 | Qwen 서버 설정 | AI 기능을 쓸 때만 |
| 8 | 강의 자료 넣기 | 슬라이드 선택을 쓸 때만 |
| 9 | 기존 컴퓨터의 기록 옮기기 | 옮길 기록이 있을 때만 |

---

## 1. 프로그램 설치

| 프로그램 | 용도 | 설치 확인 |
|---|---|---|
| [Python](https://www.python.org/downloads/) 3.10 이상 (3.11 권장) | 앱 실행 | `python --version` |
| [Git for Windows](https://git-scm.com/download/win) | 저장소 내려받기 | `git --version` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 학생 코드를 안전하게 실행 | `docker --version` |

> - **Python:** 설치 첫 화면에서 **Add python.exe to PATH**를 꼭 체크하세요.
> - **Docker Desktop:** WSL 2를 쓰라는 안내가 나오면 그대로 따르세요. 재부팅이 필요할 수 있습니다.
> - **채점할 때는 Docker Desktop이 항상 켜져 있어야 합니다.** 작업 표시줄의 고래 아이콘으로 확인합니다.

## 2. 저장소 내려받기

PowerShell을 열고 실행합니다. 경로에 한글이나 공백이 없는 폴더(예: `C:\dev`)를 권장합니다.

```powershell
cd C:\dev
git clone https://github.com/DCUSnSLab/SWLAB_practice_evaluation.git
cd SWLAB_practice_evaluation
```

> 아래 명령은 모두 이 `SWLAB_practice_evaluation` 폴더에서 실행합니다.

## 3. 패키지 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

> 필요한 패키지는 프로젝트 안의 `.venv` 폴더에만 설치됩니다.

## 4. Docker 이미지 만들기

Docker Desktop을 켠 상태에서 **한 번만** 실행합니다.

```powershell
docker compose build grader
```

> 채점할 때마다 앱이 알아서 컨테이너를 만들고 지웁니다. 컨테이너를 따로 켜 둘 필요는 없습니다.

## 5. 앱 실행

```powershell
.\.venv\Scripts\python src\main.py
```

바탕화면 바로가기를 만들면 다음부터는 **SWLAB 실습 채점** 아이콘을 두 번 클릭해 실행할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
```

> 오류 내용을 콘솔로 보고 싶을 때는 `scripts\launch_gui.cmd`로 실행합니다.

## 6. 학생 명단과 채점 케이스 넣기

학생 명단과 채점 케이스는 학생에게 보이면 안 되므로 Git에 올라가지 않습니다. 기존 컴퓨터나 담당자에게서 받아 같은 위치에 넣어 주세요.

| 받을 것 | 넣을 위치 |
|---|---|
| 학생 명단 CSV | `testdata\<연도>\` |
| 채점 케이스 | `testcase\` 폴더 전체 |
| 중간고사 문제 세트 | `assignments\system\` 폴더 전체 |

명단 파일은 아래 규칙을 따릅니다.

| 항목 | 규칙 | 예 |
|---|---|---|
| 위치 | `testdata\<연도>\` | `testdata\2026\` |
| 파일 이름 | `system_<분반>.csv` 또는 `python_<분반>.csv` | `system_3.csv` |
| 내용 | `학번,이름,GitHub 주소` (헤더 행은 있어도 되고 없어도 됨) | 아래 참고 |

```csv
24115186,홍길동,https://github.com/example/syspro.git
```

> **학생 저장소가 비공개라면** 이 컴퓨터의 Git에 GitHub 계정으로 먼저 로그인해 두어야 합니다.
> 비공개 저장소 하나를 `git clone`으로 받아 보면 로그인 창이 뜹니다. 로그인하지 않으면 그 학생들은 동기화 실패로 나옵니다.

## 7. Qwen 서버 설정 (AI 기능을 쓸 때만)

AI 케이스 생성과 정성평가에만 필요합니다. 일반 채점은 설정 없이 됩니다.

```powershell
Copy-Item settings.example.json settings.local.json
```

`settings.local.json`을 열어 채웁니다.

| 항목 | 넣을 값 |
|---|---|
| `llm.url` | 서버 주소 (예: `https://llm.example.com/v1`) |
| `llm.model` | 모델 이름 |
| `llm.api_key` | 인증이 필요한 서버만 |

> 앱의 **서버 연결 확인** 버튼으로 연결되는지 확인할 수 있습니다. 이 파일은 Git에 올라가지 않습니다.

## 8. 강의 자료 넣기 (슬라이드 선택을 쓸 때만)

강의 원본 PPTX/PDF를 프로젝트 폴더의 `강의자료\`에 넣으면 앱에서 슬라이드를 골라 쓸 수 있습니다. 이 폴더는 Git에 올라가지 않습니다.

## 9. 기존 컴퓨터의 기록 옮기기

**두 컴퓨터 모두 앱을 닫은 뒤** 복사하세요.

| 옮길 것 | 방법 |
|---|---|
| 채점·정성평가 기록, 점수 조정 | `data\swlab.db` 파일 하나를 같은 위치에 복사 |
| 채점 케이스 | `testcase\`, `assignments\system\` 폴더 복사 |
| 학생 제출물 | 복사할 필요 없음. **저장소 동기화**를 다시 하면 새로 받습니다. |
| Qwen 설정 | `settings.local.json` 복사 |
| 강의 자료 | `강의자료\` 폴더 복사 |
| 아주 예전 결과 폴더(`reports\`) | 폴더를 복사한 뒤 **도구 / 고급 → 이전 채점·정성평가 기록을 DB로 가져오기** |

---

## 설치 확인

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
```

마지막 줄에 `OK`가 나오면 설치가 끝난 것입니다. `skipped`가 함께 나오는 것은 정상입니다.

## 업데이트 받기

```powershell
git pull
.\.venv\Scripts\python -m pip install -r requirements.txt
```

> - **업데이트한 뒤에는 열려 있던 앱을 꼭 닫고 다시 실행하세요.** 켜 둔 채로 업데이트하면 오류가 날 수 있습니다.
> - `Dockerfile`이 바뀐 경우에만 `docker compose build grader`를 다시 실행합니다.

## 자주 생기는 문제

| 증상 | 해결 |
|---|---|
| `python`을 찾을 수 없음 | Python 설치 때 PATH 체크를 빠뜨렸습니다. 다시 설치하거나 `py -3.11 -m venv .venv`를 씁니다. |
| 바로가기 만들 때 `.venv 이 없습니다` | 3단계를 먼저 합니다. |
| 모든 학생이 실행 오류 | Docker Desktop이 꺼져 있거나 4단계를 안 했습니다. `docker images`에 `grader-image`가 있는지 봅니다. |
| 동기화에서 일부 학생 실패 | 완료 창의 사유를 봅니다. 주소 오류, 비공개 저장소 권한, 학생 폴더의 직접 수정이 흔한 원인입니다. |
| 문제 옆에 `케이스 없음`이 나옴 | 6단계의 채점 케이스를 넣습니다. 새 문제라면 앱에서 **AI 케이스 생성**으로 만듭니다. |
| 연도·분반 목록이 비어 있음 | 아직 받은 제출물이 없습니다. **저장소 동기화**를 먼저 합니다. |
| `CSV filename must be system_3.csv ...` | 명단 파일 이름을 6단계 규칙대로 바꿉니다. |
| AI 기능에서 서버 주소·모델 안내가 뜸 | 7단계 설정을 합니다. |
