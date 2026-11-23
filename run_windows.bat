@echo off
cd /d "%~dp0"
if not exist .venv (py -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if not exist .env (echo Create a .env file based on .env.example first. & pause & exit /b 1)
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /v /b "#" .env`) do set "%%A=%%B"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
