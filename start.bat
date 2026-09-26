@echo off
title Hangeul Admin API & Telegram Agent
echo ============================================================
echo Starting Hangeul Admin API, Local LLM & Telegram Agent...
echo ============================================================

set PYTHON_EXE=C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe

if not exist "%PYTHON_EXE%" (
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_EXE=python
    ) else (
        echo [ERROR] Python 3.11 is not found! Please check Python installation.
        pause
        exit /b 1
    )
)

echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" run.py
pause
