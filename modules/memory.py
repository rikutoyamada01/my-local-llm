import os
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Any

from chromadb import HttpClient
from chromadb.config import Settings

# --- Configuration ---
CHROMA_HOST = os.environ.get("CHROMA_HOST", "http://chromadb:8000")
COLLECTION_NAME = "digital_twin_memory"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Monkey-patch PostHog to silence the pesky telemetry error if possible
try:
    import chromadb.telemetry.product.posthog as posthog
    if hasattr(posthog, 'Posthog'):
        class NoOpPosthog:
            def __init__(self, *args, **kwargs): pass
            def capture(self, *args, **kwargs): pass
            def flush(self): pass
        posthog.Posthog = NoOpPosthog
except Exception:
    pass

class MemoryManager:
    def __init__(self):
        try:
            # Connect to ChromaDB container
            # Robust parsing of CHROMA_HOST
            host_str = str(CHROMA_HOST)
            if "://" in host_str:
                host_str = host_str.split("://")[-1]
            
            if ":" in host_str:
                host, port = host_str.split(":")
                port = int(port)
            else:
                host, port = host_str, 8000
                
            self.client = HttpClient(
                host=host, 
                port=port,
                settings=Settings(anonymized_telemetry=False)
            )
            
            # Get or Create Collection
            self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
            logger.info(f"Connected to ChromaDB: {COLLECTION_NAME} at {host}:{port}")
            
        except Exception as e:
            logger.error(f"Failed to connect to ChromaDB: {e}")
            self.collection = None

    def ingest_fact(self, fact: str, date_str: str, metadata: Dict = None):
        if not self.collection:
            return
            
        if metadata is None:
            metadata = {}
            
        metadata['date'] = date_str
        # Ensure timestamp is float
        metadata['timestamp'] = float(datetime.datetime.strptime(date_str, "%Y-%m-%d").timestamp())
        
        # ID generation
        import hashlib
        doc_id = hashlib.md5((fact + date_str).encode()).hexdigest()
        
        try:
            self.collection.add(
                documents=[fact],
                metadatas=[metadata],
                ids=[doc_id]
            )
            logger.info(f"Ingested fact: {fact[:30]}...")
        except Exception as e:
            logger.error(f"Error ingesting fact: {e}")

    def query(self, text: str, n_results: int = 5, where: Dict = None) -> List[Dict]:
        if not self.collection:
            return []

        try:
            results = self.collection.query(
                query_texts=[text],
                n_results=n_results * 2,
                where=where
            )
            
            if not results['documents'] or not results['documents'][0]:
                return []

            docs = results['documents'][0]
            metas = results['metadatas'][0]
            dists = results['distances'][0]
            
            scored_results = []
            jst = datetime.timezone(datetime.timedelta(hours=9))
            now_ts = datetime.datetime.now(jst).timestamp()
            
            for doc, meta, dist in zip(docs, metas, dists):
                base_score = 1 / (1 + dist)
                event_ts = meta.get('timestamp', 0)
                days_old = max(0, (now_ts - event_ts) / 86400)
                time_decay = 1 / (1 + 0.05 * days_old)
                final_score = base_score * (1 + time_decay)
                
                scored_results.append({
                    "content": doc,
                    "metadata": meta,
                    "score": final_score
                })
            
            scored_results.sort(key=lambda x: x['score'], reverse=True)
            return scored_results[:n_results]
            
        except Exception as e:
            logger.error(f"Query Error: {e}")
            return []

if __name__ == "__main__":
    mem = MemoryManager()
    if mem.collection:
        print(f"Memory Manager Initialized. Collection count: {mem.collection.count()}")
