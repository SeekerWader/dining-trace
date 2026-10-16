@echo off
title bei-hang-canteen

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please install Python 3.9+
    pause
    exit /b
)

python -c "import requests,streamlit,plotly,pandas" 2>nul
if %errorlevel% neq 0 (
    echo Installing dependencies ...
    pip install requests streamlit plotly pandas
)

echo Launching dashboard ...
streamlit run app.py
pause
