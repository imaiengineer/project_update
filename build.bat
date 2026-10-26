@echo off
REM Builds dist\AttendanceSync.exe. Double-click this file on Windows.
REM Needs Python 3.10+ from python.org (tick "Add python.exe to PATH" when installing).
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist client_secret.json (
  echo.
  echo WARNING: client_secret.json is not in this folder.
  echo The app will build, but "Sign in with Google" will not work until you put
  echo client_secret.json next to AttendanceSync.exe. See GUIDE.md, part A.
  echo.
  pause
)

echo [1/3] Creating a private Python environment...
python -m venv .venv || goto :fail
call .venv\Scripts\activate.bat

echo [2/3] Installing libraries (a few minutes the first time)...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller || goto :fail

echo [3/3] Building AttendanceSync.exe...
set EXTRA=
if exist client_secret.json set EXTRA=--add-data "client_secret.json;."
pyinstaller --noconfirm --clean --onefile --windowed --name AttendanceSync ^
  --collect-all playwright ^
  --collect-submodules keyring --hidden-import keyring.backends.Windows ^
  %EXTRA% app.py || goto :fail

echo.
echo Done: %~dp0dist\AttendanceSync.exe
echo Share that one file with trainers (it already contains client_secret.json if it was here).
explorer "%~dp0dist"
pause
exit /b 0

:fail
echo.
echo Build failed - scroll up for the error.
pause
exit /b 1
