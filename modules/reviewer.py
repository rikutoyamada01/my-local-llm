import os
import glob
import datetime
import yaml
import logging
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict

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

PROMPT_MONTHLY = """
Analyze the past month's weekly reviews ({month}: {start_date} to {end_date}).
Identify growth trajectories, trends, and actionable strategies for next month.

**Analysis Framework**:
1. **Fact-Based Progress**: What was *actually* completed? (Cite specific artifacts/commits)
2. **Skill Application**: Where were specific skills applied? (e.g., "Used Python for data analysis", NOT "Improved Python skills by 20%")
3. **Project Distinction**: clearly separate different projects (e.g., "University Assignment" vs "Antigravity"). Do NOT mix them.
4. **Bottlenecks**: Actual blockers encountered.

**Required Output Structure in Japanese**:

## 🎯 月次サマリー
- **主要活動**: [事実に基づく活動の要約]
- **実績**: [完了したタスク/成果物]

## 📊 プロジェクト別進捗
| プロジェクト | 今月の成果 |
|--------------|------------|
| [Project A] | [具体的な成果] |
| [Project B] | [具体的な成果] |

**注意**:
- "Antigravity" と "Raspberry Pi" (e.g., 課題) は別のプロジェクトとして扱うこと。
- ログに書かれていない目標（例：世界ランク⚪︎位）を捏造しないこと。
- 「20%向上」のような根拠のない数値を使わないこと。

## 💡 技術的・経験的知見 (Top 3)
1. **[知見]**: [具体的なコンテキスト] -> [学び]
2. [...]
3. [...]

## 🚀 来月のフォーカス
- [ログに基づく次のステップ]

## 🚀 来月のフォーカス
- [ログに基づく次のステップ]

**CORRECT EXAMPLE**:
{examples}

Weekly Summaries:
{summaries}
[参考情報：過去の経緯]
{rag_context}
"""

PROMPT_YEARLY = """
Create a yearly reflection for {year} based on the actual monthly reviews provided.
**CRITICAL**: Stick strictly to the FACTS in the summaries. Do NOT invent stories, metrics, or "transformation arcs" that are not supported by data.

**Analysis Framework**:
1. **Key Milestones**: What was actually shipped or completed?
2. **Skill Acquisition**: What specific technologies/tools were learned?
3. **Project Portfolio**: Summary of progress on key projects.

**Required Output Structure in Japanese**:

## 📖 Year in Review: {year}の実績

### Part 1: マイルストーン年表
[事実に基づく主要イベントのみ]
- **Q1**: [...]
- **Q2**: [...]
- **Q3**: [...]
- **Q4**: [...]

### Part 2: プロジェクト別成果
- **[Project Name]**:
  - [成果物]
  - [学んだ技術]

### Part 3: 技術的成長
- [習得したスキル]: [具体的な活用例]

### Part 4: 来年の展望
- [ログから読み取れる継続課題]

Monthly Reviews:
{summaries}
[参考情報：過去の経緯]
{rag_context}

**CORRECT EXAMPLE**:
{examples}
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

def parse_frontmatter(content: str) -> Dict:
    """Extract YAML frontmatter from markdown content."""
    if content.startswith("---"):
        try:
            _, fm, _ = content.split("---", 2)
            return yaml.safe_load(fm) or {}
        except ValueError:
            pass
    return {}

def get_weekly_summaries() -> List[Path]:
    """Get all weekly summary files."""
    return sorted(list(JOURNALS_DIR.glob("*_weekly.md")))

def get_monthly_reviews() -> List[Path]:
    """Get all monthly review files."""
    return sorted(list(JOURNALS_DIR.glob("*_monthly.md")))

def create_monthly_review():
    """Generate monthly reviews from weekly summaries."""
    logger.info("Starting monthly review generation...")
    
    weeklies = get_weekly_summaries()
    if not weeklies:
        logger.info("No weekly summaries found.")
        return
    
    # Group by month
    months = defaultdict(list)
    for weekly_file in weeklies:
        with open(weekly_file, 'r', encoding='utf-8') as f:
            content = f.read()
            fm = parse_frontmatter(content)
            start_date = fm.get('start_date')
            
            if not start_date:
                continue
            
            # Handle date objects
            if isinstance(start_date, (datetime.date, datetime.datetime)):
                start_date = start_date.strftime("%Y-%m-%d")
            
            dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            month_key = dt.strftime("%Y-%m")  # e.g., 2026-01
            
            months[month_key].append({
                "path": weekly_file,
                "content": content,
                "frontmatter": fm
            })
    
    # Process each month
    for month_key, weeklies in months.items():
        if len(weeklies) < 2:
            logger.info(f"Month {month_key} has only {len(weeklies)} weekly summaries. Skipping.")
            continue
        
        month_file = JOURNALS_DIR / f"{month_key}_monthly.md"
        if month_file.exists():
            logger.info(f"Monthly review for {month_key} already exists.")
            continue
        
        logger.info(f"Creating monthly review for {month_key} ({len(weeklies)} weeks)...")
        
        # Calculate average productivity
        prod_scores = []
        for w in weeklies:
            # Try to extract productivity from weekly content
            # This is a simplified approach; adjust based on actual weekly format
            pass
        
        # Combine weekly summaries
        combined_text = "\n\n".join([
            f"## Week {w['frontmatter'].get('week', 'Unknown')}\n{w['content']}"
            for w in weeklies
        ])
        
        # RAG: Time-Offset Retrieval (Monthly)
        rag_context = ""
        try:
            start_date_str = weeklies[0]['frontmatter'].get('start_date')
            start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
            start_ts = start_dt.timestamp()
            
            memory = MemoryManager()
            query_text = f"skills growth challenges achievements"
            past_insights = memory.query(
                query_text, 
                n_results=5, 
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
            logger.warning(f"Monthly Time-Offset RAG failed: {e}")
        
        start_date = weeklies[0]['frontmatter'].get('start_date')
        end_date = weeklies[-1]['frontmatter'].get('end_date')
        
        # Handle date objects
        if isinstance(start_date, (datetime.date, datetime.datetime)):
            start_date = start_date.strftime("%Y-%m-%d")
        if isinstance(end_date, (datetime.date, datetime.datetime)):
            end_date = end_date.strftime("%Y-%m-%d")
        
        try:
            response = client.chat(model=cfg.model, messages=[
                {"role": "system", "content": "You are a personal assistant creating insightful monthly reviews. Use first-person voice."},
                {"role": "user", "content": PROMPT_MONTHLY.format(
                    month=month_key,
                    start_date=start_date,
                    end_date=end_date,
                    summaries=combined_text,

                    rag_context=rag_context,
                    examples=load_examples("monthly")
                )}
            ])
            
            narrative = response['message']['content']
            
            # Save Monthly Review
            week_ids = [w['frontmatter'].get('week', '') for w in weeklies]
            content = f"""---
month: {month_key}
tags: [monthly, digital_twin, review]
start_date: {start_date}
end_date: {end_date}
weeks: {week_ids}
---
# Monthly Review: {month_key}

{narrative}
"""
            with open(month_file, "w", encoding="utf-8") as f:
                f.write(content)
            
            logger.info(f"Created {month_file}")
            
        except Exception as e:
            logger.error(f"Monthly review generation failed for {month_key}: {e}")

def create_yearly_review():
    """Generate yearly review from monthly reviews."""
    logger.info("Starting yearly review generation...")
    
    monthlies = get_monthly_reviews()
    if not monthlies:
        logger.info("No monthly reviews found.")
        return
    
    # Group by year
    years = defaultdict(list)
    for monthly_file in monthlies:
        with open(monthly_file, 'r', encoding='utf-8') as f:
            content = f.read()
            fm = parse_frontmatter(content)
            month = fm.get('month')
            
            if not month:
                continue
            
            year = month.split('-')[0]  # Extract year from YYYY-MM
            
            years[year].append({
                "path": monthly_file,
                "content": content,
                "frontmatter": fm,
                "month": month
            })
    
    # Process each year
    for year, monthlies in years.items():
        if len(monthlies) < 3:
            logger.info(f"Year {year} has only {len(monthlies)} monthly reviews. Skipping.")
            continue
        
        year_file = JOURNALS_DIR / f"{year}_yearly.md"
        if year_file.exists():
            logger.info(f"Yearly review for {year} already exists.")
            continue
        
        logger.info(f"Creating yearly review for {year} ({len(monthlies)} months)...")
        
        # Combine monthly reviews
        combined_text = "\n\n".join([
            f"## {m['month']}\n{m['content']}"
            for m in sorted(monthlies, key=lambda x: x['month'])
        ])
        
        # RAG: Time-Offset Retrieval (Yearly)
        rag_context = ""
        try:
            # Assume year starts on Jan 1st
            year_start_date = f"{year}-01-01"
            start_dt = datetime.datetime.strptime(year_start_date, "%Y-%m-%d")
            start_ts = start_dt.timestamp()
            
            memory = MemoryManager()
            query_text = f"transformation major achievements growth"
            past_insights = memory.query(
                query_text, 
                n_results=7, 
                where={"timestamp": {"$lt": start_ts}}
            )
            
            if past_insights:
                rag_context = ""
                for idx, insight in enumerate(past_insights, 1):
                    date = insight['metadata'].get('date', 'Unknown')
                    content = insight['content']
                    rag_context += f"- ({date}): {content}\n"
                logger.info(f"Found {len(past_insights)} historical insights (before {year_start_date})")
        except Exception as e:
            logger.warning(f"Yearly Time-Offset RAG failed: {e}")

        try:
            year_next = int(year) + 1
            response = client.chat(model=cfg.model, messages=[
                {"role": "system", "content": "You are a personal assistant creating profound yearly reflections. Use first-person voice and be thoughtful."},
                {"role": "user", "content": PROMPT_YEARLY.format(
                    year=year,
                    year_next=year_next,

                    summaries=combined_text,
                    rag_context=rag_context,
                    examples=load_examples("yearly")
                )}
            ])
            
            narrative = response['message']['content']
            
            # Save Yearly Review
            month_ids = sorted([m['month'] for m in monthlies])
            content = f"""---
year: {year}
tags: [yearly, digital_twin, reflection]
months: {month_ids}
---
# Yearly Reflection: {year}

{narrative}
"""
            with open(year_file, "w", encoding="utf-8") as f:
                f.write(content)
            
            logger.info(f"Created {year_file}")
            
        except Exception as e:
            logger.error(f"Yearly review generation failed for {year}: {e}")

def main():
    """Run monthly and yearly review generation."""
    logger.info("Reviewer module started.")
    create_monthly_review()
    create_yearly_review()
    logger.info("Reviewer module completed.")

if __name__ == "__main__":
    main()
