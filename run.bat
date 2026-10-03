@echo off
chcp 65001 >nul
REM 파이썬 찾기: py 런처 우선 (python은 MS스토어 바로가기일 수 있음)
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
cd /d "%~dp0"
%PY% main.py
pause
