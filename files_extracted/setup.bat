@echo off
chcp 65001 >nul
echo ================================================
echo   AD RANK 자동화 - 설치 스크립트
echo ================================================
echo.

REM Python 설치 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo 아래 링크에서 Python을 설치해주세요:
    echo https://www.python.org/downloads/
    echo.
    echo ※ 설치 시 "Add Python to PATH" 체크 필수!
    pause
    exit /b
)

echo [1/2] Python 확인 완료
echo.

echo [2/2] 필요한 패키지 설치 중...
pip install selenium gspread google-auth chromedriver-autoinstaller --quiet

echo.
echo ================================================
echo   설치 완료!
echo.
echo   다음 단계:
echo   1. config.json 파일에 구글 시트 URL 입력
echo   2. credentials.json 파일을 이 폴더에 넣기
echo   3. run.bat 실행
echo ================================================
pause
