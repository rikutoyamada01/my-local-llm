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

# Import MemoryManager for RAG
try:
    from memory import MemoryManager
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from memory import MemoryManager

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
SAMPLES_DIR = DATA_DIR / "samples"

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
You are a personal productivity analyst creating an actionable daily reflection.
Your goal: Transform raw activity data into insights that drive continuous improvement.

**PHILOSOPHY**: This is not passive logging - it's active self-optimization.
Focus on: **Impact** (value created), **Energy** (when focus peaked), **Growth** (what improved), **Momentum** (progress toward goals).

Use **First-Person** voice ("I...") for all sections.

IMPORTANT: Even for short or sparse logs, you MUST generate a summary. Do not return empty fields.
**CRITICAL**: Be specific. Do not just say "I worked on code" or "Processed files".
If the log shows file usage (e.g., window titles like `cognizer.py`, `README.md`), you MUST explicitly say "I edited `cognizer.py`" or "I updated `README.md`".
Identify the **project name** from the window titles (e.g., "Antigravity", "my-local-llm") and mention it.
**Include specific filenames, URLs, project names, and error messages** where visible in the logs.

**JSON FORMAT - EXACTLY THESE KEYS**:
1. "summary": STRING - First-person impact narrative (2-3 sentences focusing on VALUE created and PROGRESS made)
2. "activities": ARRAY OF STRINGS with context.
3. "learnings": ARRAY OF STRINGS - Generalizable, conceptual insights (Experience-based).
   - Format: "Context -> Action/Decision -> Result/Principle"
   - REQUIRED: Focus on the "Why" and "Root Cause" derived from actual experience.
   - Example: "Distributed System State: Enforcing strong consistency caused high latency. Switching to eventual consistency significantly improved availability."
   - AVOID: "Use `chown 1000:1000`." (Too specific. Instead: "Permission Issues: Aligning container UID with host fixed volume access errors.")
4. "productivity_score": INTEGER (1-10)
5. "main_focus": STRING (primary work area)
6. "facts": ARRAY OF STRINGS (concrete achievements:
 files touched, bugs fixed)
7. "next_steps": ARRAY OF STRINGS (actionable items for tomorrow)
8. "energy_level": STRING ("high"/"medium"/"low" - overall vitality)
9. "focus_time": STRING (when deep work happened, e.g., "Morning 9-11AM")
10. "distractions": ARRAY OF STRINGS (what broke flow - meetings, notifications, etc.)

**CORRECT EXAMPLE**:
{examples}

**INCORRECT EXAMPLE (DO NOT DO THIS)**:
{
  "activities": {"morning": []},  // ❌ WRONG - should be a simple list of strings
  "learnings": [
    {"topic": "PostgreSQL", "researched": "indexing"}  // ❌ WRONG - should be a string
  ]
  "productivity_score": 5,
  "main_focus": "Development/Research/etc",
  "next_steps": ["Action item 1", "Action item 2"]
}

**RULES**:
1. **activities**: MUST be an ARRAY of STRINGS. Format: "HH:MM - Description". DO NOT use Objects.
2. **learnings**: Focus on technical details found in logs.
3. Be specific with filenames and errors.
4. Output ONLY valid JSON.
"""

PROMPT_MAP_REDUCE = """
Summarize these logs into bullet points. Preserve filenames (e.g. `cognizer.py`) and specific URL topics.
Logs:
{logs}
"""

PROMPT_FINAL = """
Here are the activity logs for {date}. 
Activity Timeline:
{timeline_summary}

Past Context:
{past_context}

Generate the JSON summary. 
- Keep descriptions specific (filenames, errors).
- Activities MUST be strings: "HH:MM - [App] Description".
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

def load_samples() -> str:
    """Loads example JSONs from data/samples to guide the LLM."""
    examples = []
    if SAMPLES_DIR.exists():
        for f in SAMPLES_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as file:
                    # Validation
                    data = json.load(file)
                    examples.append(json.dumps(data, indent=2, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"Failed to load sample {f}: {e}")
    
    if not examples:
        return "No examples available - please follow the rules strictly."
        
    return "\n\n".join(examples)

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
            past_context = "No past context available due to retrieval error."
        
        # --- Contextual RAG ---
        rag_patterns = ""
        try:
            # Query RAG using the timeline summary to find relevant past insights
            # addressing user feedback to avoid noise from simple error matching
            query_text = final_context[:500] 
            logger.info("Querying RAG for relevant past insights...")
            
            # Calculate timestamp for start of this day to filter only PAST insights
            current_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            current_ts = current_dt.timestamp()

            memory = MemoryManager()
            past_insights = memory.query(
                query_text, 
                n_results=3,
                where={"timestamp": {"$lt": current_ts}}
            )
            
            if past_insights:
                rag_patterns = "\n\n**RELEVANT PAST INSIGHTS (CONTEXT)**:\n"
                for idx, item in enumerate(past_insights, 1):
                     content = item['content']
                     date = item['metadata'].get('date', 'Unknown')
                     rag_patterns += f"{idx}. ({date}) {content}\n"
                logger.info(f"Found {len(past_insights)} relevant past insights via RAG")
        except Exception as e:
            logger.warning(f"RAG context retrieval failed: {e}")

        # Load reference examples
        examples_text = load_samples()
        system_prompt = PROMPT_SYSTEM.format(examples=examples_text) + rag_patterns

        response = client.chat(model=cfg.model, format='json', messages=[
            {"role": "system", "content": system_prompt},
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
            if isinstance(result_json['activities'], list):
                logger.info(f"Activities count: {len(result_json['activities'])}")
            elif isinstance(result_json['activities'], dict):
                # Handle case where LLM still returns a dict (backward compatibility/hallucination)
                logger.warning("Activities returned as dict, flattening...")
                flattened = []
                for k, v in result_json['activities'].items():
                    if isinstance(v, list):
                        flattened.extend(v)
                result_json['activities'] = flattened
            else:
                 logger.warning(f"Activities is NOT a list: {type(result_json['activities'])}")
        elif 'tasks' in result_json:
            # Fallback
            result_json['activities'] = result_json['tasks']
        else:
             logger.warning("No 'activities' or 'tasks' key found in LLM response.")
        
        if 'learnings' in result_json:
            logger.info(f"Learnings type: {type(result_json['learnings'])}, count: {len(result_json['learnings'])}")
            if result_json['learnings'] and not isinstance(result_json['learnings'][0], str):
                logger.warning(f"First learning item is NOT a string: {type(result_json['learnings'][0])}")
        
        # Save Outputs
        logger.info("Calling save_journal with data keys: " + str(list(result_json.keys())))
        save_journal(date_str, result_json)
        
        # Ingest LEARNINGS to ChromaDB for RAG (High-Value Knowledge)
        try:
            learnings = result_json.get('learnings', [])
            if learnings:
                logger.info(f"Ingesting {len(learnings)} learnings to ChromaDB...")
                memory = MemoryManager()
                for insight in learnings:
                    if isinstance(insight, str):
                        memory.ingest_fact(insight, date_str, metadata={
                            "source": "daily_log",
                            "type": "learning",
                            "productivity_score": result_json.get('productivity_score', 5),
                            "main_focus": result_json.get('main_focus', 'General')
                        })
                logger.info("Learnings successfully ingested to memory.")
        except Exception as e:
            logger.warning(f"Failed to ingest learnings to memory: {e}")
        
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
    
    # Extract Data (Robust Fallback)
    summary = data.get('summary', 'No summary generated.')
    
    # Handle 'tasks' vs 'activities' confusion
    activities_raw = data.get('activities', {})
    if not activities_raw and 'tasks' in data:
        activities_raw = data['tasks']
        logger.info("Using 'tasks' as activities source.")

    learnings_raw = data.get('learnings', [])
    prod_score = data.get('productivity_score', 5)
    main_focus = data.get('main_focus', 'General')
    facts = data.get('facts', [])
    next_steps = data.get('next_steps', [])
    energy_level = data.get('energy_level', 'medium')
    focus_time = data.get('focus_time', 'Not tracked')
    distractions = data.get('distractions', [])
    
    # --- Validate and Sanitize Learnings ---
    learnings = []
    for item in learnings_raw:
        if isinstance(item, str):
            learnings.append(item)
        elif isinstance(item, dict):
            # Quietly handle dicts without spamming warnings (common with smaller models)
            topic = item.get('topic', '')
            insight = item.get('insight', '') or item.get('summary') or item.get('description', '')
            
            # Choose the best primary text
            primary_text = insight or topic or "No detail provided"
            
            # Format: "**Topic**: Insight"
            if topic and topic != primary_text:
                learnings.append(f"**{topic}**: {primary_text}")
            else:
                learnings.append(primary_text)
        else:
            logger.warning(f"Skipping unknown learning type: {type(item)}")
    
    # --- Validating Activities structure ---
    activities_list = []
    
    if isinstance(activities_raw, list):
        activities_list = activities_raw
    elif isinstance(activities_raw, dict):
        # Flatten if dict received
        for k, v in activities_raw.items():
            if isinstance(v, list):
                activities_list.extend(v)
    else:
        logger.warning(f"Activities received in unknown format: {type(activities_raw)}. Defaulting to empty.")
    
    if not activities_list:
        logger.error(f"WARNING: Activity list is empty for {safe_date}. Check LLM output!")
    
    # Helper to sanitize and format activities
    def sanitize_activities(items: List[Any]) -> List[str]:
        sanitized = []
        for item in items:
            if isinstance(item, str):
                sanitized.append(item)
            elif isinstance(item, dict):
                # Robust Dict Parsing
                
                # 1. Extract Main Title/Task
                act = item.get('activity') or item.get('task') or item.get('topic') or item.get('description')
                
                # 2. Extract Details (String or List)
                details = item.get('details') or item.get('action') or []
                
                # 3. Consolidate Details if it's a list
                details_str = ""
                if isinstance(details, list):
                    # Handle [{"file": "...", "action": "..."}] or ["step 1", "step 2"]
                    sub_actions = []
                    for d in details:
                        if isinstance(d, str):
                            sub_actions.append(d)
                        elif isinstance(d, dict):
                            # Try "action" + "file" or just "file"
                            a = d.get('action', '')
                            f = d.get('file', '')
                            if a and f: sub_actions.append(f"{a} {f}")
                            elif a: sub_actions.append(a)
                            elif f: sub_actions.append(f)
                            else: sub_actions.append(json.dumps(d, ensure_ascii=False))
                    if sub_actions:
                        details_str = "; ".join(sub_actions)
                elif isinstance(details, str):
                    details_str = details
                
                # 4. Construct Final String
                if act:
                    line = f"**{act}**"
                    if details_str:
                        line += f": {details_str}"
                        
                    # Add URL/App context if strictly present and not redundant
                    app = item.get('application')
                    if app and app not in line: 
                        line += f" ({app})"
                        
                    sanitized.append(line)
                else:
                    # Fallback (Just try to print values)
                    vals = [str(v) for v in item.values() if isinstance(v, (str, int, float))]
                    if vals:
                        sanitized.append(", ".join(vals))
                    else:
                        sanitized.append(f"Raw: {json.dumps(item, ensure_ascii=False)}")
                        
            else:
                sanitized.append(str(item))
        return sanitized

    # Sanitize
    activities_list = sanitize_activities(activities_list)

    # Helper to format lists
    def fmt_list(items):
        return "\n".join([f"- {item}" for item in items]) if items else "- No major activities recorded."

    frontmatter = f"""---
date: {safe_date}
tags: [daily, digital_twin]
productivity_score: {prod_score}
main_focus: {main_focus}
energy_level: {energy_level}
focus_time: "{focus_time}"
facts: {json.dumps(facts)}
---
"""
    content = f"""{frontmatter}
# Daily Log: {safe_date}

> [!SUMMARY] Daily Summary
> {summary}

## Activities
{fmt_list(activities_list)}

> [!NOTE] Learnings & Insights
{fmt_list(learnings)}

## 📊 Energy & Focus
- **Energy Level**: {energy_level}
- **Peak Focus Time**: {focus_time}
- **Distractions**: {', '.join(distractions) if distractions else 'None tracked'}

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
