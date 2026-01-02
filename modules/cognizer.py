import os
import sys
import json
import datetime
import glob
import logging
import math
from pathlib import Path
from typing import List, Dict, Any, Optional

import ollama
import yaml
import tiktoken

# --- Configuration ---
BASE_DIR = Path("/app")
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
JOURNALS_DIR = Path(os.environ.get("OBSIDIAN_MOUNT_PATH", DATA_DIR / "journals"))
CONFIG_PATH = BASE_DIR / "config" / "secrets.yaml"

# Ensure output directories
JOURNALS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConfigLoader:
    def __init__(self):
        self.config = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
        
        self.host = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
        self.model = self.config.get("ollama_model", "llama3")
        self.context_limit = int(self.config.get("context_limit", 8192))

cfg = ConfigLoader()
client = ollama.Client(host=cfg.host)

# --- Prompts ---
PROMPT_SYSTEM = """
You are a highly intelligent Digital Twin assistant.
Your goal is to summarize the user's daily activity into a Structured Daily Journal.
Use **First-Person** voice ("I...") for all qualitative sections.

IMPORTANT: Even for short or sparse logs, you MUST generate a summary. Do not return empty fields.
**CRITICAL**: Be specific. Do not just say "I worked on code" or "Processed files".
If the log shows file usage (e.g., window titles like `cognizer.py`, `README.md`), you MUST explicitly say "I edited `cognizer.py`" or "I updated `README.md`".
Identify the **project name** from the window titles (e.g., "Antigravity", "my-local-llm") and mention it.
**Include specific filenames, URLs, project names, and error messages** where visible in the logs.

**GUIDELINES FOR 'LEARNINGS'**:
- **AVOID** generic software engineering platitudes (e.g., "I learned that testing is important", "Optimization is key"). These are low value.
- **FOCUS** on specific topics found in window titles or URLs.
- *Example*: Instead of "I learned about Python error handling", say "I investigated `ValueError` in `json.load` and learned how to handle malformed UTF-8."
- *Example*: Instead of "I researched databases", say "I researched `PostgreSQL` indexing specifically for `JSONB` columns using the official docs."
- Infer the "Why": If multiple window titles show "Error 500" followed by "overflow.com/questions/...", assume I was debugging that specific error.
- If no deep insight is visible, straightforwardly state the specific technical topics researched.

Output Format:
You must provide the response in valid JSON format with the following keys:
1. "summary": A short paragraph (2-3 sentences) summarizing the day in First-Person.
2. "activities": A nested object with keys "morning", "afternoon", "evening". Each contains a list of strings (activities) in First-Person.
3. "learnings": A list of specific technical insights or topics researched (strings) in First-Person.
4. "productivity_score": An integer (1-10) based on the volume and complexity of work.
5. "main_focus": A short string describing the primary focus (e.g., "Coding", "Research").
6. "facts": A list of short, independent strings representing key facts/topics for a Vector DB.

Example:
{
  "summary": "Today I focused heavily on...",
  "activities": {
    "morning": ["Refactored the API module", "Reviewed PRs"],
    "afternoon": ["Debugged the Login flow"],
    "evening": ["Read about Graph Databases"]
  },
  "learnings": ["I learned that...", "The Orchestrator pattern is useful for..."],
  "productivity_score": 8,
  "main_focus": "Backend Dev",
  "facts": ["Impl: Auth Module", "Fixed: Login Bug"]
}
"""

PROMPT_MAP_REDUCE = """
The following logs are a partial segment of my day. Summarize them into detailed bullet points.
**CRITICAL**: You must PRESERVE specific filenames (e.g., `cognizer.py`), project names, error messages, and URL topics.
Do not generalize these into "files" or "debugging".
Logs:
{logs}
"""

PROMPT_FINAL = """
Here are the activity logs for {date}. 
Activity Timeline:
{timeline_summary}

Synthesize these into the Structured Daily Journal JSON format.
Focus on **specific details**: what files were touched? what specific topics were researched?
Avoid generic phrases like "various components" or "general research".
"""

# --- Logic ---

def count_tokens(text: str) -> int:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback approximation (4 chars ~= 1 token)
        return len(text) // 4

def summarize_segment(segment_text: str) -> str:
    """Map step: Summarize a chunk of logs."""
    try:
        response = client.chat(model=cfg.model, messages=[
            {"role": "system", "content": "Summarize these logs into detailed bullet points, strictly preserving filenames, project names, and technical terms."},
            {"role": "user", "content": PROMPT_MAP_REDUCE.format(logs=segment_text)}
        ])
        return response['message']['content']
    except Exception as e:
        logger.error(f"Ollama Map Error: {e}")
        return "Error summarizing segment."

def format_timeline(timeline: List[Dict]) -> str:
    """Converts the session list into a readable text format for the LLM."""
    lines = []
    for s in timeline:
        start = s.get("start_time", "").split("T")[-1][:5] # HH:MM
        end = s.get("end_time", "").split("T")[-1][:5]
        app = s.get("app", "Unknown")
        duration = int(s.get("duration", 0) / 60) # Minutes
        
        # Details
        titles = list(set(s.get("titles", []))) # Unique
        urls = list(set(s.get("urls", [])))
        
        # Truncate lists if too long (Increased limit to capture more detail)
        if len(titles) > 30: titles = titles[:30] + ["..."]
        if len(urls) > 30: urls = urls[:30] + ["..."]
        
        line = f"[{start}-{end}] {app} ({duration}m): {', '.join(titles)}"
        if urls:
            line += f"\\n  - URLs: {', '.join(urls)}"
        lines.append(line)
    return "\\n".join(lines)

def process_logs(log_file: Path):
    logger.info(f"Processing {log_file}...")
    
    with open(log_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    date_str = data.get("date", str(datetime.date.today()))
    
    # Handle New Format vs Old Format
    if "timeline" in data:
        full_input = format_timeline(data["timeline"])
    else:
        # Legacy fallback
        browser = json.dumps(data.get("browser_history", []), indent=2)
        windows = json.dumps(data.get("window_activity", []), indent=2)
        full_input = f"Browser:\\n{browser}\\n\\nWindows:\\n{windows}"
        
    token_count = count_tokens(full_input)
    logger.info(f"Input Token Count: {token_count}")
    
    final_context = ""
    
    # --- Strategy: Map-Reduce vs Direct ---
    if token_count < (cfg.context_limit - 1000):
        # Direct
        final_context = full_input
    else:
        # Map-Reduce
        logger.info("Tokens exceed limit. Triggering Map-Reduce...")
        chunk_size = 12000 # Increased chunk size for text format
        chunks = [full_input[i:i+chunk_size] for i in range(0, len(full_input), chunk_size)]
        
        micro_summaries = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Mapping chunk {i+1}/{len(chunks)}...")
            summary = summarize_segment(chunk)
            micro_summaries.append(summary)
            
        final_context = "\\n".join(micro_summaries)
        
    # --- Reduce / Generate Final ---
    try:
        response = client.chat(model=cfg.model, format='json', messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": PROMPT_FINAL.format(date=date_str, timeline_summary=final_context)}
        ])
        
        content = response['message']['content']
        # logger.info(f"Ollama Raw Response: {content[:500]}...") # Log first 500 chars

        result_json = json.loads(content)
        logger.info(f"JSON Keys Received: {list(result_json.keys())}") # DIAGNOSTIC LOG
        
        # Save Outputs
        save_journal(date_str, result_json)
        
        # Mark log as processed (rename)
        new_name = log_file.with_suffix('.json.processed')
        log_file.rename(new_name)
        logger.info(f"Finished processing {log_file}")
        
    except Exception as e:
        logger.error(f"Final Generation Error: {e}")

def save_journal(date_str: str, data: Dict):
    # 1. Narrative (Markdown)
    safe_date = date_str.split("T")[0]
    md_path = JOURNALS_DIR / f"{safe_date}_daily.md"
    
    # Extract Data
    summary = data.get('summary', 'No summary generated.')
    activities = data.get('activities', {})
    learnings = data.get('learnings', [])
    prod_score = data.get('productivity_score', 5)
    main_focus = data.get('main_focus', 'General')
    facts = data.get('facts', [])
    
    morning = activities.get('morning', [])
    afternoon = activities.get('afternoon', [])
    evening = activities.get('evening', [])
    
    # Helper to format lists
    def fmt_list(items):
        return "\n".join([f"- {item}" for item in items]) if items else "- No major activities recorded."

    frontmatter = f"""---
date: {safe_date}
tags: [daily, digital_twin]
productivity_score: {prod_score}
main_focus: {main_focus}
facts: {json.dumps(facts)}
---
"""
    content = f"""{frontmatter}
# Daily Log: {safe_date}

> [!SUMMARY] Daily Summary
> {summary}

## Activity Log
### Morning
{fmt_list(morning)}

### Afternoon
{fmt_list(afternoon)}

### Evening
{fmt_list(evening)}

> [!NOTE] Learnings & Insights
{fmt_list(learnings)}
"""
    
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Saved Journal: {md_path}")

def main():
    logger.info("Cognizer started.")
    
    # Process specific file from args
    if len(sys.argv) > 1:
        log_path = Path(sys.argv[1])
        if log_path.exists():
            process_logs(log_path)
            return
        else:
            logger.error(f"File not found: {log_path}")
            return

    # Find unprocessed logs
    logs = glob.glob(str(LOGS_DIR / "sensor_log_*.json"))
    
    if not logs:
        logger.info("No new logs to process.")
        return

    for log in logs:
        process_logs(Path(log))

if __name__ == "__main__":
    main()
