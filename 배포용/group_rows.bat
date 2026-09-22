@echo off
chcp 65001 >nul
echo ================================================
echo   결과 시트 그룹화 도구
echo ================================================
echo.
python "%~dp0group_rows.py"
pause
