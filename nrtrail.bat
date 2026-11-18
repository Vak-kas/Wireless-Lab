@echo off
rem Windows: 더블클릭하면 nrtrail 을 실행한다. 창을 닫으면 전부 꺼진다.
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  rem 처음 실행: 프로젝트 안에 가상환경을 만들고 필요한 패키지를 깐다
  py -3 tools\bootstrap.py || python tools\bootstrap.py || (echo 설치하지 못했습니다. & pause & exit /b 1)
)
venv\Scripts\python.exe tools\app.py %*
