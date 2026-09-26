@echo off
title Hangeul Bot Status
echo ============================================================
echo Checking Hangeul Bot & API Background Status...
echo ============================================================
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run.py*' } | Select-Object ProcessId, CommandLine"
echo.
echo ============================================================
echo Latest 25 Lines of Log (hangeul_bot.log):
echo ============================================================
powershell -Command "if (Test-Path 'E:\BOT\hangeul_bot.log') { Get-Content 'E:\BOT\hangeul_bot.log' -Tail 25 } else { Write-Host 'No log file found yet.' }"
echo.
pause
