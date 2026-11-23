@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo NCC Sentinel - Windows Local Launcher
echo ==========================================
where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python launcher not found. Install Python 3.11+ from python.org and enable PATH.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)
echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
if not exist ".env" (
  echo Generating local demo configuration...
  ".venv\Scripts\python.exe" -c "import secrets,pathlib; pathlib.Path('.env').write_text('SESSION_SECRET='+secrets.token_urlsafe(48)+'\nDEV_MODE=1\nSMS_MODE=demo\nCOOKIE_SECURE=0\nDATABASE_PATH=./sentinel.db\nTZ_OFFSET_MINUTES=330\n')"
  if errorlevel 1 goto :failed
)
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /r /v "^# ^$" .env`) do set "%%A=%%B"
".venv\Scripts\python.exe" -c "import sqlite3,os,sys; p=os.environ.get('DATABASE_PATH','sentinel.db'); c=sqlite3.connect(p); sys.exit(0 if c.execute('SELECT count(*) FROM sqlite_master WHERE type=\"table\" AND name=\"users\"').fetchone()[0] and c.execute('SELECT count(*) FROM users WHERE role=\"admin\"').fetchone()[0] else 1)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo First time setup: create an administrator account.
  echo Enter admin login ID such as ADMIN001 and password of 12+ characters.
  ".venv\Scripts\python.exe" app.py create-admin
  if errorlevel 1 goto :failed
)
echo.
echo Website: http://127.0.0.1:8000
echo DEMO OTP codes are shown in this terminal window.
echo Keep this window open while using the website.
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo STARTUP FAILED. Copy the error above when asking for help.
pause
exit /b 1
