@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title Enable 24/7 Autostart for Hangeul Bot
if not exist "%~dp0.venv\Scripts\pythonw.exe" goto :nopython
echo Configuring Hangeul Bot to launch automatically when you sign in to Windows...
set "BOT_DIR=%~dp0"
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $dir = $env:BOT_DIR.TrimEnd('\'); $wsh = New-Object -ComObject WScript.Shell; $startupPath = [Environment]::GetFolderPath('Startup'); $shortcut = $wsh.CreateShortcut((Join-Path $startupPath 'HangeulBot.lnk')); $shortcut.TargetPath = 'wscript.exe'; $shortcut.Arguments = [char]34 + (Join-Path $dir 'start_background.vbs') + [char]34; $shortcut.WorkingDirectory = $dir; $shortcut.WindowStyle = 7; $shortcut.Save(); Write-Host 'Successfully created startup shortcut at:' $shortcut.FullName; Write-Host 'It runs:' $shortcut.TargetPath $shortcut.Arguments"
if errorlevel 1 goto :failed
echo Successfully enabled autostart.
exit /b 0

:nopython
echo [ERROR] "%~dp0.venv\Scripts\pythonw.exe" is missing.
echo Create the Python 3.12 environment in this folder first (see the top of requirements.txt).
pause
exit /b 1

:failed
echo [ERROR] The startup shortcut was not created - see the message above.
pause
exit /b 1
