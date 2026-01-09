# test_sensor.ps1
# Test script for sensor.py (runs on host)

param (
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

Write-Host "=== Testing Sensor Module ===" -ForegroundColor Cyan

try {
    # Verify Python is available
    python --version
    if ($LASTEXITCODE -ne 0) { throw "Python not found" }
    
    Write-Host "`nRunning sensor.py..." -ForegroundColor Yellow
    
    if ($Verbose) {
        python "$ScriptDir\modules\sensor.py"
    } else {
        python "$ScriptDir\modules\sensor.py"
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Sensor completed successfully!" -ForegroundColor Green
        
        # Show the latest log file
        $LatestLog = Get-ChildItem "$ScriptDir\data\logs\sensor_log_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($LatestLog) {
            Write-Host "`nLatest log file: $($LatestLog.Name)" -ForegroundColor Cyan
            Write-Host "Size: $([math]::Round($LatestLog.Length / 1KB, 2)) KB" -ForegroundColor Cyan
        }
    } else {
        throw "Sensor failed with exit code $LASTEXITCODE"
    }
    
} catch {
    Write-Host "`n[ERROR] $_" -ForegroundColor Red
    exit 1
}
