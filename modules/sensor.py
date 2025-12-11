import os
import shutil
import sqlite3
import datetime
import json
import re
import time
import yaml
import requests
from typing import List, Dict, Any, Optional
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# --- Configuration & Setup ---
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "secrets.yaml"

# Ensure directories exist
LOGS_DIR.mkdir(parents=True, exist_ok=True)

class ConfigLoader:
    def __init__(self):
        self.config = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
        else:
            print(f"Warning: {CONFIG_PATH} not found. Using defaults.")

    @property
    def blocked_domains(self) -> List[str]:
        return self.config.get("blocked_domains", [])

    @property
    def sensitive_keywords(self) -> List[str]:
        return self.config.get("sensitive_keywords", [])

config = ConfigLoader()

# --- Privacy & Sanitization ---
def sanitize_text(text: str) -> str:
    if not text:
        return ""
    
    # 1. Redact specific keywords
    for keyword in config.sensitive_keywords:
        if keyword:
            text = text.replace(keyword, "[REDACTED]")
    
    # 2. Basic PII (Email) - naive regex
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    text = re.sub(email_pattern, "[EMAIL_REDACTED]", text)
    
    return text

def is_domain_blocked(url: str) -> bool:
    if not url:
        return False
    for pattern in config.blocked_domains:
        if re.search(pattern, url):
            return True
    return False

# --- ActivityWatch Integration ---
def fetch_aw_events(hours: int = 24) -> List[Dict[str, Any]]:
    """Fetch window events from ActivityWatch (aw-watcher-window)."""
    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(hours=hours)
    
    # ISO format for API
    params = {
        "start": start_time.isoformat(),
        "end": end_time.isoformat(),
        "bucket_id": "aw-watcher-window_yamadarikuto" # TODO: Make hostname dynamic if needed
    }
    
    # Locate the correct bucket (names vary by hostname)
    try:
        buckets = requests.get("http://localhost:5600/api/0/buckets").json()
        window_bucket = next((b for b in buckets.keys() if "aw-watcher-window" in b), None)
        
        if not window_bucket:
            print("Warning: No aw-watcher-window bucket found.")
            return []
            
        url = f"http://localhost:5600/api/0/buckets/{window_bucket}/events"
        response = requests.get(url, params={"start": params["start"], "end": params["end"]})
        
        if response.status_code != 200:
            print(f"Error fetching AW events: {response.status_code}")
            return []
            
        events = response.json()
        sanitized_events = []
        
        for e in events:
            data = e.get("data", {})
            app = data.get("app", "")
            title = data.get("title", "")
            
            # Privacy check on title
            if any(k in title for k in config.sensitive_keywords):
                title = sanitize_text(title)
                
            sanitized_events.append({
                "timestamp": e["timestamp"],
                "duration": e["duration"],
                "app": app,
                "title": title
            })
            
        return sanitized_events
        
    except Exception as e:
        print(f"Failed to connect to ActivityWatch: {e}")
        return []

# --- Browser History Extraction (Shadow Copy) ---

def get_chrome_history_path() -> Optional[Path]:
    """Returns the default Chrome history path on Windows."""
    # Typical path: C:\Users\<User>\AppData\Local\Google\Chrome\User Data\Default\History
    # Or: C:\Users\<User>\AppData\Local\Microsoft\Edge\User Data\Default\History
    home = Path.home()
    
    # Priorities: Chrome -> Edge -> None
    paths = [
        home / "AppData/Local/Google/Chrome/User Data/Default/History",
        home / "AppData/Local/Microsoft/Edge/User Data/Default/History"
    ]
    
    for p in paths:
        if p.exists():
            return p
    return None

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(PermissionError)
)
def shadow_copy_history(src_path: Path, dest_path: Path):
    """
    Attempts to copy the locked SQLite file.
    Retries on PermissionError (file lock) using tenacity.
    """
    try:
        shutil.copy2(src_path, dest_path)
    except PermissionError:
        print(f"File locked: {src_path}. Retrying...")
        raise # Triggers retry
    except Exception as e:
        print(f"Unexpected error copying history: {e}")
        raise

def extract_browser_history(hours: int = 24) -> List[Dict[str, Any]]:
    history_db = get_chrome_history_path()
    if not history_db:
        print("No Browser History file found.")
        return []

    temp_db = DATA_DIR / "temp_history.sqlite"
    
    # 1. Shadow Copy
    try:
        shadow_copy_history(history_db, temp_db)
    except Exception as e:
        print(f"Failed to copy Browser History after retries: {e}")
        print("Falling back to generic Window titles only.")
        return []

    # 2. Query SQLite
    history_items = []
    try:
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()
        
        # Chrome stores time in microseconds since 1601-01-01 (Webkit format)
        # We need to calculate the cutoff
        # Easier: just fetch recent items and filter in python or do the math
        # 1601-01-01 to 1970-01-01 is 11644473600 seconds
        
        query = """
        SELECT url, title, visit_count, last_visit_time 
        FROM urls 
        ORDER BY last_visit_time DESC 
        LIMIT 1000
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        # Calculate cutoff for 'hours'
        # Webkit timestamp is microseconds
        now_webkit = (datetime.datetime.now(datetime.timezone.utc).timestamp() + 11644473600) * 1000000
        cutoff_webkit = now_webkit - (hours * 3600 * 1000000)
        
        for row in rows:
            url, title, visit_count, last_visit_time = row
            
            if last_visit_time < cutoff_webkit:
                continue
                
            if is_domain_blocked(url):
                continue
                
            title = sanitize_text(title)
            
            history_items.append({
                "source": "browser",
                "url": url,
                "title": title,
                "timestamp_webkit": last_visit_time
            })
            
    except Exception as e:
        print(f"Error reading SQLite DB: {e}")
    finally:
        if temp_db.exists():
            try:
                os.remove(temp_db)
            except:
                pass

    return history_items

# --- Main Execution ---
def main(hours=24, dry_run=False):
    print(f"--- Starting Sensor (Last {hours} hours) ---")
    
    # 1. Fetch Browser History
    history = extract_browser_history(hours)
    print(f"Extracted {len(history)} browser items.")
    
    # 2. Fetch ActivityWatch
    events = fetch_aw_events(hours)
    print(f"Extracted {len(events)} window events.")
    
    # 3. Merge & Save
    payload = {
        "date": datetime.datetime.now().isoformat(),
        "browser_history": history,
        "window_activity": events
    }
    
    if dry_run:
        print("Dry Run: Not saving files.")
        # print(json.dumps(payload, indent=2)) 
    else:
        filename = f"sensor_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = LOGS_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Saved to {filepath}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not save output to disk")
    parser.add_argument("--hours", type=int, default=24, help="Hours of history to fetch")
    args = parser.parse_args()
    
    main(hours=args.hours, dry_run=args.dry_run)
