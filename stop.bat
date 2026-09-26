@echo off
title Stop Hangeul Bot & API
echo Stopping background Hangeul services...
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Stopped PID:' $_.ProcessId }"
echo Done.
pause
