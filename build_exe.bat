@echo off
chcp 65001 >nul
REM 파이썬 찾기: py 런처 우선 (python은 MS스토어 바로가기일 수 있음)
set "PY=python"
where py >/dev/null 2>/dev/null && set "PY=py -3"
cd /d "%~dp0"
echo ================================================
echo   AD RANK 자동화 - EXE 만들기
echo ================================================
echo.
echo [1/2] 필요한 패키지 설치 중...
%PY% -m pip install pyinstaller requests gspread google-auth --quiet
echo.
echo [2/2] EXE 만드는 중... (1~3분)
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name ADRANK --hidden-import main --hidden-import pick_random_biz --hidden-import sync_mid --hidden-import sync_traffic --hidden-import group_rows --hidden-import adrank_api --exclude-module selenium --exclude-module chromedriver_autoinstaller gui.py
if not exist "dist\ADRANK.exe" (
    echo.
    echo [오류] EXE를 만들지 못했습니다. 위 메시지를 캡처해서 보내주세요.
    pause
    exit /b
)
copy /Y "dist\ADRANK.exe" "ADRANK.exe" >nul
echo.
echo ================================================
echo   완료! 이 폴더에 ADRANK.exe 가 생겼습니다.
echo   ADRANK.exe 옆에 config.json, credentials.json 이 있어야 합니다.
echo ================================================
pause
