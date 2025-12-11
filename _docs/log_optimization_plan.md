# Log Optimization Strategy: Event Fusion & Sessionization

## 1. Current State vs. Optimal State

| Feature | Current State (Raw Logs) | Optimal State (Fused & Sessionized) |
| :--- | :--- | :--- |
| **Structure** | Two separate lists: `browser_history` and `window_activity`. | Single chronological `timeline`. |
| **Context** | Window Log has Duration but no URL. Browser Log has URL but no Duration. | **Fused Event**: App + Title + URL + Duration. |
| **Granularity** | "Clicked file", "Clicked tab", "Clicked file". (Noisy) | **Session**: "Edited Python files for 20 mins". |
| **Token Cost** | PROHIBITIVE (High noise ratio). | EFFICIENT (High signal ratio). |

## 2. Technical Implementation

### A. Stream Fusion Logic
We will modify `sensor.py` to merge the two data streams.

**Algorithm:**
1.  Fetch `BrowserEvents` (Timestamp, URL, Title).
2.  Fetch `WindowEvents` (Start, Duration, App, Title).
3.  **Iterate** through `WindowEvents`:
    -   If App is a Browser (Chrome/Edge/Firefox), look for a `BrowserEvent` where:
        -   `Browser.Timestamp` is near `Window.Start` (approx matching).
        -   `Browser.Title` fuzzy matches `Window.Title`.
    -   **Merge**: Create an `ActivityEvent` with `URL` embedded.
4.  **Result**: A single stream where "Browsing" events have specific URLs attached.

### B. Sessionization (The "Smart" Layer)
Instead of saving every second of data, we group "micro-events" into "macro-activities".

**Rule**:
-   IF `CurrentEvent.App` == `LastEvent.App` AND `Gap` < 2 minutes:
    -   **Merge** into current Session.
    -   Accumulate `Duration`.
    -   Add `Title/URL` to a frequency map or list of "Topics".
-   ELSE:
    -   Start new Session.

**Output Example (JSON)**:
```json
[
  {
    "type": "session",
    "start": "10:00",
    "end": "10:45",
    "app": "VS Code",
    "duration_min": 45,
    "topics": ["sensor.py", "debug.log"],
    "summary": "Coding in my-local-llm"
  },
  {
    "type": "session",
    "start": "10:45",
    "end": "11:00",
    "app": "Firefox",
    "duration_min": 15,
    "main_url": "stackoverflow.com",
    "page_titles": ["Python merge dict", "Pandas join"]
  }
]
```

## 3. Implementation Plan

#### [MODIFY] [sensor.py](file:///C:/Users/yamadarikuto/Mycode/my-local-llm/modules/sensor.py)
-   Add `fuzz` (fuzzy matching) dependency? -> *Better to use simple substring or strict match first to avoid deps.*
-   Implement `fuse_streams(browser_logs, window_logs)`.
-   Implement `sessionize_events(fused_logs)`.
-   Update `main` to save the `sessionized_log` instead of raw.

## 4. User Impact
-   **Privacy**: URLs are bundled into sessions; easier to spot/redact blocks.
-   **AI Quality**: LLM receives a "Story" instead of "Data Points". Summaries will be much sharper.
