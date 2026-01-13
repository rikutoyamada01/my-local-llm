# run_nightly_batch.ps1
# Nightly Orchestrator for Digital Twin

param (
    [switch]$NoSleep = $false
)

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

# --- Power Management (Prevent Sleep) ---
$signature = @"
[DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
public static extern int SetThreadExecutionState(int esFlags);
"@

$ES_CONTINUOUS = [int]0x80000000
$ES_SYSTEM_REQUIRED = [int]0x00000001
# $ES_DISPLAY_REQUIRED = [int]0x00000002 # Uncomment if display is needed

try {
    $power = Add-Type -MemberDefinition $signature -Name "Win32Power" -Namespace Win32Functions -PassThru
} catch {
    # If type is already added (e.g. in same session), ignore error
    $power = [Win32Functions.Win32Power]
}

function Prevent-Sleep {
    Write-Log "Power: preventing system sleep..."
    $power::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) | Out-Null
}

function Allow-Sleep {
    Write-Log "Power: allowing system sleep..."
    $power::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
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
    Prevent-Sleep

    Write-Log "=== Starting Nightly Batch ==="
    Write-Log "Options: NoSleep=$NoSleep"

    # 0. Ensure Docker is Running
    $DockerProcess = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
    if (-not $DockerProcess) {
        Write-Log "Docker Desktop is not running. Starting it..."
        $DockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        if (Test-Path $DockerPath) {
            Start-Process -FilePath $DockerPath
            Write-Log "Waiting for Docker to initialize (this may take a few minutes)..."
            
            # Wait loop (up to 5 minutes)
            for ($i = 0; $i -lt 30; $i++) {
                Start-Sleep -Seconds 10
                # Use cmd /c to avoid PowerShell's ErrorActionPreference triggering on stderr warnings
                cmd /c "docker info > NUL 2>&1"
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "Docker is ready!"
                    break
                }
                Write-Host "." -NoNewline
            }
            if ($LASTEXITCODE -ne 0) { throw "Docker failed to start within timeout." }
        } else {
            throw "Docker Desktop not found at $DockerPath. Please start it manually."
        }
    } else {
        Write-Log "Docker is running."
    }

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
    
    # 3.5. Review Phase (Monthly/Yearly Reviews)
    Write-Log "Step 3.5: Running Reviewer (Docker)..."
    docker compose run --rm core python modules/reviewer.py
    
    # 4. Training Check (Optional)
    # Check if we should train (e.g., is it Sunday?)
    $DayOfWeek = (Get-Date).DayOfWeek
    if ($DayOfWeek -eq "Sunday") {
        Write-Log "Step 4: Weekly Training (Trainer Container)..."
        # Note: This might take hours. Run detached or blocking? Blocking for now.
        # Ensure --gpus all is active in compose or via command line
        docker compose run --rm trainer python modules/trainer.py
        if ($LASTEXITCODE -ne 0) { throw "Trainer failed with exit code $LASTEXITCODE" }
    } else {
        Write-Log "Skipping Training (Not Sunday)."
    }

    Write-Log "=== Batch Completed Successfully ==="
    
    # 5. Sleep Logic
    if (-not $NoSleep) {
        Write-Log "Going to Sleep in 10 seconds..."
        Allow-Sleep # Reset state before suspending
        Start-Sleep -Seconds 10
        # Suspend (Sleep)
        # Note: This requires hibernation to be disabled for S3 sleep, or it might hibernate.
        # Arguments: Hibernate (0=Sleep), Force (1), WakeupEventsDisabled (0)
        [Console]::Beep(440, 200) # Beep to notify
        rundll32.exe powrprof.dll,SetSuspendState 0,1,0
    } else {
        Write-Log "Sleep skipped (-NoSleep flag active)."
    }

} catch {
    Write-Log "FATAL ERROR: $_"
    exit 1
} finally {
    Allow-Sleep
    Stop-Transcript
}
