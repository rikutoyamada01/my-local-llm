# Future Optimization Plan: WSL2 Sync-then-Train Architecture

**Status**: Planned / Ready for Implementation
**Target**: Optimization of LLM Fine-tuning Pipeline
**Reference**: `_docs/qiita_draft_20251211.md`, `modules/trainer.py`

## 1. Problem Statement
Currently, the Docker-based training pipeline uses **Bind Mounts** to access data stored on the Windows host (`NTFS`).
- **Issue**: Cross-OS file I/O (NTFS <-> Linux Kernel) via Docker Desktop is significantly slower than native FS access.
- **Impact**: Training small models with massive datasets (many small text files) results in low GPU utilization because the data loader waits for I/O.

## 2. Proposed Architecture: "Sync-then-Train"

To bypass the I/O bottleneck, we propose a "Selectable Mode" that utilizes WSL2's native `ext4` file system.

### Workflow
1.  **Sync (Windows -> WSL2)**
    -   Use `wsl.exe` + `rsync` (or `robocopy`) to mirror the `data/journals` directory from the Windows host to a dedicated directory inside the default WSL2 distribution (e.g., `~/digital_twin_data`).
2.  **Train (WSL2 Native)**
    -   execute the training script (`trainer.py`) directly inside WSL2 using the native Python environment (or a native Docker container inside WSL2), accessing the data on `ext4`.
3.  **Sync Back (WSL2 -> Windows)**
    -   Copy only the resulting Adapter files (`.safetensors`, `adapter_config.json`) back to the Windows host for use by the inference engine (`Ollama`).

## 3. Cost/Benefit Analysis

| Metric | Docker Mount (Current) | WSL2 Native (Target) | Improvement |
| :--- | :--- | :--- | :--- |
| **I/O Speed** | ~50-100 MB/s | >1000 MB/s (Native) | **10x - 20x** |
| **Training Time** | Baseline | -20% to -30% | Faster Iteration |
| **Complexity** | Low (Single `docker-compose`) | Medium (Requires Sync Scripts) | - |
| **Disk Usage** | 1x | 2x (Data Duplication) | - |

## 4. Implementation Specifications

### A. Configuration (`config/settings.yaml`)
Introduce a new config file to manage the mode.
```yaml
training:
  mode: "wsl_sync" # or "standard"
  wsl_distro: "Ubuntu-24.04"
  wsl_path: "~/digital_twin_data"
```

### B. Management Script (`scripts/manage_training.ps1`)
A PowerShell script to orchestrate the process:
- **`Switch-Mode`**: Updates `settings.yaml`.
- **`Sync-Data`**: Performs the copy to WSL.
- **`Run-Training`**: Wraps the `wsl.exe` command execution.

### C. Automation (`run_nightly_batch.ps1`)
Update the nightly batch to check `mode`.
- If `mode == "wsl_sync"`:
    1. Exec Sync.
    2. Exec Training via `wsl.exe`.
    3. Exec Sync Back.
- Else:
    1. Exec standard `docker compose run`.

## 5. Migration Steps (Future)
1.  Create `config/settings.yaml` and load it in `run_nightly_batch.ps1`.
2.  Develop `scripts/manage_training.ps1` to handle `rsync` logic.
3.  Verify permissions and path mapping between Windows and WSL2.
4.  Switch mode and verify speed improvements.
