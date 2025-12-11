from modules.sensor import GlobalSensor, get_browser_history, get_window_activity
import datetime

def parse_ts(iso_str):
    try:
        return datetime.datetime.fromisoformat(str(iso_str).replace('Z', '+00:00'))
    except:
        return None

def main():
    print("--- Debugging Timestamps ---")
    
    # 1. Fetch Raw Streams
    print("Fetching last 24 hours...")
    history = get_browser_history(hours=24)
    events = get_window_activity(hours=24)
    
    print(f"\nBrowser History ({len(history)} items):")
    for h in history[:5]: # Show top 5
        print(f"  [{h['timestamp']}] {h['title']} ({h['source']})")
        
    print(f"\nWindow Events ({len(events)} items):")
    # Filter for browser windows
    browser_wins = [e for e in events if "floorp" in e['app'].lower() or "chrome" in e['app'].lower()]
    for w in browser_wins[:5]:
        print(f"  [{w['timestamp']}] {w['title']} ({w['app']})")
        
    # Check overlap
    if history and browser_wins:
        h_last = parse_ts(history[0]['timestamp'])
        # events (browser_wins) are Oldest -> Newest (due to reverse() in sensor.py)
        # So the LAST element is the LATEST time.
        w_last = parse_ts(browser_wins[-1]['timestamp'])
        print(f"\nLatest Hist: {h_last}")
        print(f"Latest Win : {w_last}")
        if h_last and w_last:
            diff = (w_last - h_last).total_seconds()
            print(f"Offset (Win - Hist): {diff} seconds")

if __name__ == "__main__":
    main()
