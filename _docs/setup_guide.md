# Local Digital Twin - Setup & Configuration Guide

**Version**: 1.0
**Status**: Draft
**Reference**: `README.md`, `_docs/detailed_design.md`

This document outlines the hardware requirements, automated installation steps, and necessary manual configurations for the Local Digital Twin project.

---

## 1. System Requirements

### Hardware
-   **OS**: Windows 11 (Build 22000 or later recommended).
-   **CPU**: Recent Multi-core processor (Intel i5/Ryzen 5 or better).
-   **RAM**: Minimum 16GB (32GB recommended for smooth LLM operation).
-   **GPU**: NVIDIA RTX 3060 (12GB VRAM) or better.
    -   *Required for Unsloth training and fast Ollama inference.*

### Software Prerequisites
-   **Docker Desktop**: Installed with WSL2 backend enabled.
-   **NVIDIA Container Toolkit**: For GPU passthrough to Docker.
-   **Python 3.10+**: Installed on Windows (Host) for the Sensor.
-   **Git**: For version control.
-   **ActivityWatch**: Installed on Host (Windows).

### 2.3 Ollama Setup (Windows)
1.  **Download**: Go to [ollama.com/download/windows](https://ollama.com/download/windows) and install the Windows preview.
2.  **Pull Model**: Open PowerShell and run:
    ```powershell
    ollama run llama3 "Hello Digital Twin"
    ```
    *This downloads the ~4.7GB model and verifies it works.*
3.  **Serve**: Ensure Ollama is running in the system tray (it serves on `localhost:11434` by default).

---

## 2. Setup Overview

This project uses a **Hybrid Architecture**:
1.  **Host (Windows)**: Runs `sensor.py` to capture locked files and Window activity.
2.  **Docker (WSL2)**: Runs the "Brain" (Cognition, Memory, Training) to ensure a clean, reproducible environment.

### 2.1 Host Setup (Sensor)
1.  Run the dependency script to set up ActivityWatch and local directories:
    ```powershell
    ./scripts/install_host_dependencies.ps1
    ```

### 2.2 Docker Setup (The Brain)
1.  Ensure Docker Desktop is running.
2.  Create `docker-compose.yml` in the root:

```yaml
version: '3.8'

services:
  chromadb:
    image: chromadb/chroma
    ports:
      - "8000:8000"
    volumes:
      - ./data/chroma:/chroma/chroma

  core:
    build: 
      context: .
      dockerfile: Dockerfile.core
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      # Mount existing Obsidian Vault (Update path below!)
      - /mnt/c/Users/YourName/YourVault:/obsidian_vault
    environment:
      - OBSIDIAN_MOUNT_PATH=/obsidian_vault
    depends_on:
      - chromadb
    extra_hosts:
      - "host.docker.internal:host-gateway"

  trainer:
    build:
      context: .
      dockerfile: Dockerfile.trainer
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ./data:/app/data
    command: python trainer.py --watch
```

3.  Build and Start:
    ```bash
    docker-compose up -d --build
    ```

---

## 3. Configuration

### 3.1 Secrets & Paths (`config/secrets.yaml`)
Create `config/secrets.yaml` and configure your vault path.

```yaml
# config/secrets.yaml

# 1. Obsidian Configuration
# ABSOLUTE PATH on Windows (Format: C:/Users/...)
obsidian_vault_path_host: "C:/Users/yamadarikuto/Documents/MyVault"

# 2. Domain Blocking & PII
blocked_domains:
  - "bank_of_america\.com"
sensitive_keywords:
  - "MySecretPassword"

# 3. LLM Configuration
ollama_host: "http://host.docker.internal:11434"
context_limit: 8192
```

### 3.2 Host Scripts
The `run_nightly_batch.ps1` script will now:
1.  Run `modules/sensor.py` natively.
2.  Trigger `docker compose run core ...` for processing.

---

## 4. Verification

### 4.1 Check Containers
Run `docker ps` to ensure `chromadb` is running.

### 4.2 Check Sensor (Host)
Run `python modules/sensor.py --dry-run` to verify it can read AW data and copy browser history.

### 4.3 Check Docker Connectivity
Run:
```bash
docker compose run core python -c "import requests; print(requests.get('http://host.docker.internal:5600/api/0/info').json())"
```
This confirms the Docker container can talk to ActivityWatch on the Host.

---

## 5. Troubleshooting

### 5.1 Empty Journals / No Logs
**Issue**: Daily journals say "no major activities", or `data/logs/` JSON files contain empty arrays `[]`.
**Cause**: ActivityWatch (`aw-qt.exe`) is not running or hasn't been installed correctly.
**Fix**:
1. Check if `aw-qt.exe` is running in Task Manager.
2. If not, manually start it from `bin/activitywatch/aw-qt.exe`.
3. If the folder is missing, re-run `./scripts/install_host_dependencies.ps1`.

### 5.2 Access Denied for Scheduled Tasks
**Issue**: `install_host_dependencies.ps1` fails with "Access is denied" when registering tasks.
**Fix**: Run PowerShell as Administrator, OR configure the task manually (see below).

---

## 6. Manual Task Scheduler Configuration

If the automated script fails, configure these steps manually to ensure the Digital Twin runs autonomously.

### 6.1 Auto-Start ActivityWatch
1. Open **Task Scheduler** (`taskschd.msc`).
2. **Create Basic Task**:
   - **Name**: `StartActivityWatch`
   - **Trigger**: "When I log on"
   - **Action**: "Start a program" -> Browse to `C:\...\my-local-llm\bin\activitywatch\aw-qt.exe`
   - **Conditions**: Uncheck "Start the task only if the computer is on AC power" (optional).
   - **Settings**: Check "Run task as soon as possible after a scheduled start is missed".

### 6.2 Nightly Batch (The Brain)
To generate daily summaries automatically and manage power:

1. **Create Basic Task**:
   - **Name**: `DigitalTwinNightlyBatch`
   - **Trigger**: Daily at 02:00 AM (recommended time when you are asleep).
   - **Action**: "Start a program"
     - **Program/script**: `powershell.exe`
     - **Add arguments**: `-ExecutionPolicy Bypass -File "C:\...\my-local-llm\run_nightly_batch.ps1"`
     - **Start in**: `C:\...\my-local-llm\`
2. **Configure Wake-Up & Sleep**:
   - Right-click the task -> **Properties**.
   - **Conditions** Tab:
     - [x] **Wake the computer to run this task** (CRITICAL).
   - **Settings** Tab:
     - [x] Run task as soon as possible after a scheduled start is missed.

**Note**: The script is now configured to **automatically start Docker Desktop** if it is not running, and **put the PC to sleep** after the job finishes.
- To test *without* sleeping, verify via terminal: `.\run_nightly_batch.ps1 -NoSleep`
