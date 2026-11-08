# StudyRelay startup script for Windows PowerShell
# Starts PowerContext Server and the StudyRelay application.

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $ProjectDir ".data\powercontext"
$AppPort = if ($env:APP_PORT) { $env:APP_PORT } else { 18080 }
$PcPort = if ($env:PC_PORT) { $env:PC_PORT } else { 18000 }

Write-Host "=== StudyRelay Startup ===" -ForegroundColor Cyan

# Create data directory
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    Write-Host "Created data directory: $DataDir"
}

# Set environment
$env:POWERCONTEXT_HOME = $DataDir
$env:POWERCONTEXT_URL = "http://127.0.0.1:$PcPort"

# Check if PowerContext server is already running
$pcAlreadyRunning = $false
try {
    $healthResp = Invoke-WebRequest -Uri "http://127.0.0.1:$PcPort/health/live" -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($healthResp.StatusCode -eq 200) {
        Write-Host "PowerContext Server already running on port $PcPort" -ForegroundColor Green
        $pcAlreadyRunning = $true
    }
} catch {
    $pcAlreadyRunning = $false
}

# Start PowerContext Server if not running
$pcProcess = $null
if (-not $pcAlreadyRunning) {
    Write-Host "Starting PowerContext Server on port $PcPort..." -ForegroundColor Yellow
    $pcProcess = Start-Process -FilePath "powercontext" -ArgumentList "server", "run", "--port", "$PcPort", "--no-env-file" -PassThru -WindowStyle Hidden
    Write-Host "PowerContext Server PID: $($pcProcess.Id)"

    # Wait for server to be ready
    $maxWait = 30
    $waited = 0
    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 1
        $waited++
        try {
            $healthResp = Invoke-WebRequest -Uri "http://127.0.0.1:$PcPort/health/live" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($healthResp.StatusCode -eq 200) {
                Write-Host "PowerContext Server ready (waited ${waited}s)" -ForegroundColor Green
                break
            }
        } catch {
            # Not ready yet
        }
    }
    if ($waited -ge $maxWait) {
        Write-Host "WARNING: PowerContext Server did not become ready within ${maxWait}s" -ForegroundColor Red
        Write-Host "The application will start but memory operations may fail." -ForegroundColor Yellow
    }
}

# Start the StudyRelay application
Write-Host "Starting StudyRelay application on port $AppPort..." -ForegroundColor Yellow
Write-Host "Open http://127.0.0.1:$AppPort in your browser" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray

try {
    Set-Location $ProjectDir
    python -m uvicorn app.main:app --host 127.0.0.1 --port $AppPort --reload
} finally {
    # Cleanup: stop PowerContext if we started it
    if ($pcProcess -and -not $pcAlreadyRunning) {
        Write-Host "Stopping PowerContext Server (PID $($pcProcess.Id))..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $pcProcess.Id -Force -ErrorAction SilentlyContinue
        } catch {
            # Process may have already exited
        }
    }
    Write-Host "StudyRelay stopped." -ForegroundColor Cyan
}
