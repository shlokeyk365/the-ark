param([switch]$RestartApi)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'apps\api\.venv\Scripts\python.exe'
$vite = Join-Path $repoRoot 'node_modules\vite\bin\vite.js'
$logs = Join-Path $repoRoot 'work\local-servers'
if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $vite)) {
    throw 'Install the Python environment and npm dependencies first.'
}
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$apiListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($apiListener -and $RestartApi) {
    $apiProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($apiListener[0].OwningProcess)"
    $apiParent = Get-CimInstance Win32_Process -Filter "ProcessId=$($apiProcess.ParentProcessId)"
    $belongsToCheckout = ($apiProcess.CommandLine -like "*$repoRoot*") -or
        ($apiParent.ExecutablePath -eq $python -and $apiParent.CommandLine -match 'uvicorn\s+apps\.api\.main:app')
    if ($apiProcess.CommandLine -notmatch 'uvicorn\s+apps\.api\.main:app' -or
        !$belongsToCheckout) {
        throw 'Port 8000 belongs to a process this launcher did not identify as this Ark checkout. Stop that API terminal and retry.'
    }
    Stop-Process -Id $apiProcess.ProcessId
    $apiListener = $null
}
if (!$apiListener) {
    Start-Process -FilePath $python -ArgumentList '-m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000' -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'api.out.log') -RedirectStandardError (Join-Path $logs 'api.err.log') | Out-Null
}
$webListener = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if (!$webListener) {
    $node = (Get-Command node.exe).Source
    Start-Process -FilePath $node -ArgumentList ('"' + $vite + '" --host 127.0.0.1 --port 5173 --strictPort') -WorkingDirectory (Join-Path $repoRoot 'apps\web') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'web.out.log') -RedirectStandardError (Join-Path $logs 'web.err.log') | Out-Null
}
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $status = Invoke-RestMethod 'http://127.0.0.1:8000/intelligence/status' -TimeoutSec 2
        $web = Invoke-WebRequest 'http://127.0.0.1:5173/command-center' -UseBasicParsing -TimeoutSec 2
        if ($web.StatusCode -eq 200) {
            Write-Host 'Ark: http://127.0.0.1:5173/command-center'
            Write-Host ('Assistant configured: ' + $status.assistant_configured)
            Write-Host 'Private server configuration is read from the root .env.local on each chat request.'
            exit 0
        }
    } catch { Start-Sleep -Milliseconds 500 }
}
throw "Servers did not become ready. Inspect logs in $logs."
