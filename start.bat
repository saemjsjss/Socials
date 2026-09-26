@echo off
cd /d "%~dp0"
title Hangeul Admin API ^& Telegram Agent
echo ============================================================
echo Starting Hangeul Admin API, Local LLM ^& Telegram Agent...
echo ============================================================

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" goto :nopython

echo Using Python: "%PYTHON_EXE%"
"%PYTHON_EXE%" run.py
pause
exit /b

:nopython
echo [ERROR] "%PYTHON_EXE%" is missing.
echo Create the Python 3.12 environment in this folder first (see the top of requirements.txt).
pause
exit /b 1
