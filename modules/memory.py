import os
import json
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Any

import chromadb
from chromadb.config import Settings

# --- Configuration ---
CHROMA_HOST = os.environ.get("CHROMA_HOST", "http://chromadb:8000")
COLLECTION_NAME = "digital_twin_memory"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self):
        try:
            # Connect to ChromaDB container
            # The host format might vary based on chromadb version, 
            # but usually for client/server it's HttpClient
            host, port = CHROMA_HOST.split("://")[-1].split(":")
            self.client = chromadb.HttpClient(host=host, port=port)
            
            # Get or Create Collection
            self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
            logger.info(f"Connected to ChromaDB: {COLLECTION_NAME}")
            
        except Exception as e:
            logger.error(f"Failed to connect to ChromaDB: {e}")
            self.collection = None

    def ingest_fact(self, fact: str, date_str: str, metadata: Dict = None):
        if not self.collection:
            return
            
        if metadata is None:
            metadata = {}
            
        metadata['date'] = date_str
        metadata['timestamp'] = datetime.datetime.strptime(date_str, "%Y-%m-%d").timestamp()
        
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
        """
        Retrieves relevant context with Time-Weighted Re-ranking.
        Args:
            text: Query text
            n_results: Number of results to return
            where: ChromaDB filter dict (e.g., {"timestamp": {"$lt": 1234567890}})
        """
        if not self.collection:
            return []

        try:
            results = self.collection.query(
                query_texts=[text],
                n_results=n_results * 2, # Fetch more for re-ranking
                where=where
            )
            
            # Flatten results structure
            # results['documents'] is [[doc1, doc2...]]
            docs = results['documents'][0]
            metas = results['metadatas'][0]
            dists = results['distances'][0]
            
            scored_results = []
            
            # Current time for decay
            now_ts = datetime.datetime.now().timestamp()
            
            for doc, meta, dist in zip(docs, metas, dists):
                # Similarity Score (approximated from distance)
                # Cosine distance: lower is better. 0 = identical.
                # Let's convert to similarity: 1 / (1 + dist)
                base_score = 1 / (1 + dist)
                
                # Recency Boost
                # Calculate days since event
                event_ts = meta.get('timestamp', 0)
                days_old = (now_ts - event_ts) / 86400
                
                # Decay function: 1 / (1 + 0.1 * days_old)
                # Recent events (0 days) -> factor 1.0
                # 30 days old -> 1 / 4 = 0.25
                time_decay = 1 / (1 + 0.05 * days_old)
                
                # Final Score
                final_score = base_score * (1 + time_decay)
                
                scored_results.append({
                    "content": doc,
                    "metadata": meta,
                    "score": final_score,
                    "base_score": base_score
                })
            
            # Sort by Final Score DESC
            scored_results.sort(key=lambda x: x['score'], reverse=True)
            
            return scored_results[:n_results]
            
        except Exception as e:
            logger.error(f"Query Error: {e}")
            return []

if __name__ == "__main__":
    # Test
    mem = MemoryManager()
    print("Memory Manager Initialized.")
