# test_reviewer.ps1
# Test script for reviewer.py (runs in Docker)

param (
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

Write-Host "=== Testing Reviewer Module ===" -ForegroundColor Cyan

try {
    # Check Docker
    docker info | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }
    
    Write-Host "Docker is running [OK]" -ForegroundColor Green
    
    # Run reviewer
    Write-Host "`nRunning reviewer.py..." -ForegroundColor Yellow
    docker compose run --rm core python modules/reviewer.py
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Reviewer completed successfully!" -ForegroundColor Green
        
        Write-Host "`n[INFO] Review files generated in Obsidian Vault:" -ForegroundColor Cyan
        Write-Host "Path: Documents\Obsidian\Vault\DailyActivity" -ForegroundColor Yellow
        
        # Try to show content if we can find it in the standard location
        $VaultPath = "$env:USERPROFILE\Documents\Obsidian\Vault\DailyActivity"
        if (Test-Path $VaultPath) {
            # Show monthly reviews
            $MonthlyReviews = Get-ChildItem "$VaultPath\*_monthly.md" -ErrorAction SilentlyContinue | 
                Sort-Object LastWriteTime -Descending | 
                Select-Object -First 3
            
            if ($MonthlyReviews) {
                Write-Host "`nRecent monthly reviews:" -ForegroundColor Cyan
                foreach ($review in $MonthlyReviews) {
                    Write-Host "  - $($review.Name)" -ForegroundColor White
                }
                
                if ($Verbose -and $MonthlyReviews) {
                    Write-Host "`n--- Latest Monthly Review ---" -ForegroundColor Yellow
                    Get-Content $MonthlyReviews[0].FullName
                }
            }
            
            # Show yearly reviews
            $YearlyReviews = Get-ChildItem "$VaultPath\*_yearly.md" -ErrorAction SilentlyContinue | 
                Sort-Object LastWriteTime -Descending | 
                Select-Object -First 3
            
            if ($YearlyReviews) {
                Write-Host "`nRecent yearly reviews:" -ForegroundColor Cyan
                foreach ($review in $YearlyReviews) {
                    Write-Host "  - $($review.Name)" -ForegroundColor White
                }
                
                if ($Verbose -and $YearlyReviews) {
                    Write-Host "`n--- Latest Yearly Review ---" -ForegroundColor Yellow
                    Get-Content $YearlyReviews[0].FullName
                }
            }
        }
    } else {
        throw "Reviewer failed with exit code $LASTEXITCODE"
    }
    
} catch {
    Write-Host "`n[ERROR] $_" -ForegroundColor Red
    exit 1
}
