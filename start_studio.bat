@echo off
title Automated Video Dubbing Studio
cd /d "%~dp0"

call venv\Scripts\activate
echo ========================================================
echo   Launching Automated Video Dubbing Web Studio
echo   Opening in your browser: http://localhost:8000
echo ========================================================
start http://localhost:8000
python app.py

pause
