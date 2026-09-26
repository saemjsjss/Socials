@echo off
title Hangeul Bot watchdog
echo.
echo This adds a Windows task that checks every 5 minutes whether the bot is running,
echo and starts it again if it is not - after a crash as well as after a restart.
echo.
schtasks /Create /TN "HangeulBotWatchdog" /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"E:\BOT\watchdog.ps1\"" /SC MINUTE /MO 5 /RL LIMITED /F
echo.
echo Done. The log is E:\BOT\hangeul_watchdog.log
echo To remove it later:  schtasks /Delete /TN "HangeulBotWatchdog" /F
pause
