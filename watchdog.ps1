# Starts the Hangeul bot if it is not running.
# Called every few minutes by the scheduled task that install_watchdog.bat creates,
# so the bot comes back by itself after a crash as well as after a restart.
$ErrorActionPreference = "SilentlyContinue"

$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
           Where-Object { $_.CommandLine -like "*run.py*" }

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
if ($running) {
    Add-Content -Path "E:\BOT\hangeul_watchdog.log" -Value "$stamp  running (pid $($running.ProcessId))" -Encoding utf8
    exit 0
}

Add-Content -Path "E:\BOT\hangeul_watchdog.log" -Value "$stamp  not running - starting it" -Encoding utf8
Start-Process -FilePath "wscript.exe" -ArgumentList '"E:\BOT\start_background.vbs"' -WorkingDirectory "E:\BOT" -WindowStyle Hidden
