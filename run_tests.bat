@echo off
rem Double-click to run every automated test. Needs start_app.bat to have run once first.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest
pause
