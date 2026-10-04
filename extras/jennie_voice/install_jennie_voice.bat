@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title Jennie voice - autostart and watchdog
set "VOICE_DIR=%~dp0"
setlocal EnableDelayedExpansion
echo.
echo This makes the Jennie voice service start when you sign in to Windows (a Startup shortcut),
echo and adds a Windows task that checks it every 5 minutes and starts it again if it stopped
echo or stopped answering - after a crash as well as after a restart.
echo.
if not exist "!VOICE_DIR!.venv\Scripts\pythonw.exe" goto :nopython

REM 1) Startup shortcut JennieVoice.lnk -> wscript.exe "...\start_jennie_voice.vbs"
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $dir = $env:VOICE_DIR.TrimEnd('\'); $wsh = New-Object -ComObject WScript.Shell; $startupPath = [Environment]::GetFolderPath('Startup'); $shortcut = $wsh.CreateShortcut((Join-Path $startupPath 'JennieVoice.lnk')); $shortcut.TargetPath = 'wscript.exe'; $shortcut.Arguments = [char]34 + (Join-Path $dir 'start_jennie_voice.vbs') + [char]34; $shortcut.WorkingDirectory = $dir; $shortcut.WindowStyle = 7; $shortcut.Save(); Write-Host 'Created the startup shortcut:' $shortcut.FullName; Write-Host 'It runs:' $shortcut.TargetPath $shortcut.Arguments"
if errorlevel 1 goto :noshortcut

REM 2) Watchdog task, every 5 minutes, only while you are signed in, without admin rights.
REM The folder goes in as !VOICE_DIR! so that no character in its name can break the quoting.
REM schtasks refuses a /TR longer than 261 characters; that shows up as the error below.
schtasks /Create /TN "JennieVoiceWatchdog" /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"!VOICE_DIR!watchdog_jennie_voice.ps1\"" /SC MINUTE /MO 5 /RL LIMITED /F
if errorlevel 1 goto :notask
echo.
echo Done. Logs: "!VOICE_DIR!jennie_voice.log" and "!VOICE_DIR!jennie_watchdog.log"
echo To remove it later:  schtasks /Delete /TN "JennieVoiceWatchdog" /F
echo                 and  delete JennieVoice.lnk from shell:startup
pause
exit /b 0

:nopython
echo [ERROR] "!VOICE_DIR!.venv\Scripts\pythonw.exe" is missing.
echo Create the Python 3.12 environment in this folder first (see README.md and the top of requirements.txt).
pause
exit /b 1

:noshortcut
echo.
echo [ERROR] The startup shortcut was not created - see the message above.
pause
exit /b 1

:notask
echo.
echo [ERROR] The watchdog task was not created - see the message above.
echo If it says /TR is too long, move this folder to a shorter path.
pause
exit /b 1
