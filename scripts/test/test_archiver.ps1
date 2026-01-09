# test_archiver.ps1
# Test script for archiver.py (runs in Docker)

param (
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

Write-Host "=== Testing Archiver Module ===" -ForegroundColor Cyan

try {
    # Check Docker
    docker info | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }
    
    Write-Host "Docker is running [OK]" -ForegroundColor Green
    
    # Run archiver
    Write-Host "`nRunning archiver.py..." -ForegroundColor Yellow
    docker compose run --rm core python modules/archiver.py
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Archiver completed successfully!" -ForegroundColor Green
        
        # Show weekly summary if exists
        $WeeklySummaries = Get-ChildItem "$ScriptDir\data\journals\weekly_*" -ErrorAction SilentlyContinue | 
            Sort-Object LastWriteTime -Descending | 
            Select-Object -First 3
        
        if ($WeeklySummaries) {
            Write-Host "`nRecent weekly summaries:" -ForegroundColor Cyan
            foreach ($summary in $WeeklySummaries) {
                Write-Host "  - $($summary.Name)" -ForegroundColor Gray
            }
        }
    } else {
        throw "Archiver failed with exit code $LASTEXITCODE"
    }
    
} catch {
    Write-Host "`n[ERROR] $_" -ForegroundColor Red
    exit 1
}
