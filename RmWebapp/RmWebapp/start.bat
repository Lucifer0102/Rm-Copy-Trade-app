@echo off
echo Starting MT5 Copy Trading System...
echo.

REM Start Backend
echo Starting Backend Server...
cd backend
start cmd /k "python app.py"
timeout /t 3 /nobreak > nul

REM Start Frontend
echo Starting Frontend...
cd ../frontend
start cmd /k "npm start"
timeout /t 5 /nobreak > nul
start http://localhost:3000

echo.
echo MT5 Copy Trading System is running!
echo Backend: http://localhost:5000
echo Frontend: http://localhost:3000
echo.
echo Press any key to stop all services...
pause >nul

REM Kill Python processes
taskkill /F /IM python.exe
echo Services stopped.
pause
