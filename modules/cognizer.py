import os
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
Your goal is to summarize the user's daily activity into a coherent First-Person Narrative.
You must also extract structured facts for a vector database.

Output Format:
You must provide the response in valid JSON format with two keys:
1. "narrative": A standard markdown string (3-5 paragraphs) describing the day in first person ("I did...").
2. "facts": A list of short, independent strings representing key facts/topics (e.g., "Worked on Project X", "Fixed bug in API").

Example:
{
  "narrative": "Today I focused on...",
  "facts": ["Impl: Auth Module", "Fixed: Login Bug"]
}
"""

PROMPT_MAP_REDUCE = """
The following logs are a partial segment of my day. Summarize them briefly into bullet points.
Logs:
{logs}
"""

PROMPT_FINAL = """
Here are the activity logs for {date}. 
Browser History:
{browser_summary}

Window Activity:
{window_summary}

Synthesize these into a meaningful Daily Journal.
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
            {"role": "system", "content": "Summarize these logs into concise bullet points."},
            {"role": "user", "content": PROMPT_MAP_REDUCE.format(logs=segment_text)}
        ])
        return response['message']['content']
    except Exception as e:
        logger.error(f"Ollama Map Error: {e}")
        return "Error summarizing segment."

def process_logs(log_file: Path):
    logger.info(f"Processing {log_file}...")
    
    with open(log_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    date_str = data.get("date", str(datetime.date.today()))
    browser = json.dumps(data.get("browser_history", []), indent=2)
    windows = json.dumps(data.get("window_activity", []), indent=2)
    
    full_input = f"Browser:\n{browser}\n\nWindows:\n{windows}"
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
        chunk_size = 6000 # Safety buffer
        chunks = [full_input[i:i+chunk_size] for i in range(0, len(full_input), chunk_size)]
        
        micro_summaries = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Mapping chunk {i+1}/{len(chunks)}...")
            summary = summarize_segment(chunk)
            micro_summaries.append(summary)
            
        final_context = "\n".join(micro_summaries)
        
    # --- Reduce / Generate Final ---
    try:
        response = client.chat(model=cfg.model, format='json', messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": PROMPT_FINAL.format(date=date_str, browser_summary=final_context, window_summary="")}
        ])
        
        result_json = json.loads(response['message']['content'])
        
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
    
    frontmatter = f"""---
date: {safe_date}
tags: [daily, digital_twin]
facts: {json.dumps(data.get('facts', []))}
---
"""
    content = f"{frontmatter}\n# Daily Log: {safe_date}\n\n{data.get('narrative', '')}"
    
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Saved Journal: {md_path}")

def main():
    logger.info("Cognizer started.")
    # Find unprocessed logs
    logs = glob.glob(str(LOGS_DIR / "sensor_log_*.json"))
    
    if not logs:
        logger.info("No new logs to process.")
        return

    for log in logs:
        process_logs(Path(log))

if __name__ == "__main__":
    main()
