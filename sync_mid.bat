@echo off
chcp 65001 >nul
echo ================================================
echo   MID 동기화 도구
echo ================================================
echo.
python "%~dp0sync_mid.py"
pause
