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
# Detect if running in Docker (assumed /app exists) or Local
if Path("/app").exists():
    BASE_DIR = Path("/app")
else:
    # Local execution: Parent of 'modules' folder
    # Assuming valid structure: <root>/modules/cognizer.py
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
    except NameError:
        BASE_DIR = Path.cwd() # Fallback for interactive modes

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "secrets.yaml"

# Ensure output directories (Logs)
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
        self.context_limit = int(self.config.get("context_limit", 8192))
        
        # Resolve Journals Directory: Env > Secrets > Default
        env_path = os.environ.get("OBSIDIAN_MOUNT_PATH")
        secret_path = self.config.get("obsidian_mount_path")
        
        if env_path:
            self.journals_dir = Path(env_path)
        elif secret_path:
            self.journals_dir = Path(secret_path)
        else:
            self.journals_dir = DATA_DIR / "journals"

cfg = ConfigLoader()
JOURNALS_DIR = cfg.journals_dir
client = ollama.Client(host=cfg.host)

# Ensure output directories (Journals)
JOURNALS_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"Journals Directory: {JOURNALS_DIR}")

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

**JSON FORMAT REQUIREMENTS**:
YOU MUST RETURN VALID JSON WITH EXACTLY THE FOLLOWING STRUCTURE. DO NOT DEVIATE.

1. "summary": STRING - A short paragraph (2-3 sentences) in First-Person.
2. "activities": OBJECT with THREE REQUIRED KEYS:
   - "morning": ARRAY OF STRINGS (activities from 6:00-12:00)
   - "afternoon": ARRAY OF STRINGS (activities from 12:00-18:00)  
   - "evening": ARRAY OF STRINGS (activities from 18:00-6:00)
   **CRITICAL**: Each value MUST be an array of strings, even if empty: []
3. "learnings": ARRAY OF STRINGS (NOT objects/dicts)
   - Each learning MUST be a single string describing one insight
   - Example: "I learned that PostgreSQL JSONB indexing improves query performance by 10x"
   - DO NOT use objects like {"topic": "...", "filesTouched": [...]}
4. "productivity_score": INTEGER (1-10)
5. "main_focus": STRING  
6. "facts": ARRAY OF STRINGS
7. "next_steps": ARRAY OF STRINGS

**TIME PERIOD CLASSIFICATION**:
- Use timestamps from the timeline to categorize activities
- Morning: 6:00 AM - 12:00 PM
- Afternoon: 12:00 PM - 6:00 PM
- Evening: 6:00 PM - 6:00 AM (next day)

**CORRECT EXAMPLE**:
{
  "summary": "Today I focused heavily on refactoring the authentication module and researching PostgreSQL optimization techniques.",
  "activities": {
    "morning": ["Refactored the API authentication module", "Reviewed GitHub PRs for my-local-llm project"],
    "afternoon": ["Debugged login flow issues", "Researched PostgreSQL JSONB indexing"],
    "evening": ["Read documentation about Graph Databases", "Updated project README.md"]
  },
  "learnings": [
    "I learned that PostgreSQL B-tree indexes work efficiently with JSONB columns using GIN indexes",
    "The Orchestrator pattern helps decouple authentication logic from business logic"
  ],
  "productivity_score": 8,
  "main_focus": "Backend Development",
  "facts": ["Implemented: Auth Module Refactor", "Fixed: Login Bug in OAuth flow", "Researched: PostgreSQL JSONB optimization"],
  "next_steps": ["Continue refactoring auth middleware", "Research Redis caching strategies"]
}

**INCORRECT EXAMPLE (DO NOT DO THIS)**:
{
  "activities": [],  // ❌ WRONG - not an object with morning/afternoon/evening
  "learnings": [
    {"topic": "PostgreSQL", "researched": "indexing"}  // ❌ WRONG - should be a string
  ]
}

**PAST CONTEXT**:
You will be provided with summaries from yesterday and/or last week.
Use this context to:
- Highlight **progress** made since the last session.
- Identify **changes** in focus or approach.
- Deepen the "Learnings" section by connecting new insights to previous knowledge.

**GUIDELINES FOR 'LEARNINGS'**:
- **AVOID** generic software engineering platitudes (e.g., "I learned that testing is important", "Optimization is key").
- **FOCUS** on specific topics found in window titles or URLs.
- Example: Instead of "I learned about Python error handling", say "I investigated `ValueError` in `json.load` and learned how to handle malformed UTF-8."
- Infer the "Why": If multiple window titles show "Error 500" followed by "stackoverflow.com/questions/...", assume I was debugging that specific error.

**CRITICAL REMINDERS**:
1. ALWAYS return valid JSON
2. ALWAYS include all 7 required keys
3. "activities" MUST be an object with "morning", "afternoon", "evening" keys
4. "learnings" MUST be an array of strings, NOT objects
5. Use timestamps to intelligently distribute activities across time periods
6. If no activity for a time period, use empty array: []
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

Past Context:
{past_context}

Synthesize these into the Structured Daily Journal JSON format.
Focus on **specific details**: what files were touched? what specific topics were researched?
Avoid generic phrases like "various components" or "general research".
Use the "Past Context" to provide better continuity and deeper insights in the "Learnings" section.
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
        # --- Context Retrieval ---
        try:
            past_context = get_past_context(date_str)
            logger.info(f"Past Context Length: {len(past_context)}")
        except Exception as e:
            logger.warning(f"Failed to retrieve past context: {e}. Proceeding without it.")
            past_context = "No past context available due to retrieval error."
        
        response = client.chat(model=cfg.model, format='json', messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": PROMPT_FINAL.format(date=date_str, timeline_summary=final_context, past_context=past_context)}
        ])
        
        content = response['message']['content']
        
        # --- Debug Logging ---
        logger.info(f"=== RAW LLM RESPONSE (first 1000 chars) ===")
        logger.info(content[:1000])
        logger.info("=== END RAW RESPONSE ===")

        result_json = json.loads(content)
        logger.info(f"JSON Keys Received: {list(result_json.keys())}")
        
        # DEBUG: Check summary explicitly
        if 'summary' in result_json:
            logger.info(f"Summary found (len={len(result_json['summary'])}): {result_json['summary'][:50]}...")
        else:
            logger.error("NO SUMMARY KEY in LLM response!")
        
        # --- Validate structure before saving ---
        if 'activities' in result_json:
            if isinstance(result_json['activities'], dict):
                logger.info(f"Activities keys: {list(result_json['activities'].keys())}")
                # DEBUG: Inspect first activity
                for k in ['morning', 'afternoon', 'evening']:
                    act_list = result_json['activities'].get(k, [])
                    if act_list:
                        logger.info(f"First activity in {k}: {act_list[0]}")
            else:
                logger.warning(f"Activities is NOT a dict: {type(result_json['activities'])}")
        elif 'tasks' in result_json:
            # Fallback: Map 'tasks' to 'activities' (assign to afternoon/general)
            logger.warning(f"LLM returned 'tasks' instead of 'activities'. Remapping {len(result_json['tasks'])} tasks.")
            result_json['activities'] = {
                'morning': [],
                'afternoon': result_json['tasks'], # Assign tasks list to afternoon
                'evening': []
            }
        else:
             logger.warning("No 'activities' or 'tasks' key found in LLM response.")
        
        if 'learnings' in result_json:
            logger.info(f"Learnings type: {type(result_json['learnings'])}, count: {len(result_json['learnings'])}")
            if result_json['learnings'] and not isinstance(result_json['learnings'][0], str):
                logger.warning(f"First learning item is NOT a string: {type(result_json['learnings'][0])}")
        
        # Save Outputs
        logger.info("Calling save_journal with data keys: " + str(list(result_json.keys())))
        save_journal(date_str, result_json)
        
        # Mark log as processed (rename)
        new_name = log_file.with_suffix('.json.processed')
        log_file.rename(new_name)
        logger.info(f"Finished processing {log_file}")
        
    except Exception as e:
        logger.error(f"Final Generation Error: {e}")

def get_past_context(current_date_str: str) -> str:
    """Retrieves summaries from yesterday and 7 days ago."""
    try:
        curr_date = datetime.date.fromisoformat(current_date_str.split("T")[0])
    except ValueError:
        return ""
        
    offsets = {"Yesterday": 1, "Last Week": 7}
    context_parts = []
    
    for label, days in offsets.items():
        target_date = curr_date - datetime.timedelta(days=days)
        target_file = JOURNALS_DIR / f"{target_date}_daily.md"
        
        if target_file.exists():
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Extract Summary block: > [!SUMMARY] ... (until header or end)
                    # Simple extraction: look for [!SUMMARY] line and take following lines starting with >
                    summary_lines = []
                    capture = False
                    for line in content.splitlines():
                        if "[!SUMMARY]" in line:
                            capture = True
                            continue
                        if capture:
                            if line.strip().startswith(">"):
                                summary_lines.append(line.strip().replace(">", "").strip())
                            else:
                                break # End of block
                    
                    if summary_lines:
                        context_parts.append(f"[{label} ({target_date})]: {' '.join(summary_lines)}")
            except Exception as e:
                logger.warning(f"Failed to read journal {target_file}: {e}")
                
    if not context_parts:
        return "No past journals found."
        
    return "\n".join(context_parts)

def save_journal(date_str: str, data: Dict):
    # 1. Narrative (Markdown)
    safe_date = date_str.split("T")[0]
    md_path = JOURNALS_DIR / f"{safe_date}_daily.md"
    
    # Extract Data
    summary = data.get('summary', 'No summary generated.')
    activities = data.get('activities', {})
    learnings_raw = data.get('learnings', [])
    prod_score = data.get('productivity_score', 5)
    main_focus = data.get('main_focus', 'General')
    facts = data.get('facts', [])
    next_steps = data.get('next_steps', [])
    
    # --- Validate and Sanitize Learnings ---
    learnings = []
    for item in learnings_raw:
        if isinstance(item, str):
            learnings.append(item)
        elif isinstance(item, dict):
            # Handle malformed dict learnings - extract meaningful text
            logger.warning(f"Learnings contains dict instead of string: {item}. Attempting to convert.")
            # Try to construct a readable string from the dict
            # Schema variations: topic, insight, description
            topic = item.get('topic', '')
            insight = item.get('insight', '')
            desc = item.get('description', '')
            
            # Choose the best primary text
            primary_text = insight or desc or topic or "No detail provided"
            
            files = item.get('filesTouched', [])
            researched = item.get('researched', '')
            related = item.get('related_files', [])
            
            all_files = list(set(files + related))
            
            # Build a coherent learning string
            learning_str = primary_text
            if topic and topic != primary_text:
                learning_str = f"[{topic}] {learning_str}"
                
            if all_files:
                learning_str += f" (Files: {', '.join(all_files)})"
            if researched:
                learning_str += f" - Researched: {researched}"
            
            learnings.append(learning_str)
        else:
            logger.warning(f"Learnings contains unknown type: {type(item)}. Skipping.")
    
    # --- Validating Activities structure ---
    morning, afternoon, evening = [], [], []
    
    if isinstance(activities, dict):
        morning = activities.get('morning', [])
        afternoon = activities.get('afternoon', [])
        evening = activities.get('evening', [])
        
        # Ensure all are lists
        if not isinstance(morning, list): morning = []
        if not isinstance(afternoon, list): afternoon = []
        if not isinstance(evening, list): evening = []
        
    elif isinstance(activities, list):
        # Fallback: distribute to afternoon
        afternoon = activities
        logger.warning(f"Activities received as list instead of dict. Distributing to Afternoon.")
    else:
        logger.warning(f"Activities received in unknown format: {type(activities)}. Defaulting to empty.")
    
    # --- Final Validation - If ALL time periods are empty, log a warning ---
    if not morning and not afternoon and not evening:
        logger.error(f"WARNING: All activity time periods are empty for {safe_date}. Check LLM output!")
    
    # Helper to sanitize and format activities
    def sanitize_activities(items: List[Any]) -> List[str]:
        sanitized = []
        for item in items:
            if isinstance(item, str):
                sanitized.append(item)
            elif isinstance(item, dict):
                # Handle raw log dictionary or bad schema
                # Schemas seen: 
                # 1. Standard: {'activity': '...', 'topics': [...]}
                # 2. 'Tasks' fallback: {'topic': '...', 'description': '...', 'related_files': []}
                
                time_range = ""
                if 'start_time' in item:
                    start = item.get('start_time', '')
                    end = item.get('end_time', '')
                    time_range = f"[{start}-{end}] "
                
                # Extract main activity description
                act = item.get('activity') or item.get('description') or item.get('topic')
                
                app = item.get('application', '')
                topics = item.get('topics', [])
                urls = item.get('urls', [])
                
                # Fallback logic for activity title
                if not act:
                    # Try to use the first topic (usually window title)
                    if topics and isinstance(topics[0], str):
                        act = topics[0]
                        # Remove used topic from list to avoid duplication
                        topics = topics[1:]
                    elif app:
                        act = f"Using {app}"
                    else:
                        act = "Unknown Activity"

                # If parsed from 'tasks', topic might be title, description might be detail
                if not item.get('activity') and item.get('topic') and item.get('description'):
                    # format as "Topic: Description"
                    act = f"{item['topic']}: {item['description']}"
                
                # Format: [HH:MM-HH:MM] Activity (App) - Topics
                line = f"{time_range}{act}"
                if app and act != f"Using {app}":
                    line += f" ({app})"
                
                if topics:
                    clean_topics = [t for t in topics if isinstance(t, str)]
                    if clean_topics:
                        line += f": {', '.join(clean_topics[:5])}"
                        if len(clean_topics) > 5: line += "..."
                
                if urls:
                    # extract url string from dict or str
                    clean_urls = []
                    for u in urls:
                        if isinstance(u, dict):
                            clean_urls.append(u.get('url', ''))
                        elif isinstance(u, str):
                            clean_urls.append(u)
                    clean_urls = [u for u in clean_urls if u]
                    if clean_urls:
                        line += f" (URLs: {', '.join(clean_urls[:3])})"
                
                sanitized.append(line)
            else:
                sanitized.append(str(item))
        return sanitized

    # Sanitize all lists
    morning = sanitize_activities(morning)
    afternoon = sanitize_activities(afternoon)
    evening = sanitize_activities(evening)

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

## Next Steps
{fmt_list(next_steps)}
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
