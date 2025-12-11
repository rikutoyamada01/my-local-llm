# Implementation Plan: Local Digital Twin Project

**Goal**: Build a self-hosted, privacy-first Digital Twin agent on Windows 11 that learns from user logs (ActivityWatch) to mimic the user's personality and recall context, utilizing a Hierarchical Summarization architecture and Replay Buffer to prevent catastrophic forgetting.

## User Review Required

> [!IMPORTANT]
> **Hardware Requirements**: This plan assumes the availability of an NVIDIA GPU (RTX 3060 or better recommended) for local LLM inference (Ollama) and Fine-Tuning (Unsloth).
> **WSL2 Dependence**: Advanced training features (Unsloth) rely on Linux/WSL2. The system employs a **Sync-then-Train** architecture to mitigate cross-OS I/O performance issues.

## Architecture Overview

Based on Research 001 & 002, the system consists of 4 core layers connected by a "Daily Summary" hub.

| Layer | Function | Tech Stack |
| :--- | :--- | :--- |
| **1. Perception** | Collect raw activity logs & browser history. | `ActivityWatch`, `Python` (Robust Shadow Copy) |
| **2. Cognition** | Compress raw logs into structured Daily/Weekly summaries. | `Ollama`, `LangChain` (Smart Token Budgeting) |
| **3. Memory** | Store structured facts (RAG) & narratives (Obsidian). | `Obsidian` (Markdown), `ChromaDB` (Vector) |
| **4. Persona** | Continual learning of user's voice/thinking style. | `Unsloth` (QLoRA), `Replay Buffer` (WSL2) |

---

## Proposed Changes (Phased Implementation)

### Phase 1: Data Collection & Environment Setup (Perception Layer)
**Objective**: Establish the bedrock of data collection with robust error handling and automated setup.

#### [NEW] `scripts/install_dependencies.ps1`
- Automates download and configuration of ActivityWatch (Rust server + Watchers).
- Sets up autostart tasks.

#### [NEW] `modules/sensor.py`
- Wrapper for `aw-client` to fetch "Canonical Events".
- **Robust Shadow Copy**: Implements specific retry logic (`tenacity`) for copying locked Chrome/Edge history files.
- **Fallback Mode**: Gracefully degrades to use only ActivityWatch data if browser history is inaccessible.
- **Privacy Filter**: RegEx-based sanitizer for emails, credit cards, and blacklist for private domains.

#### [NEW] `config/secrets.yaml`
- Define sensitive keywords, exclusion rules, and browser profile paths.

### Phase 2: Cognition Pipeline (Daily Summary)
**Objective**: Convert voluminous raw logs into meaningful "Daily Summaries" using Local LLM context-aware processing.

#### [NEW] `modules/cognizer.py`
- **Smart Token Budgeting**: dynamically calculates token counts. Uses Map-Reduce strategy for summarizing if logs exceed context window.
- **Dual-Structure Output**: Generates JSON (for RAG) and Markdown (for Narrative).
- Integration with `ollama` python library.

### Phase 3: Hierarchical Memory & Archiving (Memory Layer)
**Objective**: Implement the "Second Brain" structure (Daily -> Weekly -> Annual) compatible with Obsidian.

#### [NEW] `modules/archiver.py`
- **Hierarchical Summarization**: Script to aggregate 7 Daily Summaries into a Weekly Summary.
- **Obsidian Integration**: Auto-generate backlink structure (`parent`, `children` fields in Frontmatter).

#### [NEW] `data/templates/`
- Jinja2 templates (`daily.md.j2`, `weekly.md.j2`) for consistent creation of Obsidian notes.

### Phase 4: RAG Implementation (Recall Layer)
**Objective**: Enable "Time-Aware" retrieval of facts.

#### [NEW] `modules/memory.py`
- **ChromaDB Setup**: Persistent vector store initialization.
- **Time-Weighted Search**: Implementation of `query_with_time_filter` and re-ranking logic favouring query-relevant timeframes.

### Phase 5: Persona Training (Persona Layer)
**Objective**: Train the LLM to speak and think like the user using Continual Learning in a high-performance environment.

#### [NEW] `modules/trainer.py` (WSL2 side)
- **Sync-then-Train**: 
    1. Syncs training data from Windows (`/mnt/c/...`) to WSL2 native FS.
    2. Runs Unsloth QLoRA training on native FS for maximum throughput.
    3. Syncs resulting Adapters back to Windows.
- **Replay Buffer**: Logic to mix New Data + Replay Data (Surprise-Prioritized + Anchors).

### Phase 6: Automation & UI
**Objective**: "Set and Forget" operation.

#### [NEW] `run_nightly_batch.ps1`
- PowerShell orchestrator to run the full pipeline:
    1. `sensor.py` (Windows)
    2. `cognizer.py` (Windows/Ollama)
    3. `memory.py` (Windows/Chroma)
    4. `wsl python3 trainer.py` (WSL2 - with sync steps)

#### [NEW] `interface/streamlit_app.py`
- Chat UI with RAG context visualization and Persona-based responses.

---

## Verification Plan

### Automated Tests
- [ ] **I/O Resilience**: Simulate locked file scenario and verify `sensor.py` fallback behavior.
- [ ] **Context Stress Test**: Feed `cognizer.py` 20k tokens of logs and verify Map-Reduce logic triggers.
- [ ] **WSL Bridge**: Verify `run_nightly_batch.ps1` successfully triggers the Python script inside WSL2.

### Manual Verification
- [ ] **Obsidian Check**: Open the `data/journals` folder in Obsidian and verify the graph view and links work.
- [ ] **Personality Check**: After initial training, ask the model "What did I work on last week?" and verify the tone matches the narrative logs.
