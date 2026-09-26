@echo off
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" goto :nopython
echo ============================================================
echo    HANGEUL BOT  -  BUILD PROGRESS SHEETS  (live portal data)
echo ============================================================
echo.
echo Building all four program sheets into the ALL STUDENTS Drive folder...
echo (Korean Language, EAP, Bachelor, Master - each into its intake folder.)
echo.
"%PY%" -m src.sheets.progress_builder --all
echo.
echo Done. Open your ALL STUDENTS Drive folder to see the sheets.
pause
exit /b

:nopython
echo [ERROR] "%PY%" is missing.
echo Create the Python 3.12 environment in this folder first (see the top of requirements.txt).
pause
exit /b 1
