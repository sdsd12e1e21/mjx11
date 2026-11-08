# StudyRelay startup script for Windows PowerShell.
$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $ProjectDir ".data/powercontext"
$AppPort = if ($env:APP_PORT) { $env:APP_PORT } else { 18080 }
$PcPort = if ($env:PC_PORT) { $env:PC_PORT } else { 18000 }
$maxWait = if ($env:PC_START_TIMEOUT) { [int]$env:PC_START_TIMEOUT } else { 60 }
if ($maxWait -lt 1) { throw "PC_START_TIMEOUT must be a positive number of seconds." }
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
$env:POWERCONTEXT_HOME = $DataDir
$env:POWERCONTEXT_URL = "http://127.0.0.1:$PcPort"
$stdoutLog = Join-Path $DataDir "server.stdout.log"
$stderrLog = Join-Path $DataDir "server.stderr.log"
function Test-PowerContextReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$env:POWERCONTEXT_URL/health/live" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch { return $false }
}
$pcProcess = $null
Push-Location $ProjectDir
try {
    if (Test-PowerContextReady) {
        Write-Host "Reusing PowerContext at $env:POWERCONTEXT_URL"
    } else {
        Write-Host "Starting PowerContext at $env:POWERCONTEXT_URL"
        $pcProcess = Start-Process -FilePath "powercontext" -ArgumentList "server", "run", "--host", "127.0.0.1", "--port", "$PcPort", "--no-env-file" -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $ready = $false
        while ($timer.Elapsed.TotalSeconds -lt $maxWait) {
            $pcProcess.Refresh()
            if ($pcProcess.HasExited) {
                throw "PowerContext exited before becoming ready (exit $($pcProcess.ExitCode)). Logs: $stdoutLog ; $stderrLog"
            }
            if (Test-PowerContextReady) { $ready = $true; break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $ready) {
            throw "PowerContext did not become ready within ${maxWait}s. StudyRelay was not started. Logs: $stdoutLog ; $stderrLog"
        }
    }
    Write-Host "Open http://127.0.0.1:$AppPort ; press Ctrl+C to stop."
    python -m uvicorn app.main:app --host 127.0.0.1 --port $AppPort --reload
    if ($LASTEXITCODE -ne 0) { throw "StudyRelay exited with code $LASTEXITCODE." }
} finally {
    # Only stop the process tree started here; reused servers stay up.
    if ($pcProcess) {
        $pcProcess.Refresh()
        if (-not $pcProcess.HasExited) {
            & taskkill.exe /PID $pcProcess.Id /T /F 2>$null | Out-Null
        }
    }
    Pop-Location
}
