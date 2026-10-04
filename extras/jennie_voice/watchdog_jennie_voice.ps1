# Keeps the Jennie voice service alive: starts it when it is not running, and restarts it when
# http://127.0.0.1:8765/health fails twice in a row (two checks 20 seconds apart).
# Called every 5 minutes by the JennieVoiceWatchdog task that install_jennie_voice.bat creates,
# so the service comes back by itself after a crash, a hang, or a restart of the PC.
# /health also fails (HTTP 503, "ok": false) when one request has held the service's lock for over
# 10 minutes, which only a stalled GPU/driver call does - so a hang is restarted too.
$ErrorActionPreference = "SilentlyContinue"

$log          = Join-Path $PSScriptRoot "jennie_watchdog.log"
$venv         = Join-Path $PSScriptRoot ".venv\Scripts\"
$health       = "http://127.0.0.1:8765/health"
$graceMinutes = 5      # loading the models takes 1-3 minutes: a younger process is left alone
$stamp        = Get-Date -Format "yyyy-MM-dd HH:mm"

function Test-Health {
    try {
        $r = Invoke-RestMethod -Uri $health -TimeoutSec 15
        return [bool]$r.ok
    } catch {
        return $false
    }
}

function Write-Log($text) {
    Add-Content -LiteralPath $log -Value "$stamp  $text" -Encoding utf8
}

# The service is service.py under this folder's venv interpreter (pythonw.exe from start_jennie_voice.vbs,
# or python.exe when started by hand). The venv's python(w).exe is only a redirector: it starts the real
# Python312 python(w).exe as its child with the same arguments.
function Get-ServiceProcesses {
    $python   = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"
    $redirect = @($python | Where-Object { $_.ExecutablePath -and
                                           $_.ExecutablePath.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) -and
                                           $_.CommandLine -match '\bservice\.py\b' })
    return $redirect + @($python | Where-Object { $redirect.ProcessId -contains $_.ParentProcessId })
}

if (Test-Health) {
    Write-Log "healthy (pid $((Get-ServiceProcesses).ProcessId))"
    exit 0
}
Start-Sleep -Seconds 20
if (Test-Health) {
    Write-Log "healthy after one failed /health check (pid $((Get-ServiceProcesses).ProcessId))"
    exit 0
}

# Looked up only now, after both checks: a copy started during the 20 s wait (Startup shortcut, or by
# hand) is seen here and left to finish loading instead of being joined by a second one.
$running = Get-ServiceProcesses
if ($running) {
    $started = ($running | ForEach-Object { $_.CreationDate } | Sort-Object -Descending | Select-Object -First 1)
    if ($started -and ((Get-Date) - $started).TotalMinutes -lt $graceMinutes) {
        Write-Log "still starting up (pid $($running.ProcessId), started $($started.ToString('HH:mm'))) - left alone"
        exit 0
    }
    Write-Log "not answering /health twice - restarting it (pid $($running.ProcessId))"
    foreach ($p in $running) {
        Stop-Process -Id $p.ProcessId -Force
    }
    Start-Sleep -Seconds 5
} else {
    Write-Log "not running - starting it"
}

$pythonw = Join-Path $venv "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) {
    Write-Log "cannot start it: $pythonw is missing"
    exit 1
}
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$(Join-Path $PSScriptRoot 'start_jennie_voice.vbs')`"" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
