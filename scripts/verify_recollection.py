import sys
import os
import datetime
# Add module path
sys.path.append("/app")

from modules.memory import MemoryManager

def verify_recency_bias():
    print("=== Initializing Memory Manager ===")
    mem = MemoryManager()
    
    # Clean slate for test (optional, but good for clarity)
    try:
        mem.client.delete_collection("digital_twin_memory")
        mem.collection = mem.client.create_collection("digital_twin_memory")
        print("Cleared existing memory for clean test.")
    except:
        pass

    print("\n=== Ingesting Test Facts ===")
    
    # Use JST (Japan Standard Time, UTC+9) for consistency
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now_jst = datetime.datetime.now(jst)
    
    # Fact 1: Old (30 days ago)
    old_date = (now_jst - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    fact_old = "I love eating Sushi for dinner."
    print(f"Ingesting OLD Fact ({old_date}): {fact_old}")
    mem.ingest_fact(fact_old, old_date, {"type": "test"})

    # Fact 2: Recent (Today)
    recent_date = now_jst.strftime("%Y-%m-%d")
    fact_new = "I changed my mind, I now love eating Pizza for dinner."
    print(f"Ingesting NEW Fact ({recent_date}): {fact_new}")
    mem.ingest_fact(fact_new, recent_date, {"type": "test"})

    print("\n=== Performing RAG Query ===")
    query = "What do I like for dinner?"
    print(f"Query: '{query}'")
    
    results = mem.query(query, n_results=5)
    
    print("\n=== Results (Ranked by Score) ===")
    print(f"{'Score':<10} | {'Base (Sim)':<10} | {'Date':<12} | {'Content'}")
    print("-" * 80)
    
    for r in results:
        meta = r['metadata']
        content = r['content']
        score = r['score']
        base = r['base_score']
        date = meta.get('date', 'N/A')
        
        print(f"{score:.4f}     | {base:.4f}     | {date:<12} | {content}")

    print("\n=== Verification ===")
    if len(results) >= 2:
        top_result = results[0]
        if "Pizza" in top_result['content']:
            print("SUCCESS: The recent fact (Pizza) is ranked higher than the old fact (Sushi).")
            print("Time-Weighted Retrieval is working correctly.")
        else:
            print("FAILURE: The old fact is ranked higher. Tune the decay factor in memory.py.")
    else:
        print("Note: Not enough results to compare.")

if __name__ == "__main__":
    verify_recency_bias()
