@echo off
rem Windows: 더블클릭하면 nrtrail 을 실행한다. 창을 닫으면 전부 꺼진다.
cd /d "%~dp0"
venv\Scripts\python.exe tools\app.py %*
