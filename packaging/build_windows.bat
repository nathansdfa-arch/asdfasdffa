@echo off
rem Builds the Windows app and its installer on this PC. You normally don't need
rem this: GitHub builds the installer automatically (see INSTALL.md). It is here
rem so a developer can build one by hand.
rem
rem Needs: Python 3.13 from python.org, and Inno Setup 6 from https://jrsoftware.org/isdl.php
rem Result: dist\TradingApp-Setup-<version>.exe

cd /d "%~dp0\.."

if not exist ".build-venv\Scripts\python.exe" (
    py -3.13 -m venv .build-venv || goto :failed
)
".build-venv\Scripts\python.exe" -m pip install --upgrade pip || goto :failed
".build-venv\Scripts\python.exe" -m pip install -r requirements-build.txt || goto :failed
rem MetaTrader 5 support is optional; include it when it installs.
".build-venv\Scripts\python.exe" -m pip install -r requirements-mt5.txt

for /f %%v in ('".build-venv\Scripts\python.exe" packaging\make_version_info.py') do set APP_VERSION=%%v
echo Building Trading App %APP_VERSION%

".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean packaging\trading_app.spec || goto :failed

set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo.
    echo The app is built in dist\TradingApp, but Inno Setup 6 was not found, so there is no installer.
    echo Install it from https://jrsoftware.org/isdl.php and run this again.
    pause
    goto :eof
)
%ISCC% /DAppVersion=%APP_VERSION% packaging\installer.iss || goto :failed

echo.
echo Done: dist\TradingApp-Setup-%APP_VERSION%.exe
pause
goto :eof

:failed
echo.
echo The build failed. The messages above say why.
pause
