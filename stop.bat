@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title Stop Hangeul Bot ^& API
echo Stopping background Hangeul services...
set "BOT_DIR=%~dp0"
REM Only this folder's bot: run.py under .venv\Scripts\python.exe or pythonw.exe, the Python312
REM process that redirector starts, and the "-m src.*" jobs run.py starts, or left behind when it died.
powershell -NoProfile -Command "$v = $env:BOT_DIR + '.venv\Scripts\'; $all = @(Get-CimInstance Win32_Process); $python = @($all | Where-Object { $_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' }); $venv = @($python | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($v, [StringComparison]::OrdinalIgnoreCase) }); $run = @($venv | Where-Object { $_.CommandLine -match '\brun\.py\b' }); $run += @($python | Where-Object { $run.ProcessId -contains $_.ParentProcessId }); $jobs = @($venv | Where-Object { $_.CommandLine -match '\s-m\s+src\.' -and ($run.ProcessId -contains $_.ParentProcessId -or $all.ProcessId -notcontains $_.ParentProcessId) }); $jobs += @($python | Where-Object { $jobs.ProcessId -contains $_.ParentProcessId }); $bot = $run + $jobs; if (-not $bot) { Write-Host 'The bot is not running.' }; $bot | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host 'Stopped PID:' $_.ProcessId $_.CommandLine }"
echo Done.
if /i not "%~1"=="nopause" pause
