import os
import glob
import datetime
import yaml
import logging
from pathlib import Path
from typing import List, Dict, Optional

import ollama

# Import MemoryManager for RAG
try:
    from memory import MemoryManager
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from memory import MemoryManager


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

# --- New Configuration for Samples ---
SAMPLES_DIR = DATA_DIR / "samples"

PROMPT_WEEKLY = """
You are a personal project manager analyzing the past week's logs ({start_date} to {end_date}).
Create a factual weekly summary. Do NOT invent metrics or mix up projects.

**Analysis Framework**:
1. **Key Achievements**: What was actually finished? (Cite filenames/commits if possible)
2. **Project Updates**:
   - Separate "Antigravity" work from "University/Assignments" (e.g., Raspberry Pi tasks).
   - List specific progress for each.
3. **Learnings**: Technical or process definitions learned.
4. **Blockers**: What went wrong?

**Required Output Structure in Japanese**:

## 📊 週次データ
- **主要な取り組み**: [リスト]
- **完了タスク**: [リスト]

## 🛠 プロジェクト別進捗
### [Project A]
- [進捗]
- [課題]

### [Project B]
- [進捗]

**注意**:
- Antigravity(Local LLM) と Raspberry Pi(課題) は混同しないこと。
- 正確なログのみに基づき、推測で数値を書かないこと。

## 💡 今週の学び (Learnings)
- [Context] -> [Knowledge]

## 📝 来週のアクション
- [ログから導かれる次のタスク]

**CORRECT EXAMPLE**:
{examples}

Daily Summaries:
{summaries}

[参考情報：過去の経緯]
{rag_context}
"""

def load_examples(type_name: str) -> str:
    """Load example markdown files to guide the LLM."""
    example_path = SAMPLES_DIR / f"sample_{type_name}.md"
    if example_path.exists():
        try:
            with open(example_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to load sample {example_path}: {e}")
    return "(No examples available)"

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
            
            # YAML loader might auto-parse ISO dates into datetime.date objects
            if isinstance(date_str, (datetime.date, datetime.datetime)):
                date_str = date_str.strftime("%Y-%m-%d")

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
        
        # RAG: Time-Offset Retrieval
        # Query for insights explicitly BEFORE this week started
        rag_context = ""
        try:
            # 1. Determine Week Start Timestamp
            start_date_str = notes[0]['date']
            start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
            start_ts = start_dt.timestamp()
            
            # 2. Extract Keywords (Simple Frequency or Main Focus)
            # For now, use a generic query related to growth/challenges
            query_text = f"challenges learned achievements skills"
            
            memory = MemoryManager()
            # 3. Query with Filter: timestamp < start_ts
            past_insights = memory.query(
                query_text, 
                n_results=3, 
                where={"timestamp": {"$lt": start_ts}}
            )
            
            if past_insights:
                rag_context = ""
                for idx, insight in enumerate(past_insights, 1):
                    date = insight['metadata'].get('date', 'Unknown')
                    content = insight['content']
                    rag_context += f"- ({date}): {content}\n"
                logger.info(f"Found {len(past_insights)} historical insights (before {start_date_str})")
        except Exception as e:
            logger.warning(f"Time-Offset RAG failed: {e}")
        
        try:
            response = client.chat(model=cfg.model, messages=[
                {"role": "system", "content": "You are a personal assistant creating a weekly executive summary."},
                {"role": "user", "content": PROMPT_WEEKLY.format(
                    start_date=notes[0]['date'],
                    end_date=notes[-1]['date'],
                    summaries=combined_text,
                    rag_context=rag_context,
                    examples=load_examples("weekly")
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
