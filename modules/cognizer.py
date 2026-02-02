import os
import sys
import json
import datetime
import glob
import logging
import yaml
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict
import ollama

# --- Configuration & Setup ---
if Path("/app").exists():
    BASE_DIR = Path("/app")
else:
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
    except NameError:
        BASE_DIR = Path.cwd()

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "secrets.yaml"
CATEGORIES_PATH = BASE_DIR / "config" / "categories.yaml"
SAMPLES_DIR = DATA_DIR / "samples"
UNCATEGORIZED_LOG = LOGS_DIR / "uncategorized_activities.log"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConfigLoader:
    def __init__(self):
        self.config = {}
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"Failed to load secrets.yaml: {e}")
        
        self.host = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
        self.model = self.config.get("ollama_model", "llama3")
        
        # Path Resolution
        env_path = os.environ.get("OBSIDIAN_MOUNT_PATH")
        secret_path = self.config.get("obsidian_vault_path_host") or self.config.get("obsidian_mount_path")
        
        if env_path:
            self.journals_dir = Path(env_path)
        elif secret_path:
            self.journals_dir = Path(secret_path)
        else:
            self.journals_dir = DATA_DIR / "journals"

cfg = ConfigLoader()
JOURNALS_DIR = cfg.journals_dir
JOURNALS_DIR.mkdir(parents=True, exist_ok=True)
client = ollama.Client(host=cfg.host)

PROMPT_SYSTEM = """
You are a reflective daily journal assistant that helps users gain insights from their day.
Your job is to analyze a structured timeline and create a meaningful reflection with scores, insights, and actionable feedback.

**INPUT**: A list of activities categorized by type (Work, Break, Comms, etc.) with time spent.
**OUTPUT**: A structured reflection in English following the format below.

**ANALYSIS FRAMEWORK**:
1. **Productivity Scoring**: Rate the day's effectiveness (1-10) based on:
   - Focus time on meaningful work (Work/Coding)
   - Balance between work and breaks
   - Alignment with goals (if visible from project names)
   
2. **Deep Work Analysis**: Identify patterns in focus and distraction
   - Long focused sessions = high quality work
   - Frequent context switches = fragmented attention

3. **Insights**: Go beyond facts. Ask:
   - What did this work session *achieve*?
   - Were there inefficiencies?
   - What can be learned from the patterns?

4. **Emotional Context**: If entertainment/breaks are high, note potential burnout or procrastination

**RULES**:
- Write in **English**
- Be **reflective**, not just descriptive
- Provide **actionable insights**
- Mention specific project names when visible
- Use a **first-person** perspective ("I spent...", "I focused on...")
"""

PROMPT_USER = """
Here is the activity timeline for {date}:

{timeline_text}

**Time Distribution Stats**:
{stats_text}

**Context from Yesterday**:
{yesterday_context}

**Historical Insights** (from past reflections):
{rag_context}

**Required Output Format**:

## 🎯 Daily Reflection

### Productivity Score: X/10
[One sentence justification for the score based on focus time, achievements, and balance]

### Summary
[2-3 sentences describing what was actually accomplished today. Focus on outcomes and meaning, not just activities.]

### 💡 Key Insights
- [Insight 1: Pattern observed, e.g., "Long coding session on Antigravity suggests deep progress on core features"]
- [Insight 2: Efficiency observation, e.g., "Frequent context switches between Teams and browser may have fragmented focus"]
- [Insight 3: Balance note, if relevant]
- [If relevant: Connection to yesterday's focus or past patterns from RAG context]

### 🚀 Tomorrow's Focus
- [One actionable recommendation based on today's patterns and yesterday's goals]

---

Now generate the reflection for {date}.
"""



# --- Core Logic: Categorization ---

class Categorizer:
    def __init__(self):
        self.rules = {}
        self.load_rules()
        self.unknown_cache = set()

    def load_rules(self):
        if CATEGORIES_PATH.exists():
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                self.rules = yaml.safe_load(f).get("categories", {})
        else:
            logger.warning("categories.yaml not found! Using empty rules.")

    def classify(self, app_name: str, window_title: str) -> Tuple[str, str, str]:
        """
        Returns (CategoryLabel, ActivityName, Icon)
        e.g. ("💻 Work", "Coding", "💻")
        """
        app_lower = app_name.lower()
        title_lower = window_title.lower() if window_title else ""

        # 1. Iterate through categories by priority
        sorted_cats = sorted(self.rules.items(), key=lambda x: x[1].get('priority', 999))

        for cat_key, rule in sorted_cats:
            label = rule.get('label', cat_key)
            icon = label.split()[0] if " " in label else "❓"
            
            # A. Check Specific Activities (Keyword Match in ID/Title)
            if 'activities' in rule:
                for activity in rule['activities']:
                    act_name = activity['name']
                    # strict keyword matching on title or app
                    keywords = activity.get('keywords', [])
                    for kw in keywords:
                        kw_lower = kw.lower()
                        if kw_lower in title_lower: #or kw_lower in app_lower:
                            return label, act_name, icon
            
            # B. Check App Name match (Fallback for Category)
            if 'apps' in rule:
                for target_app in rule['apps']:
                    if target_app.lower() in app_lower:
                        # Default activity for this category if no specific keyword matched
                        return label, "General", icon

        # 2. Uncategorized
        self.log_uncategorized(app_name, window_title)
        return "❓ Uncategorized", app_name, "❓"

    def log_uncategorized(self, app: str, title: str):
        sig = f"{app}::{title}"
        if sig not in self.unknown_cache:
            self.unknown_cache.add(sig)
            try:
                with open(UNCATEGORIZED_LOG, "a", encoding="utf-8") as f:
                    # Use JST (Japan Standard Time, UTC+9) for logging
                    jst = datetime.timezone(datetime.timedelta(hours=9))
                    now_jst = datetime.datetime.now(jst)
                    timestamp = now_jst.isoformat()
                    f.write(f"[{timestamp}] App: '{app}', Title: '{title}'\n")
            except Exception as e:
                logger.error(f"Failed to log uncategorized: {e}")

# --- Core Logic: Visualization ---

class TimelineVisualizer:
    def __init__(self, timeline_data: List[Dict]):
        self.raw_timeline = timeline_data
        self.categorizer = Categorizer()
        self.processed_blocks = []
        self.stats = defaultdict(int) # Duration by Category
        self.process()

    def process(self):
        """
        Refines the raw timeline:
        - Categorizes each event
        - Smooths short interruptions
        - Merges consecutive identical blocks
        """
        if not self.raw_timeline:
            return

        # 1. Initial Classification
        temp_blocks = []
        for event in self.raw_timeline:
            start = event.get("start_time")
            end = event.get("end_time")
            duration = event.get("duration", 0)
            app = event.get("app", "Unknown")
            titles = event.get("titles", [])
            main_title = titles[0] if titles else ""

            cat_label, activity, icon = self.categorizer.classify(app, main_title)
            
            temp_blocks.append({
                "start": start,
                "end": end,
                "duration": duration,
                "category": cat_label,
                "activity": activity,
                "icon": icon,
                "app": app,
                "title": main_title
            })

        # 2. Smoothing & Merging
        # Strategy: Merge block B into A if:
        # - B is very short (< 15s) AND
        # - A is "Focus" (Work/Coding) AND
        # - B is NOT a strong context switch (e.g. not Gaming)
        
        merged_blocks = []
        if not temp_blocks: return

        current = temp_blocks[0]

        for i in range(1, len(temp_blocks)):
            next_block = temp_blocks[i]
            
            # Time gap check (if logs have gaps)
            # Assuming contiguous for now or handled by start/end timestamps

            # Merge Condition 1: Same Activity
            if current['category'] == next_block['category'] and current['activity'] == next_block['activity']:
                current['end'] = next_block['end']
                current['duration'] += next_block['duration']
                # Append title if unique and important? Simplified for now.
                continue
            
            # Merge Condition 2: Noise Smoothing (Next block is short noise)
            is_noise = next_block['duration'] < 30 # 30 seconds threshold
            is_compatible = (current['category'] == "💻 Work") and (next_block['category'] != "🎮 Entertainment")
            
            if is_noise and is_compatible:
                # Absorb the noise
                current['end'] = next_block['end']
                current['duration'] += next_block['duration']
                continue

            # Else: Commit current and move to next
            merged_blocks.append(current)
            current = next_block
        
        merged_blocks.append(current)
        self.processed_blocks = merged_blocks

        # 3. Calculate Stats
        for b in self.processed_blocks:
            self.stats[b['category']] += b['duration']

    def generate_markdown(self) -> str:
        lines = []
        for b in self.processed_blocks:
            # Parse ISO timestamps to HH:MM in JST
            # Convert to JST (Japan Standard Time, UTC+9)
            jst = datetime.timezone(datetime.timedelta(hours=9))
            s_dt = datetime.datetime.fromisoformat(b['start'])
            e_dt = datetime.datetime.fromisoformat(b['end'])
            # Convert to JST if timestamp has timezone info
            if s_dt.tzinfo is not None:
                s_dt = s_dt.astimezone(jst)
            if e_dt.tzinfo is not None:
                e_dt = e_dt.astimezone(jst)
            s_str = s_dt.strftime("%H:%M")
            e_str = e_dt.strftime("%H:%M")
            
            duration_min = int(b['duration'] / 60)
            if duration_min < 5: continue # Skip short activities (less than 5 min)

            # Format: > [!check] 💻 **Coding** (09:00 - 10:00) 60m
            #         > Working on Antigravity
            
            # Choose callout type based on category
            callout_type = "example" # default
            if "Work" in b['category']: callout_type = "abstract" # cyan
            if "Break" in b['category']: callout_type = "success" # green
            if "Comms" in b['category']: callout_type = "quote" # grey
            
            title_clean = b['title'].replace('[', '(').replace(']', ')')
            
            lines.append(f"> [!{callout_type}] {b['icon']} **{b['activity']}** ({s_str} - {e_str}) `{duration_min} min`")
            lines.append(f"> *{b['app']}*: {title_clean}")
            lines.append(">") # Spacer

        return "\n".join(lines)

    def generate_mermaid_gantt(self) -> str:
        """Generate Mermaid Gantt Chart grouped by project/app for better insights"""
        lines = ["```mermaid", "gantt", "title Activity Timeline", "dateFormat HH:mm", "axisFormat %H:%M"]
        
        # Convert to JST helper
        def to_jst(iso_str):
            jst = datetime.timezone(datetime.timedelta(hours=9))
            dt = datetime.datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone(jst)
            return dt
        
        # Extract project name from title or app dynamically
        def extract_project(block):
            title = block.get('title', '')
            app = block.get('app', '')
            
            # Common app name cleanup
            app_clean = app.replace('.exe', '').strip()
            
            # Pattern 1: "ProjectName - AppName - Details" (common in IDEs)
            # Example: "MyLife - Antigravity - update_dashboard.py"
            if ' - ' in title:
                parts = title.split(' - ')
                if len(parts) >= 2:
                    # First part is usually the project/folder name
                    project_name = parts[0].strip()
                    # Filter out app names that might appear in first position
                    common_apps = ['Visual Studio', 'Antigravity', 'Obsidian', 'Microsoft']
                    if project_name and not any(app_word in project_name for app_word in common_apps):
                        return project_name
                    # Second part might be project name
                    elif len(parts) >= 2:
                        second_part = parts[1].strip()
                        if second_part and len(second_part) > 2:
                            return second_part
            
            # Pattern 2: Check for known development tools and extract folder/project
            dev_tools = {
                'devenv.exe': 'Visual Studio',
                'Code.exe': 'VS Code',
                'pycharm': 'PyCharm',
                'idea': 'IntelliJ',
            }
            
            for tool_app, tool_name in dev_tools.items():
                if tool_app.lower() in app.lower():
                    # Try to extract project from title
                    # Pattern: "project_name - filename* - Tool"
                    if ' - ' in title:
                        project = title.split(' - ')[0].strip()
                        if project and len(project) > 2:
                            return f"{project} ({tool_name})"
                    return tool_name
            
            # Pattern 3: Browser grouping
            browsers = ['floorp.exe', 'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe']
            if any(browser in app.lower() for browser in browsers):
                return '🌐 Browser'
            
            # Pattern 4: Common productivity apps with emojis
            app_mappings = {
                'Obsidian': '📓 Obsidian',
                'Teams': '💬 Teams',
                'Slack': '💬 Slack',
                'Discord': '💬 Discord',
                'Notion': '📝 Notion',
            }
            
            for app_keyword, display_name in app_mappings.items():
                if app_keyword.lower() in app.lower() or app_keyword.lower() in title.lower():
                    return display_name
            
            # Fallback: Use cleaned app name
            if app_clean and len(app_clean) > 1:
                return app_clean.title()
            
            return 'Other'
        
        # Separate long tasks (>=5min) and short interruptions (<5min)
        long_tasks = []
        short_tasks = []
        
        for b in self.processed_blocks:
            s_dt = to_jst(b['start'])
            e_dt = to_jst(b['end'])
            duration_sec = (e_dt - s_dt).total_seconds()
            
            if duration_sec < 60: continue  # Skip <1min
            
            task = {
                'project': extract_project(b),
                'category': b['category'],
                'activity': b['activity'],
                'start': s_dt,
                'end': e_dt,
                'duration_min': int(duration_sec / 60),
                'title': b['title']
            }
            
            if task['duration_min'] >= 5:
                long_tasks.append(task)
            else:
                short_tasks.append(task)
        
        # Group long tasks by project
        project_tasks = defaultdict(list)
        for t in long_tasks:
            project_tasks[t['project']].append(t)
        
        # Sort projects by total time (descending)
        project_totals = {proj: sum(t['duration_min'] for t in tasks) 
                         for proj, tasks in project_tasks.items()}
        sorted_projects = sorted(project_totals.items(), key=lambda x: x[1], reverse=True)
        
        # Display long tasks by project
        for proj, total_min in sorted_projects:
            tasks = project_tasks[proj]
            
            # Check if project name already has emoji
            if any(char in proj for char in ['📝', '📊', '🖥️', '🌐', '📓', '💬', '📁', '🎮', '🎵']):
                # Already has emoji, use as-is
                section_name = proj
            else:
                # Assign emoji based on project characteristics
                emoji = '📁'  # Default
                
                # Development/coding projects
                if any(keyword in proj.lower() for keyword in ['visual studio', 'vs code', 'pycharm', 'intellij']):
                    emoji = '�️'
                # Specific known projects (flexible pattern matching)
                elif 'antigravity' in proj.lower():
                    emoji = '�'
                elif 'mylife' in proj.lower():
                    emoji = '📊'
                # Documentation/writing
                elif any(keyword in proj.lower() for keyword in ['doc', 'readme', 'note']):
                    emoji = '�'
                # Web/browser already handled in extract_project
                
                section_name = f"{emoji} {proj}"
            
            lines.append(f"section {section_name}")
            
            for t in tasks:
                label = t['activity']
                start = t['start'].strftime("%H:%M")
                end = t['end'].strftime("%H:%M")
                lines.append(f"{label} ({t['duration_min']}m) : {start}, {end}")
        
        # Display short interruptions as "Brief Switches" section
        if short_tasks:
            lines.append("section ⚡ Brief Switches")
            for t in short_tasks:
                label = f"{t['activity']}"
                start = t['start'].strftime("%H:%M")
                end = t['end'].strftime("%H:%M")
                # Use 'crit' to visually distinguish interruptions
                lines.append(f"{label} ({t['duration_min']}m) : crit, {start}, {end}")
        
        lines.append("```")
        return "\n".join(lines)

    def generate_stats_table(self) -> str:
        total_sec = sum(self.stats.values())
        if total_sec == 0: return ""
        
        lines = ["| Category | Time | % |", "|---|---|---|"]
        
        sorted_stats = sorted(self.stats.items(), key=lambda x: x[1], reverse=True)
        for cat, seconds in sorted_stats:
            m = int(seconds / 60)
            h = round(m / 60, 1)
            pct = round((seconds / total_sec) * 100, 1)
            lines.append(f"| {cat} | {h}h ({m}m) | {pct}% |")
            
        return "\n".join(lines)
        
    def get_text_for_llm(self) -> str:
        """Simplified text representation for the LLM prompt"""
        lines = []
        for b in self.processed_blocks:
            s_dt = datetime.datetime.fromisoformat(b['start'])
            e_dt = datetime.datetime.fromisoformat(b['end'])
            duration_min = int(b['duration'] / 60)
            if duration_min < 5: continue
            
            lines.append(f"[{b['category']}] {b['activity']} ({duration_min}m): {b['title']} (App: {b['app']})")
        return "\n".join(lines)

# --- Main Pipeline ---

def process_logs(log_file: Path):
    logger.info(f"Processing {log_file}...")
    
    with open(log_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    date_str = data.get("date", str(datetime.date.today()))
    safe_date = date_str.split("T")[0]
    
    # 1. Visualize & Categorize
    timeline_raw = data.get("timeline", [])
    viz = TimelineVisualizer(timeline_raw)
    
    # 2. Get Yesterday's Journal (for context)
    yesterday_context = ""
    try:
        # Calculate yesterday's date
        current_dt = datetime.datetime.strptime(safe_date, "%Y-%m-%d")
        yesterday_dt = current_dt - datetime.timedelta(days=1)
        yesterday_str = yesterday_dt.strftime("%Y-%m-%d")
        yesterday_file = JOURNALS_DIR / f"{yesterday_str}_daily.md"
        
        if yesterday_file.exists():
            with open(yesterday_file, 'r', encoding='utf-8') as f:
                yesterday_content = f.read()
                # Extract only the reflection section (skip detailed activities)
                if "## 🎯 Daily Reflection" in yesterday_content:
                    reflection_start = yesterday_content.find("## 🎯 Daily Reflection")
                    reflection_end = yesterday_content.find("## 📊 Time Distribution")
                    if reflection_end > reflection_start:
                        yesterday_context = yesterday_content[reflection_start:reflection_end].strip()
                    else:
                        yesterday_context = yesterday_content[reflection_start:].strip()
                else:
                    # Fallback: take first 500 chars
                    yesterday_context = yesterday_content[:500]
                logger.info(f"Loaded yesterday's journal: {yesterday_file}")
        else:
            yesterday_context = "(No journal from yesterday)"
            logger.info("No journal found from yesterday")
    except Exception as e:
        logger.warning(f"Failed to load yesterday's journal: {e}")
        yesterday_context = "(Unable to load yesterday's journal)"
    
    # 3. RAG: Retrieve Historical Insights
    rag_context = ""
    try:
        from memory import MemoryManager
        memory = MemoryManager()
        
        # Query for relevant insights before today
        current_dt = datetime.datetime.strptime(safe_date, "%Y-%m-%d")
        current_ts = current_dt.timestamp()
        
        query_text = "productivity insights focus achievements challenges patterns"
        past_insights = memory.query(
            query_text,
            n_results=3,
            where={"timestamp": {"$lt": current_ts}}
        )
        
        if past_insights:
            rag_lines = []
            for idx, insight in enumerate(past_insights, 1):
                date = insight['metadata'].get('date', 'Unknown')
                content = insight['content']
                rag_lines.append(f"- ({date}): {content}")
            rag_context = "\n".join(rag_lines)
            logger.info(f"Retrieved {len(past_insights)} historical insights from memory")
        else:
            rag_context = "(No historical insights found)"
    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        rag_context = "(RAG unavailable)"
    
    # 4. LLM Summary with context
    timeline_text = viz.get_text_for_llm()
    stats_text = viz.generate_stats_table()
    
    summary = ""
    try:
        response = client.chat(model=cfg.model, messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": PROMPT_USER.format(
                date=safe_date,
                timeline_text=timeline_text,
                stats_text=stats_text,
                yesterday_context=yesterday_context,
                rag_context=rag_context
            )}
        ])
        summary = response['message']['content']
    except Exception as e:
        logger.error(f"LLM Error: {e}")
        summary = "AI summarization failed."

    # 3. Assemble Markdown
    md_path = JOURNALS_DIR / f"{safe_date}_daily.md"
    
    markdown_content = f"""---
date: {safe_date}
tags: [daily, digital_twin]
---
# Daily Log: {safe_date}

{summary}

## 📊 Time Distribution
{viz.generate_stats_table()}

## 📅 Timeline (Gantt)
{viz.generate_mermaid_gantt()}

## ⏰ Detailed Activities
{viz.generate_markdown()}
"""

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    
    logger.info(f"Saved Journal: {md_path}")
    
    # Rename processed file
    new_name = log_file.with_suffix('.json.processed')
    log_file.rename(new_name)
    logger.info("Done.")

def main():
    if len(sys.argv) > 1:
        log_path = Path(sys.argv[1])
        if log_path.exists():
            process_logs(log_path)
            return
        else:
            logger.error(f"File not found: {log_path}")
    else:
        # Auto-process logs
        logs = glob.glob(str(LOGS_DIR / "sensor_log_*.json"))
        for log in logs:
            process_logs(Path(log))

if __name__ == "__main__":
    main()
