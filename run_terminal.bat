@echo off
TITLE NSE Alpha-Sell Options Terminal
COLOR 0A
CLS

echo =======================================================================
echo               NSE ALPHA-SELL OPTIONS TRADING TERMINAL
echo =======================================================================
echo [INFO] Starting Institutional Options Seller Terminal...
echo [INFO] Environment: Windows
echo [INFO] Server: FastAPI + Uvicorn on http://localhost:8000
echo =======================================================================
echo.

:: Navigate to backend directory
cd /d "%~dp0backend"

:: Launch browser after 2 seconds in background
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: Start Uvicorn Server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

pause
