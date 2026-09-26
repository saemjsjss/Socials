@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo    HANGEUL BOT  -  APPLY UPDATE ^& RESTART  (one click)
echo ============================================================
echo.

REM --- 1) locate fresh files (E:\BOT first, then newest in Downloads) ---
set "BOTFILE="
if exist "%~dp0telegram_bot.py" set "BOTFILE=%~dp0telegram_bot.py"
if not defined BOTFILE (
  for /f "delims=" %%F in ('dir /b /o-d "%USERPROFILE%\Downloads\telegram_bot*.py" 2^>nul') do (
    set "BOTFILE=%USERPROFILE%\Downloads\%%F"
    goto :botdone
  )
)
:botdone
set "CFGFILE="
if exist "%~dp0config.py" set "CFGFILE=%~dp0config.py"
if not defined CFGFILE (
  for /f "delims=" %%F in ('dir /b /o-d "%USERPROFILE%\Downloads\config*.py" 2^>nul') do (
    set "CFGFILE=%USERPROFILE%\Downloads\%%F"
    goto :cfgdone
  )
)
:cfgdone

REM --- 2) stop every running bot copy (this also frees port 8000) ---
echo [1/5] Stopping any running bot processes (python)...
taskkill /F /IM python.exe  >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul

REM --- 3) install the fresh files into the right folders ---
if defined BOTFILE (
  echo [2/5] Installing telegram_bot.py  -^>  src\bot\
  copy /Y "!BOTFILE!" "%~dp0src\bot\telegram_bot.py" >nul
) else (
  echo [2/5] No fresh telegram_bot.py found; keeping existing src\bot\ copy.
)
if defined CFGFILE (
  echo       Installing config.py         -^>  src\
  copy /Y "!CFGFILE!" "%~dp0src\config.py" >nul
) else (
  echo       No fresh config.py found; keeping existing src\ copy.
)

REM --- 4) clear compiled cache so Python recompiles from the NEW source ---
echo [3/5] Clearing __pycache__ (forces a fresh compile)...
for /d /r "%~dp0" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

REM --- 5) verify BOTH files are the new versions ---
echo [4/5] Verifying installed files...
set "OK=1"
findstr /C:"crosscheck_range" "%~dp0src\bot\telegram_bot.py" >nul 2>&1 || set "OK=0"
findstr /C:"def authorized_ids" "%~dp0src\config.py" >nul 2>&1 || set "OK=0"
if "!OK!"=="0" (
  echo.
  echo    !!!  UPDATE INCOMPLETE:
  findstr /C:"crosscheck_range" "%~dp0src\bot\telegram_bot.py" >nul 2>&1 || echo        - src\bot\telegram_bot.py is missing 'crosscheck_range'
  findstr /C:"def authorized_ids" "%~dp0src\config.py" >nul 2>&1 || echo        - src\config.py is missing 'authorized_ids'
  echo    Put the file(s) I sent into E:\BOT (this folder) and run this again.
  echo.
  pause
  exit /b 1
)
echo        OK - telegram_bot.py and config.py are both up to date.

REM --- 6) start one fresh copy ---
echo [5/5] Starting the bot...
start "" "%~dp0start.bat"
echo.
echo ============================================================
echo  DONE. In the new black window look for:
echo    "Successfully set 9 ... bot menu commands"   and NO red Traceback.
echo  In Telegram, type "/"  then tap  /crosscheck_range
echo ============================================================
echo.
pause
