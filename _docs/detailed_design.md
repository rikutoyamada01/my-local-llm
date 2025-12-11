# Local Digital Twin - Detailed Design Document

**Version**: 1.0
**Status**: Draft
**Reference**: `README.md`, `_docs/risk_mitigation_strategy.md`

This document details the logical design for the Local Digital Twin project. It is structured into chapters representing the data flow stages.

---

## Chapter 1: Perception Layer (Data Collection)

**Objective**: Robustly capture user activity logs and browser history without interrupting the user or crashing due to file locks.  
**Execution Context**: **Host Machine (Windows Native)**.  
*Reason: Direct access to file locks (Edge/Chrome History) and Window Handles (ActivityWatch watchers) is most reliable on the host OS.*

### 1.1 Core Components
- **Module**: `modules/sensor.py`
- **External Dependencies**: ActivityWatch (`aw-server`, `aw-watcher-window`, `aw-watcher-afk`), Web Browsers (Chrome/Edge).

### 1.2 Logic & Workflow

#### A. ActivityWatch Integration
The system queries the `aw-server` API (`localhost:5600`) to retrieve "Canonical Events".

#### B. Robust Browser History Extraction (Risk Mitigation #2)
- **Strategy**: **Shadow Copy with Retry**
    1.  **Attempt Copy**: Copy `History` file to a temp directory.
    2.  **Retry**: Exponential backoff using `tenacity`.
    3.  **Fallback**: Use ActivityWatch window titles if copy fails.

#### C. Privacy Filtering
- **Mechanism**: Regex-based text processing.
- **Rules**: PII stripping and Domain Blacklist.

---

## Chapter 2: Cognition Layer (Daily Summaries)

**Objective**: Compress raw logs into structured narratives.  
**Execution Context**: **Docker Container (`digital-twin-core`)**.

### 2.1 Core Components
- **Module**: `modules/cognizer.py`
- **Model**: Ollama (Accessible via `host.docker.internal` or local container network).

### 2.2 Logic & Workflow

#### A. Smart Token Budgeting
- **Token Counting**: Calculate tokens of input logs.
- **Map-Reduce Strategy**: Split and summarize chunks if input > context limit.

#### B. Structured Output
Generates Markdown (Narrative) and JSON (Semantic Facts).

---

## Chapter 3: Memory Layer (Storage & Retrieval)

**Objective**: Store summaries for recall.  
**Execution Context**: **Docker Container (`digital-twin-core`)**.

### 3.1 Core Components
- **Modules**: `modules/archiver.py`, `modules/memory.py`
- **Storage**: 
    -   **Obsidian**: User's existing Vault (Mounted Volume).
    -   **ChromaDB**: Containerized Vector Store.

### 3.2 Logic & Workflow

#### A. Existing Obsidian Vault Integration
- **Config**: User provides absolute path to their existing Obsidian Vault in `secrets.yaml`.
- **Output**: System writes to a dedicated subfolder (e.g., `MyVault/DigitalTwin_Journals/`).
- **Linking**: Updates Frontmatter to link Daily notes to Weekly notes.

#### B. Time-Weighted RAG
- **Vector Search**: Query ChromaDB.
- **Re-Ranking**: Boost results based on recency.

---

## Chapter 4: Persona Layer (Continuous Learning)

**Objective**: Fine-tune LLM.  
**Execution Context**: **Docker Container (`digital-twin-trainer`)** with GPU Support.

### 4.1 Core Components
- **Module**: `modules/trainer.py`
- **Framework**: Unsloth (QLoRA)

### 4.2 Logic & Workflow

#### A. Containerized Training
- **Volume Mount**: The training data folder is shared between the `core` container and `trainer` container.
- **GPU Pass-through**: Uses NVIDIA Container Toolkit to access host GPU from Docker.

#### B. Replay Buffer
- **Data Mix**: 80% New Data, 20% Replay Data.

---

## Chapter 5: Automation & Orchestration

**Objective**: "Set and Forget" operation ensuring the pipeline runs every night.

### 5.1 Core Components
- **Script**: `run_nightly_batch.ps1` (Host Orchestrator)
- **Docker Compose**: `docker-compose.yml`

### 5.2 Workflow Sequence
1.  **Wake/Start**: Triggered at 3:00 AM.
2.  **Sensor Phase (Host)**: Run `sensor.py` natively to grab locked files and AW data. Saves JSON to shared `data/` folder.
3.  **Cognition Phase (Docker)**:
    -   `docker compose run core python cognizer.py`
    -   Reads JSON from mount, calls Ollama, writes Markdown/VectorDB.
4.  **Training Phase (Docker - Conditional)**:
    -   If `Pending_Data > Threshold`: `docker compose run --gpus all trainer python trainer.py`.
5.  **Completion**: Log success/failure.
