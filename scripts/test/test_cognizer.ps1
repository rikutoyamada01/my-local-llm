# test_cognizer.ps1
# Test script for cognizer.py (runs in Docker)

param (
    [string]$LogFile = "",
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

Write-Host "=== Testing Cognizer Module ===" -ForegroundColor Cyan

try {
    # Check Docker
    docker info | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }
    
    Write-Host "Docker is running [OK]" -ForegroundColor Green
    
    # Build command
    if ($LogFile) {
        # Test with specific log file
        $LogFileName = Split-Path -Leaf $LogFile
        Write-Host "`nProcessing specific log: $LogFileName" -ForegroundColor Yellow
        $PythonArgs = "data/logs/$LogFileName"
    } else {
        # Process all unprocessed logs
        Write-Host "`nProcessing all unprocessed logs..." -ForegroundColor Yellow
        $PythonArgs = ""
    }
    
    # Run in Docker
    Write-Host "Running in Docker container..." -ForegroundColor Cyan
    if ($PythonArgs) {
        docker compose run --rm core python modules/cognizer.py $PythonArgs
    } else {
        docker compose run --rm core python modules/cognizer.py
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Cognizer completed successfully!" -ForegroundColor Green
        
        Write-Host "`n[INFO] Journal file has been generated." -ForegroundColor Cyan
        Write-Host "Please check your Obsidian Vault directory (defined in docker-compose.yml):" -ForegroundColor White
        Write-Host "Path: Documents\Obsidian\Vault\DailyActivity" -ForegroundColor Yellow
        
        # Try to show content if we can find it in the standard location
        $VaultPath = "$env:USERPROFILE\Documents\Obsidian\Vault\DailyActivity"
        if (Test-Path $VaultPath) {
            $LatestJournal = Get-ChildItem "$VaultPath\*_daily.md" -ErrorAction SilentlyContinue | 
                Sort-Object LastWriteTime -Descending | 
                Select-Object -First 1
            
            if ($LatestJournal) {
                Write-Host "`nLatest journal found: $($LatestJournal.Name)" -ForegroundColor Cyan
                if ($Verbose) {
                    Write-Host "`n--- Journal Content ---" -ForegroundColor Yellow
                    Get-Content $LatestJournal.FullName
                }
            } else {
                 Write-Host "`nNo journal file found in $VaultPath" -ForegroundColor Yellow
            }
        }
    } else {
        throw "Cognizer failed with exit code $LASTEXITCODE"
    }
    
} catch {
    Write-Host "`n[ERROR] $_" -ForegroundColor Red
    exit 1
}
