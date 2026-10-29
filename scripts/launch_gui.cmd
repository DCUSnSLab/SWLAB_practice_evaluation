@echo off
rem Opens the grading app with a console window (useful to see tracebacks).
rem Keep this file ASCII: cmd.exe reads batch files in the OEM code page.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Run the install steps in README first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" src\main.py
if errorlevel 1 pause
