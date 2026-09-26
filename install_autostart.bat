@echo off
title Enable 24/7 Autostart for Hangeul Bot
echo Configuring Hangeul Bot to launch automatically on Windows boot...
powershell -Command "$wsh = New-Object -ComObject WScript.Shell; $startupPath = [Environment]::GetFolderPath('Startup'); $shortcut = $wsh.CreateShortcut(\"$startupPath\HangeulBot.lnk\"); $shortcut.TargetPath = 'wscript.exe'; $shortcut.Arguments = '\"E:\BOT\start_background.vbs\"'; $shortcut.WorkingDirectory = 'E:\BOT'; $shortcut.WindowStyle = 7; $shortcut.Save(); Write-Host 'Successfully created startup shortcut at:' $shortcut.FullName"
echo Successfully enabled autostart.
