#!/bin/bash
# Ré-ingestion façade Atlantique (22/07/2026) — îles puis balises puis dangers.
set -x
cd /app/backend
python3 scripts/ingest_islands.py --zone atl100
echo "=== ISLANDS EXIT: $? ==="
python3 scripts/ingest_seamarks.py --zone atl100
echo "=== SEAMARKS EXIT: $? ==="
python3 scripts/ingest_hazards.py --zone atl100
echo "=== HAZARDS EXIT: $? ==="
echo "=== INGESTION TERMINEE $(date -u) ==="
