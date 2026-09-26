@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title Hangeul Bot Status
echo ============================================================
echo Checking Hangeul Bot ^& API Background Status...
echo ============================================================
set "BOT_DIR=%~dp0"
REM Same matching as stop.bat: only this folder's run.py and its "-m src.*" jobs.
powershell -NoProfile -Command "$v = $env:BOT_DIR + '.venv\Scripts\'; $all = @(Get-CimInstance Win32_Process); $python = @($all | Where-Object { $_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' }); $venv = @($python | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($v, [StringComparison]::OrdinalIgnoreCase) }); $run = @($venv | Where-Object { $_.CommandLine -match '\brun\.py\b' }); $run += @($python | Where-Object { $run.ProcessId -contains $_.ParentProcessId }); $jobs = @($venv | Where-Object { $_.CommandLine -match '\s-m\s+src\.' -and ($run.ProcessId -contains $_.ParentProcessId -or $all.ProcessId -notcontains $_.ParentProcessId) }); $jobs += @($python | Where-Object { $jobs.ProcessId -contains $_.ParentProcessId }); $bot = $run + $jobs; if ($bot) { $bot | Format-Table ProcessId, ParentProcessId, Name, CommandLine -AutoSize -Wrap } else { Write-Host 'The bot is not running.' }"
echo.
echo ============================================================
echo Latest 25 Lines of Log (hangeul_bot.log):
echo ============================================================
powershell -NoProfile -Command "$log = $env:BOT_DIR + 'hangeul_bot.log'; if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 25 -Encoding UTF8 } else { Write-Host 'No log file found yet.' }"
echo.
pause
