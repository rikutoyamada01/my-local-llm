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
def get_window_activity(hours: int = 24) -> List[Dict[str, Any]]:
    """
    Fetch window events from ActivityWatch (aw-watcher-window).
    Filters short events (< 1.5s) and squashes consecutive duplicates.
    """
    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(hours=hours)
    
    # Locate Bucket
    try:
        buckets = requests.get("http://localhost:5600/api/0/buckets").json()
        window_bucket = next((b for b in buckets.keys() if "aw-watcher-window" in b), None)
        
        if not window_bucket:
             print("Warning: No aw-watcher-window bucket found.")
             return []
            
        url = f"http://localhost:5600/api/0/buckets/{window_bucket}/events"
        # Fetch generous amount, then filter in python
        response = requests.get(url, params={"start": start_time.isoformat(), "end": end_time.isoformat(), "limit": 2000})
        
        if response.status_code != 200:
            return []
            
        events = response.json()
        cleaned_events = []
        last_event = None
        
        # AW returns newest first. Let's process valid ones then optionally squash on title+app.
        # But simple squashing works best on time-series.
        # Ideally we reverse to process chronologically:
        events.reverse() 
        
        for e in events:
            data = e.get("data", {})
            app = data.get("app", "")
            title = data.get("title", "")
            duration = e.get("duration", 0)
            
            # Privacy check
            if is_domain_blocked(title) or any(k in title for k in config.sensitive_keywords):
                title = sanitize_text(title)

            # Noise Filter: Skip < 1.5s unless it's a browser tab switch (sometimes fast)
            # Actually, ignore < 1.0s generally to remove alt-tab noise
            if duration < 1.5:
                continue
                
            current_obj = {
                "timestamp": e["timestamp"],
                "duration": duration,
                "app": app,
                "title": title
            }
            
            # Squashing: If same app & title as last event, merge (sum duration)
            if last_event and last_event["app"] == app and last_event["title"] == title:
                last_event["duration"] += duration
                # Should we update timestamp? Usually we keep the start time of the group.
            else:
                cleaned_events.append(current_obj)
                last_event = current_obj
                
        # Re-reverse to Newest First if desired, or keep Chronological.
        # Cognizer likely reads top-down. Let's return Chronological (Oldest -> Newest) as it flows better as a story.
        return cleaned_events
        
    except Exception as e:
        print(f"Failed to connect to ActivityWatch: {e}")
        return []

# --- Browser History Extraction (Shadow Copy) ---

# Removed get_chrome_history_path as it is now integrated into get_browser_history

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

def get_browser_history(hours: int = 24) -> List[Dict]:
    """
    Reads browser history from Chrome, Edge, and Firefox/Floorp.
    Uses a shadow copy to avoid file locking.
    """
    history_items = []
    home = Path.home()
    
    # Browser Paths
    browsers = [
        {"name": "Chrome", "path": home / "AppData/Local/Google/Chrome/User Data/Default/History", "type": "chromium"},
        {"name": "Edge", "path": home / "AppData/Local/Microsoft/Edge/User Data/Default/History", "type": "chromium"},
        {"name": "Firefox", "path": home / "AppData/Roaming/Mozilla/Firefox/Profiles", "type": "firefox"},
        {"name": "Floorp", "path": home / "AppData/Roaming/Floorp/Profiles", "type": "firefox"}
    ]

    # Calculate time range
    now = datetime.datetime.now(datetime.timezone.utc)
    # Chromium uses microseconds since 1601-01-01
    epoch_chromium = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    # Firefox uses microseconds since 1970-01-01
    epoch_firefox = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    
    cutoff_dt = now - datetime.timedelta(hours=hours)
    
    cutoff_micros_chromium = int((cutoff_dt - epoch_chromium).total_seconds() * 1_000_000)
    cutoff_micros_firefox = int((cutoff_dt - epoch_firefox).total_seconds() * 1_000_000)

    for browser in browsers:
        db_path = browser["path"]
        
        # Handle Firefox Profile Globbing
        if browser["type"] == "firefox" and db_path.exists():
            # Find the first profile that has places.sqlite
            found_profiles = list(db_path.glob("*.default*"))
            if found_profiles:
                for profile in found_profiles:
                    p = profile / "places.sqlite"
                    if p.exists():
                        db_path = p
                        break
        
        if not db_path.exists():
            continue

        temp_db = DATA_DIR / f"temp_{browser['name']}.sqlite"

        try:
            # Shadow Copy
            shadow_copy_history(db_path, temp_db)
            
            conn = sqlite3.connect(str(temp_db))
            cursor = conn.cursor()
            
            if browser["type"] == "chromium":
                query = f"""
                    SELECT url, title, last_visit_time 
                    FROM urls 
                    WHERE last_visit_time > {cutoff_micros_chromium}
                    ORDER BY last_visit_time DESC
                """
                cursor.execute(query)
                for row in cursor.fetchall():
                    url, title, timestamp = row
                    if is_domain_blocked(url) or not url: continue
                    
                    # Convert to ISO String
                    # dt = epoch_chromium + timedelta(microseconds=timestamp)
                    # We'll just store the raw string for simplicty or convert
                    visit_dt = epoch_chromium + datetime.timedelta(microseconds=timestamp)
                    
                    history_items.append({
                        "source": browser["name"],
                        "timestamp": visit_dt.isoformat(),
                        "title": sanitize_text(title),
                        "url": url
                    })
                    
            elif browser["type"] == "firefox":
                query = f"""
                    SELECT url, title, last_visit_date 
                    FROM moz_places 
                    WHERE last_visit_date > {cutoff_micros_firefox}
                    ORDER BY last_visit_date DESC
                """
                cursor.execute(query)
                for row in cursor.fetchall():
                    url, title, timestamp = row
                    if not timestamp: continue
                    if is_domain_blocked(url) or not url: continue

                    visit_dt = epoch_firefox + datetime.timedelta(microseconds=timestamp)

                    history_items.append({
                        "source": browser["name"],
                        "timestamp": visit_dt.isoformat(),
                        "title": sanitize_text(title or "No Title"),
                        "url": url
                    })

            conn.close()
            
        except Exception as e:
            print(f"Error reading {browser['name']} history: {e}")
        finally:
            if temp_db.exists():
                try:
                    os.remove(temp_db)
                except:
                    pass

    return history_items

    def fuse_streams(self, browser_history: List[Dict], window_activity: List[Dict]) -> List[Dict]:
        """
        [Algorithmic Optimization]
        Merges Browser History into Window Activity stream.
        Logic: Matches Window Event to the LATEST Preceding Browser History item 
        that matches the Title. This handles "Tab Refocus" where the page load 
        happened hours ago.
        """
        def parse_ts(iso_str):
            try:
                if not iso_str: return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                dt = datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                return dt
            except:
                return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

        # Sort: History (Old -> New), Window (Old -> New)
        browser_history.sort(key=lambda x: parse_ts(x["timestamp"]))
        window_activity.sort(key=lambda x: parse_ts(x["timestamp"]))

        fused_timeline = []
        
        # We can optimize by keeping a "Cache" of active tabs?
        # Or simple scan. N=Items. For each Window, scan history up to Window Time.
        # Since history is sorted, we can maintain a "cursor" but we need to search *backwards* or keep a running map of "Title -> Last URL".
        # Better: Maintain a `title_map: Dict[str, Dict]` where key is Title (normalized), value is History Item.
        # As we iterate through TIME, we update the map with new History items.
        # When we hit a Window event, we check the map.
        
        # Merge the two streams into one sorted list of "Events" to process linearly?
        # Event types: "H" (History), "W" (Window)
        
        combined = []
        for h in browser_history:
            combined.append({"type": "H", "time": parse_ts(h["timestamp"]), "data": h})
        for w in window_activity:
            combined.append({"type": "W", "time": parse_ts(w["timestamp"]), "data": w})
            
        combined.sort(key=lambda x: x["time"])
        
        # Running State
        # title_cache maps "sanitized_title" -> "history_item"
        title_cache = {} 
        
        # Helper to normalize titles for fuzzy matching
        def normalize(t):
            return t.lower().strip() if t else ""

        for event in combined:
            if event["type"] == "H":
                # Update Cache
                h_item = event["data"]
                norm_title = normalize(h_item["title"])
                # Also cache by simple tokens? 
                # For now, just strict normalized title. 
                # And maybe "Title - BrowserName" handling.
                if norm_title:
                   title_cache[norm_title] = h_item
                   
            elif event["type"] == "W":
                w_item = event["data"]
                fused_event = w_item.copy()
                fused_event["type"] = "app"
                fused_event["details"] = []
                
                w_app = w_item["app"].lower()
                is_browser = any(b in w_app for b in ["chrome", "edge", "firefox", "floorp", "brave"])
                
                if is_browser:
                    w_title = normalize(w_item["title"])
                    print(f"Processing Window: {w_title[:30]}...") # DEBUG
                    
                    # 1. Direct Cache Match
                    best_match = None
                    if w_title in title_cache:
                        best_match = title_cache[w_title]
                        print("  Exact Match!")
                    else:
                        for h_title, h_item in title_cache.items():
                            if h_title and (h_title in w_title or w_title in h_title):
                                best_match = h_item
                                print(f"  Fuzzy Match! {h_title[:30]}...")
                                break 
                    
                    if best_match:
                        print(f"  Attached URL: {best_match['url']}")
                        fused_event["type"] = "browse"
                        fused_event["details"].append({
                            "url": best_match["url"],
                            "title": best_match["title"],
                            "timestamp": best_match["timestamp"]
                        })
                    else:
                        print(f"  NO MATCH found in cache of {len(title_cache)} items.")
                
                fused_timeline.append(fused_event)

        return fused_timeline

    def sessionize_events(self, timeline: List[Dict], gap_threshold: int = 300) -> List[Dict]:
        """
        [Algorithmic Optimization]
        Groups consecutive events into 'Sessions' based on App similarity and time proximity.
        gap_threshold: Seconds. If gap > threshold, break session.
        """
        sessions = []
        if not timeline:
            return []
            
        def parse_ts(iso_str):
            try:
                return datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
            except:
                return datetime.datetime.now(datetime.timezone.utc)

        current_session = None
        
        for event in timeline:
            ts = parse_ts(event["timestamp"])
            duration = event.get("duration", 0)
            app = event["app"]
            title = event["title"]
            details = event.get("details", [])
            
            if current_session is None:
                current_session = {
                    "start_time": ts,
                    "end_time": ts + datetime.timedelta(seconds=duration),
                    "app": app,
                    "titles": [title],
                    "urls": [d["url"] for d in details],
                    "duration": duration,
                    "event_count": 1
                }
                continue
                
            # Check conditions to merge
            # 1. Same App
            # 2. Gap < Threshold
            gap = (ts - current_session["end_time"]).total_seconds()
            
            if app == current_session["app"] and gap < gap_threshold:
                # Merge
                current_session["end_time"] = max(current_session["end_time"], ts + datetime.timedelta(seconds=duration))
                current_session["duration"] += duration
                current_session["event_count"] += 1
                if title not in current_session["titles"]:
                    current_session["titles"].append(title)
                for d in details:
                    if d["url"] not in current_session["urls"]:
                        current_session["urls"].append(d["url"])
            else:
                # Seal current session
                current_session["start_time"] = current_session["start_time"].isoformat()
                current_session["end_time"] = current_session["end_time"].isoformat()
                sessions.append(current_session)
                
                # Start new
                current_session = {
                    "start_time": ts,
                    "end_time": ts + datetime.timedelta(seconds=duration),
                    "app": app,
                    "titles": [title],
                    "urls": [d["url"] for d in details],
                    "duration": duration,
                    "event_count": 1
                }
        
        # Append last
        if current_session:
            current_session["start_time"] = current_session["start_time"].isoformat()
            current_session["end_time"] = current_session["end_time"].isoformat()
            sessions.append(current_session)
            
        return sessions

# --- Main Execution ---
def main(hours=24, dry_run=False):
    print(f"--- Starting Sensor (Last {hours} hours) ---")
    
    # Instance
    sensor = GlobalSensor()
    
    # 1. Fetch Streams
    history = sensor.get_browser_history(hours)
    print(f"Extracted {len(history)} browser items.")
    
    events = sensor.get_window_activity(hours)
    print(f"Extracted {len(events)} window events.")
    
    # 2. Algorithmic Fusion & Sessionization
    print("Fusing streams...")
    fused = sensor.fuse_streams(history, events)
    
    print("Sessionizing events...")
    sessions = sensor.sessionize_events(fused)
    print(f"Compressed into {len(sessions)} high-level sessions.")
    
    # 3. Save
    payload = {
        "date": datetime.datetime.now().isoformat(),
        "timeline": sessions, # Optimized format
        # "raw_window": events, # Optional: Keep raw if needed for debug, but user wants optimized
        # "raw_browser": history 
    }
    
    if dry_run:
        print("Dry Run: Not saving files.")
        # print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        filename = f"sensor_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = LOGS_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Saved to {filepath}")

# Helper Class Wrapper to make methods strictly static or instance
class GlobalSensor:
    def __init__(self):
        self.temp_dir = DATA_DIR
        
    def _is_sensitive(self, text, app_name=""):
        # Wrapper for existing global is_domain_blocked / sensitive_keywords check
        if is_domain_blocked(text): return True
        # Check global config
        for k in config.sensitive_keywords:
            if k and k in text: return True
        return False

    # Attach previous methods here or refactor. 
    # For minimal diff, I will just assign the global functions to this class or call them.
    # Actually, the previous methods were top-level functions.
    # I will refactor get_browser_history and get_window_activity to be methods of GlobalSensor or just keep them global and call them.
    # To avoid huge diff, let's keep them global and just call them from main.
    # Wait, fuse_streams needs to be defined. I defined it as method `fuse_streams(self, ...)` in the replacement block.
    # So I must instantiate GlobalSensor or make it a standalone function.
    # Let's make them standalone functions for simplicity and consistency with existing code.

    def get_browser_history(self, hours):
        return get_browser_history(hours)
        
    def get_window_activity(self, hours):
        return get_window_activity(hours)
        
    def fuse_streams(self, h, w):
        return fuse_streams(h, w)
        
    def sessionize_events(self, t):
        return sessionize_events(t)

# Redefining logic as standalone functions to match existing style
def fuse_streams(browser_history: List[Dict], window_activity: List[Dict]) -> List[Dict]:
    """
    [Algorithmic Optimization]
    Merges Browser History into Window Activity stream.
    Logic: Matches Window Event to the LATEST Preceding Browser History item 
    that matches the Title. This handles "Tab Refocus" where the page load 
    happened hours ago.
    """
    def parse_ts(iso_str):
        try:
            if not iso_str: return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
            dt = datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except:
            return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    # Sort
    browser_history.sort(key=lambda x: parse_ts(x["timestamp"]))
    window_activity.sort(key=lambda x: parse_ts(x["timestamp"]))

    combined = []
    for h in browser_history:
        combined.append({"type": "H", "time": parse_ts(h["timestamp"]), "data": h})
    for w in window_activity:
        combined.append({"type": "W", "time": parse_ts(w["timestamp"]), "data": w})
        
    combined.sort(key=lambda x: x["time"])
    
    title_cache = {} 
    
    def normalize(t):
        return t.lower().strip() if t else ""

    fused_timeline = []

    for event in combined:
        if event["type"] == "H":
            h_item = event["data"]
            norm_title = normalize(h_item["title"])
            if norm_title:
               title_cache[norm_title] = h_item
               
        elif event["type"] == "W":
            w_item = event["data"]
            fused_event = w_item.copy()
            fused_event["type"] = "app"
            fused_event["details"] = []
            
            w_app = w_item["app"].lower()
            is_browser = any(b in w_app for b in ["chrome", "edge", "firefox", "floorp", "brave"])
            
            if is_browser:
                w_title = normalize(w_item["title"])
                # print(f"Processing Window: {w_title[:30]}...") 
                
                best_match = None
                if w_title in title_cache:
                    best_match = title_cache[w_title]
                    # print("  Exact Match!")
                else:
                    for h_title, h_item in title_cache.items():
                        if h_title and (h_title in w_title or w_title in h_title):
                            best_match = h_item
                            # print(f"  Fuzzy Match! {h_title[:30]}...")
                            break 
                
                if best_match:
                    # print(f"  Attached URL: {best_match['url']}")
                    fused_event["type"] = "browse"
                    fused_event["details"].append({
                        "url": best_match["url"],
                        "title": best_match["title"],
                        "timestamp": best_match["timestamp"]
                    })
            
            fused_timeline.append(fused_event)

    return fused_timeline

def sessionize_events(timeline: List[Dict], gap_threshold: int = 300) -> List[Dict]:
    sessions = []
    if not timeline: return []
        
    def parse_ts(iso_str):
        try:
            return datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        except:
            return datetime.datetime.now(datetime.timezone.utc)

    current_session = None
    
    for event in timeline:
        ts = parse_ts(event["timestamp"])
        duration = event.get("duration", 0)
        app = event["app"]
        title = event["title"]
        details = event.get("details", [])
        
        if current_session is None:
            current_session = {
                "start_time": ts,
                "end_time": ts + datetime.timedelta(seconds=duration),
                "app": app,
                "titles": [title],
                "urls": [d["url"] for d in details],
                "duration": duration,
                "event_count": 1
            }
            continue
            
        gap = (ts - current_session["end_time"]).total_seconds()
        
        if app == current_session["app"] and gap < gap_threshold:
            current_session["end_time"] = max(current_session["end_time"], ts + datetime.timedelta(seconds=duration))
            current_session["duration"] += duration
            current_session["event_count"] += 1
            if title not in current_session["titles"]:
                current_session["titles"].append(title)
            for d in details:
                if d["url"] not in current_session["urls"]:
                    current_session["urls"].append(d["url"])
        else:
            current_session["start_time"] = current_session["start_time"].isoformat()
            current_session["end_time"] = current_session["end_time"].isoformat()
            sessions.append(current_session)
            current_session = {
                "start_time": ts,
                "end_time": ts + datetime.timedelta(seconds=duration),
                "app": app,
                "titles": [title],
                "urls": [d["url"] for d in details],
                "duration": duration,
                "event_count": 1
            }
    
    if current_session:
        current_session["start_time"] = current_session["start_time"].isoformat()
        current_session["end_time"] = current_session["end_time"].isoformat()
        sessions.append(current_session)
        
    return sessions

def main(hours=24, dry_run=False):
    print(f"--- Starting Sensor (Last {hours} hours) ---")
    
    # 1. Fetch Streams
    history = get_browser_history(hours)
    print(f"Extracted {len(history)} browser items.")
    
    events = get_window_activity(hours)
    print(f"Extracted {len(events)} window events.")
    
    # 2. Algorithmic Fusion & Sessionization
    print("Fusing streams...")
    fused = fuse_streams(history, events)
    
    print("Sessionizing events...")
    sessions = sessionize_events(fused)
    print(f"Compressed into {len(sessions)} high-level sessions.")
    
    # 3. Save
    payload = {
        "date": datetime.datetime.now().isoformat(),
        "timeline": sessions
    }
    
    if dry_run:
        print("Dry Run: Not saving files.")
        # print(json.dumps(payload, indent=2, ensure_ascii=False))
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
