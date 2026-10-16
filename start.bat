@echo off
title Dining Trace - Canteen Dashboard
echo ==========================================
echo    Dining Trace  ^|  Canteen Dashboard
echo ==========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.9+ first:
    echo         https://www.python.org/downloads/
    echo         Remember to check "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version 2^>^&1') do echo [OK] %%v
echo.

python -c "import requests,streamlit,plotly,pandas" >nul 2>&1
if %errorlevel% neq 0 (
    echo [SETUP] Missing dependencies, installing now...
    echo         This downloads tens of MB and may take 1-3 MINUTES.
    echo         Please wait until it finishes - do not close this window.
    echo.
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo [WARN] Install failed, retrying with a mirror...
        python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    )
    echo.
    echo [SETUP] Done.
) else (
    echo [OK] Dependencies already installed.
)
echo.

echo [RUN] Starting dashboard...
echo       Your browser will open automatically.
echo       NOTES:
echo         - First login fetches ALL your history and can take
echo           OVER 1 MINUTE. Please be patient and do NOT click
echo           the login button repeatedly.
echo         - If the page shows "connection refused", just wait a
echo           few seconds and refresh.
echo.
python -m streamlit run app.py

echo.
echo Dashboard stopped.
pause
