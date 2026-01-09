# test_memory.ps1
# Test script for memory.py (runs in Docker)

param (
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

Write-Host "=== Testing Memory Module ===" -ForegroundColor Cyan

try {
    # Check Docker
    docker info | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }
    
    # Ensure ChromaDB is running
    Write-Host "Starting ChromaDB if not running..." -ForegroundColor Yellow
    docker compose up -d chromadb
    Start-Sleep -Seconds 3
    
    Write-Host "Docker is running [OK]" -ForegroundColor Green
    
    # Run memory.py test
    Write-Host "`nTesting memory module..." -ForegroundColor Yellow
    docker compose run --rm core python -c "
import sys
sys.path.insert(0, '/app')
from modules.memory import MemoryManager

print('Initializing MemoryManager...')
mem = MemoryManager()

if mem.collection:
    print('[OK] Connected to ChromaDB successfully!')
    
    # Test ingestion
    print('Testing fact ingestion...')
    mem.ingest_fact('Test fact: Memory module is working', '2026-01-08')
    
    # Test query
    print('Testing query...')
    results = mem.query('memory module', n_results=3)
    
    if results:
        print(f'[OK] Query returned {len(results)} results')
        for i, r in enumerate(results):
            print(f'  {i+1}. {r[\"content\"][:50]}... (score: {r[\"score\"]:.3f})')
    else:
        print('[WARN] Query returned no results')
else:
    print('[ERROR] Failed to connect to ChromaDB')
    sys.exit(1)
"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Memory module test completed successfully!" -ForegroundColor Green
    } else {
        throw "Memory test failed with exit code $LASTEXITCODE"
    }
    
} catch {
    Write-Host "`n[ERROR] $_" -ForegroundColor Red
    exit 1
}
