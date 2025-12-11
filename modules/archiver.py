import os
import glob
import datetime
import yaml
import logging
from pathlib import Path
from typing import List, Dict, Optional

import ollama

# --- Configuration ---
BASE_DIR = Path("/app")
DATA_DIR = BASE_DIR / "data"
JOURNALS_DIR = Path(os.environ.get("OBSIDIAN_MOUNT_PATH", DATA_DIR / "journals"))
CONFIG_PATH = BASE_DIR / "config" / "secrets.yaml"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConfigLoader:
    def __init__(self):
        self.config = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
        
        self.host = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
        self.model = self.config.get("ollama_model", "llama3")

cfg = ConfigLoader()
client = ollama.Client(host=cfg.host)

PROMPT_WEEKLY = """
Here are my daily summaries for the past week ({start_date} to {end_date}).
Synthesize them into a high-level Weekly Review.
Highlight:
1. Key Achievements
2. Recurring Themes
3. Areas for Improvement

Summaries:
{summaries}
"""

def get_daily_notes() -> List[Path]:
    return sorted(list(JOURNALS_DIR.glob("*_daily.md")))

def parse_frontmatter(content: str) -> Dict:
    if content.startswith("---"):
        try:
            _, fm, _ = content.split("---", 2)
            return yaml.safe_load(fm) or {}
        except ValueError:
            pass
    return {}

def create_weekly_summary():
    dailies = get_daily_notes()
    if not dailies:
        logger.info("No daily notes found.")
        return

    # Naive Logic: Group by ISO Week? Or Rolling 7 days?
    # Let's go with ISO Week for structure
    # Group dailies by Week Number
    weeks = {}
    for note in dailies:
        with open(note, 'r', encoding='utf-8') as f:
            content = f.read()
            fm = parse_frontmatter(content)
            date_str = fm.get('date')
            if not date_str:
                continue
            
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%W") # e.g., 2024-W45
            
            if week_key not in weeks:
                weeks[week_key] = []
            weeks[week_key].append({"path": note, "content": content, "date": date_str})

    # Process each week
    for week_key, notes in weeks.items():
        if len(notes) < 3:
            logger.info(f"Week {week_key} has only {len(notes)} entries. Skipping rollup.")
            continue
            
        week_file = JOURNALS_DIR / f"{week_key}_weekly.md"
        if week_file.exists():
            logger.info(f"Week {week_key} already summarized.")
            continue
            
        logger.info(f"Summarizing Week {week_key} ({len(notes)} days)...")
        
        combined_text = "\n\n".join([f"## {n['date']}\n{n['content']}" for n in notes])
        
        try:
            response = client.chat(model=cfg.model, messages=[
                {"role": "system", "content": "You are a personal assistant creating a weekly executive summary."},
                {"role": "user", "content": PROMPT_WEEKLY.format(
                    start_date=notes[0]['date'],
                    end_date=notes[-1]['date'],
                    summaries=combined_text
                )}
            ])
            
            narrative = response['message']['content']
            
            # Save Weekly Note
            content = f"""---
week: {week_key}
tags: [weekly, digital_twin]
start_date: {notes[0]['date']}
end_date: {notes[-1]['date']}
children: {[n['date'] for n in notes]}
---
# Weekly Review: {week_key}

{narrative}
"""
            with open(week_file, "w", encoding="utf-8") as f:
                f.write(content)
                
            logger.info(f"Created {week_file}")
            
        except Exception as e:
            logger.error(f"Weekly summarization failed: {e}")

if __name__ == "__main__":
    create_weekly_summary()
