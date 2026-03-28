$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts_v2\orchestration\run_v2_incremental_cycle.py"
$logDir = Join-Path $root "data\logs"
$logPath = Join-Path $logDir "zhao_v2_incremental_live.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Push-Location $root
try {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "[$timestamp] starting scheduled V2 incremental cycle"
    & $python $script *>> $logPath
    $exitCode = $LASTEXITCODE
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "[$timestamp] finished scheduled V2 incremental cycle exit=$exitCode"
    exit $exitCode
}
finally {
    Pop-Location
}
