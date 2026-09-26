# Starts the Hangeul bot if it is not running.
# Called every few minutes by the scheduled task that install_watchdog.bat creates,
# so the bot comes back by itself after a crash as well as after a restart.
$ErrorActionPreference = "SilentlyContinue"

$log   = Join-Path $PSScriptRoot "hangeul_watchdog.log"
$venv  = Join-Path $PSScriptRoot ".venv\Scripts\"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"

# The bot is run.py under this folder's venv interpreter - python.exe from start.bat or
# pythonw.exe from start_background.vbs. The venv's python(w).exe is only a redirector: it
# starts the real Python312 python(w).exe as its child with the same arguments.
$python   = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"
$redirect = @($python | Where-Object { $_.ExecutablePath -and
                                       $_.ExecutablePath.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) -and
                                       $_.CommandLine -match '\brun\.py\b' })
$running  = $redirect + @($python | Where-Object { $redirect.ProcessId -contains $_.ParentProcessId })

if ($running) {
    Add-Content -LiteralPath $log -Value "$stamp  running (pid $($running.ProcessId))" -Encoding utf8
    exit 0
}

$pythonw = Join-Path $venv "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) {
    Add-Content -LiteralPath $log -Value "$stamp  not running - cannot start it, $pythonw is missing" -Encoding utf8
    exit 1
}

Add-Content -LiteralPath $log -Value "$stamp  not running - starting it" -Encoding utf8
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$(Join-Path $PSScriptRoot 'start_background.vbs')`"" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
