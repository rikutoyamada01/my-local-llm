# scripts/install_host_dependencies.ps1
# Automates ActivityWatch download and directory setup

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$BinDir = "$ProjectRoot\bin"
$LogsDir = "$ProjectRoot\data\logs"
$JournalsDir = "$ProjectRoot\data\journals"

# 1. Create Directories
Write-Host "Creating directories..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $JournalsDir | Out-Null

# 2. ActivityWatch Versions (Windows)
$AwVersion = "v0.12.2" # Example stable version
$AwServerUrl = "https://github.com/ActivityWatch/activitywatch/releases/download/$AwVersion/activitywatch-$AwVersion-windows-x86_64.zip"

# 3. Download and Extract
$ZipPath = "$BinDir\activitywatch.zip"

if (-not (Test-Path "$BinDir\activitywatch")) {
    Write-Host "Downloading ActivityWatch ($AwVersion)..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $AwServerUrl -OutFile $ZipPath
    
    Write-Host "Extracting to $BinDir..."
    Expand-Archive -Path $ZipPath -DestinationPath $BinDir -Force
    
    # Rename for consistency
    $ExtractedFolder = Get-ChildItem -Path $BinDir -Filter "activitywatch-*-windows-x86_64" | Select-Object -First 1
    if ($ExtractedFolder) {
        Rename-Item -Path $ExtractedFolder.FullName -NewName "activitywatch"
    }
    
    Remove-Item -Path $ZipPath
} else {
    Write-Host "ActivityWatch already installed in $BinDir" -ForegroundColor Yellow
}

# 4. Setup Scheduled Task
$TaskName = "StartActivityWatch"
$Action = New-ScheduledTaskAction -Execute "$BinDir\activitywatch\aw-qt.exe"
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0

Write-Host "Registering Scheduled Task: $TaskName..."
Register-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -TaskName $TaskName -Description "Auto-start ActivityWatch for Digital Twin" -Force | Out-Null

Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "ActivityWatch has been started and scheduled."
Start-Process -FilePath "$BinDir\activitywatch\aw-qt.exe"
