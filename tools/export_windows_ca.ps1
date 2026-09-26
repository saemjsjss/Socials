# Export this machine's trusted root certificates to data\windows-ca.pem
#
# Run this when Python cannot verify HTTPS certificates but a browser can — the symptom
# is CERTIFICATE_VERIFY_FAILED on every request, including pip. It happens when antivirus
# HTTPS scanning or the ISP intercepts TLS with a root that Windows trusts and Python's
# bundled certifi list does not ship.
#
#   powershell -ExecutionPolicy Bypass -File tools\export_windows_ca.ps1
#
# Afterwards, append it to certifi's bundle so httpx, requests and the Google client all
# see it (src\__init__.py only sets the environment variables, which some clients ignore):
#
#   python -c "import certifi,shutil,pathlib; b=pathlib.Path(certifi.where()); shutil.copy2(b, b.with_suffix('.pem.original')); b.write_text(b.read_text(encoding='utf-8') + open(r'data\windows-ca.pem', encoding='utf-8').read(), encoding='utf-8'); print('done')"

$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "data\windows-ca.pem"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null

$sb = New-Object System.Text.StringBuilder
$stores = @("Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root",
            "Cert:\LocalMachine\CA", "Cert:\CurrentUser\CA")
$seen = @{}
$n = 0

foreach ($s in $stores) {
    Get-ChildItem $s -ErrorAction SilentlyContinue | ForEach-Object {
        if (-not $seen.ContainsKey($_.Thumbprint)) {
            $seen[$_.Thumbprint] = $true
            $b64 = [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks')
            [void]$sb.AppendLine("# Subject: $($_.Subject)")
            [void]$sb.AppendLine("-----BEGIN CERTIFICATE-----")
            [void]$sb.AppendLine($b64)
            [void]$sb.AppendLine("-----END CERTIFICATE-----")
            $n++
        }
    }
}

[IO.File]::WriteAllText($out, $sb.ToString())
"exported $n certificates to $out"
"{0:N0} bytes" -f (Get-Item $out).Length
