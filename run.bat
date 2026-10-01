@echo off
title Automated Video Dubbing System
cd /d "%~dp0"

echo ========================================================
echo   Automated Video Dubbing System (1-Click Runner)
echo ========================================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .\venv
    echo Creating virtual environment and installing dependencies...
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate
)

echo Starting Video Dubber...
python main.py %*

echo.
echo Process finished.
pause
