# Creates a desktop shortcut that opens the grading app without a console window.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1 [-Name "SWLAB 실습 채점"] [-Folder <dir>]
param(
    [string]$Name = 'SWLAB 실습 채점',
    [string]$Folder = [Environment]::GetFolderPath('Desktop')
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $python)) {
    throw ".venv 이 없습니다. README 의 설치 단계(python -m venv .venv ...)를 먼저 실행하세요: $python"
}
$launcher = Join-Path $root 'scripts\launch_gui.cmd'
$target = Join-Path $Folder ($Name + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($target)
$shortcut.TargetPath = $python
$shortcut.Arguments = '"' + (Join-Path $root 'src\main.py') + '"'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'SWLAB 실습 일괄 채점 (Docker Desktop 이 실행 중이어야 합니다)'
$shortcut.IconLocation = (Join-Path $root 'scripts\swlab.ico') + ',0'
if (-not (Test-Path (Join-Path $root 'scripts\swlab.ico'))) {
    $shortcut.IconLocation = '%SystemRoot%\System32\imageres.dll,-1023'
}
$shortcut.Save()
Write-Host "바로가기를 만들었습니다: $target"
Write-Host "콘솔 창이 필요하면 $launcher 를 대신 사용하세요."
