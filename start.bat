@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "PYTHON=%BACKEND%\.venv\Scripts\python.exe"
set "DEFAULT_DB=%BACKEND%\data\lifepilot.db"

if not exist "%PYTHON%" (
  echo Could not find the backend virtual environment at:
  echo   %PYTHON%
  echo Create it with: python -m venv backend\.venv
  exit /b 1
)

if not exist "%FRONTEND%\package.json" (
  echo Could not find the frontend at:
  echo   %FRONTEND%
  exit /b 1
)

if not defined LIFEPILOT_DB_PATH set "LIFEPILOT_DB_PATH=%DEFAULT_DB%"
start "LifePilot Backend" /D "%BACKEND%" cmd /k ""%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "LifePilot Frontend" /D "%FRONTEND%" cmd /k "npm run dev"
start "" http://127.0.0.1:3000/

echo LifePilot services are starting.
echo Backend:  http://127.0.0.1:8000/api/health
echo Frontend: http://127.0.0.1:3000/
echo Database:  %LIFEPILOT_DB_PATH%
endlocal
