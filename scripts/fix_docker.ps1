# fix_docker.ps1
# Script to fix Docker Desktop startup issues

param (
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"

Write-Host "=== Docker Desktop Troubleshooting ===" -ForegroundColor Cyan

# Step 1: Check if Docker is already running properly
Write-Host "`n[1/5] Checking Docker status..." -ForegroundColor Yellow
try {
    docker info | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Docker is already running properly!" -ForegroundColor Green
        exit 0
    }
} catch {
    Write-Host "[INFO] Docker is not responding, proceeding with fix..." -ForegroundColor Yellow
}

# Step 2: Stop all Docker processes
Write-Host "`n[2/5] Stopping all Docker processes..." -ForegroundColor Yellow
$dockerProcesses = Get-Process | Where-Object {$_.Name -like "*docker*" -or $_.Name -like "com.docker*"}
foreach ($proc in $dockerProcesses) {
    try {
        Write-Host "  Stopping: $($proc.Name) (PID: $($proc.Id))" -ForegroundColor Gray
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "  Failed to stop $($proc.Name)" -ForegroundColor Yellow
    }
}
Start-Sleep -Seconds 5

# Step 3: Stop Docker service
Write-Host "`n[3/5] Stopping Docker service..." -ForegroundColor Yellow
try {
    Stop-Service -Name "com.docker.service" -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Docker service stopped" -ForegroundColor Green
} catch {
    Write-Host "[WARN] Could not stop Docker service (may not be running)" -ForegroundColor Yellow
}

# Step 4: Clean up potential lock files (optional with -Force)
if ($Force) {
    Write-Host "`n[4/5] Cleaning Docker data (Force mode)..." -ForegroundColor Yellow
    $dockerDataPath = "$env:APPDATA\Docker"
    if (Test-Path $dockerDataPath) {
        Write-Host "  Removing lock files..." -ForegroundColor Gray
        Remove-Item "$dockerDataPath\*.lock" -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "`n[4/5] Skipping data cleanup (use -Force to enable)" -ForegroundColor Gray
}

# Step 5: Restart Docker Desktop
Write-Host "`n[5/5] Starting Docker Desktop..." -ForegroundColor Yellow
$dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"

if (-not (Test-Path $dockerPath)) {
    Write-Host "[ERROR] Docker Desktop not found at: $dockerPath" -ForegroundColor Red
    exit 1
}

Start-Process -FilePath $dockerPath
Write-Host "[OK] Docker Desktop started" -ForegroundColor Green

# Wait for Docker to initialize
Write-Host "`nWaiting for Docker to initialize (this may take 1-2 minutes)..." -ForegroundColor Cyan
for ($i = 1; $i -le 24; $i++) {
    Start-Sleep -Seconds 5
    Write-Host "." -NoNewline
    
    # Try to connect
    try {
        $null = docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "`n`n[SUCCESS] Docker is now running!" -ForegroundColor Green
            Write-Host "`nDocker info:" -ForegroundColor Cyan
            docker version --format "Client: {{.Client.Version}}, Server: {{.Server.Version}}"
            exit 0
        }
    } catch {
        # Continue waiting
    }
}

Write-Host "`n`n[WARN] Docker did not start within 2 minutes." -ForegroundColor Yellow
Write-Host "Please try the following:" -ForegroundColor Yellow
Write-Host "1. Check Docker Desktop GUI for error messages" -ForegroundColor White
Write-Host "2. Try running: .\fix_docker.ps1 -Force" -ForegroundColor White
Write-Host "3. Restart your computer" -ForegroundColor White
Write-Host "4. Reinstall Docker Desktop" -ForegroundColor White

exit 1
