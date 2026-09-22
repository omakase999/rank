@echo off
chcp 65001 >nul
echo ================================================
echo   길찾기/유입 동기화 도구
echo ================================================
echo.
python "%~dp0sync_traffic.py"
pause
