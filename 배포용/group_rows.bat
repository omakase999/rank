@echo off
chcp 65001 >nul
REM 파이썬 찾기: py 런처 우선 (python은 MS스토어 바로가기일 수 있음)
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
echo ================================================
echo   결과 시트 그룹화 도구
echo ================================================
echo.
%PY% "%~dp0group_rows.py"
pause
