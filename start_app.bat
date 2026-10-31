@echo off
rem Double-click this file to open the Trading App on Windows.
rem The first time, it sets up a private Python environment (.venv) and installs
rem the packages listed in requirements.txt. That takes a minute or two, once.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up the app. This happens only once...
    py -3 -m venv .venv || goto :no_python
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed
)

".venv\Scripts\python.exe" -m desktop.launcher %*
goto :eof

:no_python
echo.
echo Python was not found. Install Python 3.12 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup, then double-click this file again.
pause
goto :eof

:failed
echo.
echo Setting up the packages failed. The messages above say why.
rmdir /s /q .venv
pause
