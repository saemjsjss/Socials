@echo off
REM ============================================================
REM  Double-click this file to cross-check EVERY Bachelor's
REM  Degree student's passport against the portal and open the
REM  report in Excel. Read-only: it never edits the portal.
REM  For another program, edit the quoted name on the python
REM  line below, or run:  python audit_program.py "Master's Degree"
REM ============================================================
cd /d "%~dp0"
echo.
echo Passport cross-check for: Bachelor's Degree
echo (Logging in, then OCR on ~50 scans -- this takes a few minutes.)
echo.
python audit_program.py "Bachelor's Degree"
echo.
echo Finished. The CSV report is in this folder (E:\BOT) and should
echo have opened in Excel. You can close this window.
pause
