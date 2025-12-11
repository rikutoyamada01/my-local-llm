# run_nightly_batch.ps1
# Nightly Orchestrator for Digital Twin

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$ProjectRoot = $ScriptDir
$LogFile = "$ProjectRoot\data\logs\pipeline.log"

function Write-Log {
    param($Message)
    $TimeStamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogEntry = "$TimeStamp - $Message"
    Write-Host $LogEntry
}

# --- Configuration Parsing ---
# Read secrets.yaml to get the Host Vault Path
$SecretsPath = "$ProjectRoot\config\secrets.yaml"
if (Test-Path $SecretsPath) {
    $SecretsContent = Get-Content -Raw $SecretsPath
    # Simple parsing to avoid YAML dependency requirement in PowerShell
    if ($SecretsContent -match 'obsidian_vault_path_host:\s*["'']?([^"''\r\n]+)["'']?') {
        $VaultPath = $matches[1]
        Write-Log "Config: Found Obsidian Vault at $VaultPath"
        $env:OBSIDIAN_VAULT_PATH = $VaultPath
    } else {
        Write-Log "Warning: 'obsidian_vault_path_host' not found in secrets.yaml"
    }
} else {
    Write-Log "Warning: secrets.yaml not found."
}

Start-Transcript -Path $LogFile -Append

try {
    Write-Log "=== Starting Nightly Batch ==="

    # 1. Perception Phase (Host)
    Write-Log "Step 1: Running Sensor (Host)..."
    python "$ProjectRoot\modules\sensor.py"
    if ($LASTEXITCODE -ne 0) { throw "Sensor failed with exit code $LASTEXITCODE" }

    # 2. Cognition Phase (Docker)
    Write-Log "Step 2: Start Cognition (Docker)..."
    # We use 'docker compose run' to execute the one-off task
    Set-Location $ProjectRoot
    docker compose run --rm core python modules/cognizer.py
    if ($LASTEXITCODE -ne 0) { throw "Cognizer failed with exit code $LASTEXITCODE" }

    # 3. Memory Phase (Weekly Rollup)
    Write-Log "Step 3: Running Archiver (Docker)..."
    docker compose run --rm core python modules/archiver.py
    
    # 4. Training Check (Optional)
    # Check if we should train (e.g., is it Sunday?)
    $DayOfWeek = (Get-Date).DayOfWeek
    if ($DayOfWeek -eq "Sunday") {
        Write-Log "Step 4: Weekly Training (Trainer Container)..."
        # Note: This might take hours. Run detached or blocking? Blocking for now.
        # Ensure --gpus all is active in compose or via command line
        docker compose run --rm --gpus all trainer python modules/trainer.py
    } else {
        Write-Log "Skipping Training (Not Sunday)."
    }

    Write-Log "=== Batch Completed Successfully ==="

} catch {
    Write-Log "FATAL ERROR: $_"
    exit 1
} finally {
    Stop-Transcript
}
