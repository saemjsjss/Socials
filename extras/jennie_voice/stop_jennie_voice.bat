@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title Stop Jennie voice
echo Stopping the Jennie voice service...
set "VOICE_DIR=%~dp0"
REM Only this folder's service: service.py under .venv\Scripts\python.exe or pythonw.exe, and the Python312
REM process that redirector starts. The watchdog task starts it again within 5 minutes unless it is disabled:
REM   schtasks /Change /TN "JennieVoiceWatchdog" /DISABLE
powershell -NoProfile -Command "$v = $env:VOICE_DIR + '.venv\Scripts\'; $python = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' }); $svc = @($python | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($v, [StringComparison]::OrdinalIgnoreCase) -and $_.CommandLine -match '\bservice\.py\b' }); $svc += @($python | Where-Object { $svc.ProcessId -contains $_.ParentProcessId }); if (-not $svc) { Write-Host 'The Jennie voice service is not running.' }; $svc | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host 'Stopped PID:' $_.ProcessId $_.CommandLine }"
echo Done.
if /i not "%~1"=="nopause" pause
