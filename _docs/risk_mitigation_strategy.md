# Risk Mitigation Strategy: Local Digital Twin Project

This document outlines the technical strategies to address critical risks identified in the initial implementation plan. These strategies will be incorporated into the core `implementation_plan.md`.

## 1. Hybrid Environment I/O (Windows vs WSL2)
**Risk**: Direct access from WSL2 to Windows files (`/mnt/c/...`) suffers from severe I/O performance penalties, potentially slowing down training (Unsloth) and daily processing.
**Strategy**: **"Sync-then-Train" Architecture**
- **Data Staging**: All raw logs and generated summaries reside on the **Windows** file system (`C:\Users\...\DigitalTwin\data`) for ease of access by the user and Obsidian.
- **Synchronization**: The nightly batch script (`run_nightly_batch.ps1`) will include a synchronization step.
    - Before Unsloth training triggers, the script copies the necessary JSONL training datasets from Windows to the WSL2 native file system (`~/digital_twin_training/`).
    - Training runs entirely within the fast WSL2 native FS.
    - Model artifacts (LoRA adapters) are copied back to Windows for inference by Ollama.

## 2. Browser History File Locking (SQLite)
**Risk**: `sqlite3.OperationalError: database is locked` occurs if the browser is writing to the History file exactly when the script tries to copy it.
**Strategy**: **"Robust Shadow Copy" with Fallback**
- **Retry Logic**: Implement `tenacity` retry decorator on the file copy operation (up to 3 retries with exponential backoff).
- **Fallback Mechanism**: If the History file is inaccessible after retries (rare but possible), the system will **fallback** to using only `ActivityWatch` data (aw-watcher-web).
    - *Note*: AW data lacks full historical context compared to browser history but is sufficient for defining "what happened".
    - A warning log will be generated, but the pipeline will not crash.

## 3. LLM Context Window Overflow
**Risk**: A simple concatenation of 7 days of summaries might exceed the context window (8k-128k depending on model), causing crashes or truncation of recent events.
**Strategy**: **"Smart Token Budgeting" (Cognizer)**
- **Token Counting**: Use `tiktoken` or similar customized tokenizer to count tokens before prompt construction.
- **Adaptive Execution**:
    - **Scenario A (Within Limit)**: Standard concatenation (Fast, coherent).
    - **Scenario B (Exceeds Limit)**: **Map-Reduce**.
        1. **Map**: Summarize each Daily Summary individually into a structured "Micro-Summary".
        2. **Reduce**: Combine Micro-Summaries into the Weekly structure.
- **Strict Limit**: Enforce a hard output limit for Daily Summaries (e.g., max 2000 tokens) in the prompt instructions to prevent upstream ballooning.

## 4. Deployment Complexity (ActivityWatch)
**Risk**: Manual installation of ActivityWatch is prone to path errors and user fatigue.
**Strategy**: **"PowerShell Automation"**
- Create `install_dependencies.ps1` that:
    1. Downloads the correct `aw-server-rust` and watchers binaries.
    2. Extracts them to a defined `bin` directory within the project.
    3. Sets up a Windows Scheduled Task to launch them on login automatically.
    4. Verifies the `localhost:5600` API endpoint is up.

## 5. Model Hallucination in RAG
**Risk**: RAG might retrieve irrelevant old facts and present them as current.
**Strategy**: **"Time-Weighted Re-ranking"**
- In `memory.py`, after vector retrieval, apply a re-ranking score that boosts documents closer to the query's implied date (if any) or the current date.
- Use explicit visual cues in UI (e.g., "Source: 2024-01-05") to alert the user of the information's age.
