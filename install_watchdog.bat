@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title Hangeul Bot watchdog
set "BOT_DIR=%~dp0"
setlocal EnableDelayedExpansion
echo.
echo This adds a Windows task that checks every 5 minutes whether the bot is running,
echo and starts it again if it is not - after a crash as well as after a restart.
echo.
if not exist "!BOT_DIR!.venv\Scripts\pythonw.exe" goto :nopython
REM The folder goes in as !BOT_DIR! so that no character in its name can break the quoting.
REM schtasks refuses a /TR longer than 261 characters; that shows up as the error below.
schtasks /Create /TN "HangeulBotWatchdog" /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"!BOT_DIR!watchdog.ps1\"" /SC MINUTE /MO 5 /RL LIMITED /F
if errorlevel 1 goto :failed
echo.
echo Done. The log is "!BOT_DIR!hangeul_watchdog.log"
echo To remove it later:  schtasks /Delete /TN "HangeulBotWatchdog" /F
pause
exit /b 0

:nopython
echo [ERROR] "!BOT_DIR!.venv\Scripts\pythonw.exe" is missing.
echo Create the Python 3.12 environment in this folder first (see the top of requirements.txt).
pause
exit /b 1

:failed
echo.
echo [ERROR] The watchdog task was not created - see the message above.
echo If it says /TR is too long, move this folder to a shorter path.
pause
exit /b 1
