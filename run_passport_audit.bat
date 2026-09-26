@echo off
REM ============================================================
REM  Double-click this file to cross-check EVERY Bachelor's
REM  Degree student's passport against the portal and open the
REM  report in Excel. Read-only: it never edits the portal.
REM  For another program, edit the quoted name on the python
REM  line below, or run in this folder:
REM    .venv\Scripts\python.exe audit_program.py "Master's Degree"
REM ============================================================
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" goto :nopython
echo.
echo Passport cross-check for: Bachelor's Degree
echo (Logging in, then OCR on ~50 scans -- this takes a few minutes.)
echo.
"%PY%" audit_program.py "Bachelor's Degree"
echo.
echo Finished. The CSV report is in this folder and should
echo have opened in Excel. You can close this window.
pause
exit /b

:nopython
echo [ERROR] "%PY%" is missing.
echo Create the Python 3.12 environment in this folder first (see the top of requirements.txt).
pause
exit /b 1
