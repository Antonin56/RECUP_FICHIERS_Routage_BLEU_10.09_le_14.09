"""One-shot: compute drift_cone for every existing eligible report.

Run after Phase B deploy so the seeded demo reports show their cones
immediately, without waiting for a fresh confirm/edit cycle.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import server  # noqa: E402  — imports load env, db, helpers


async def main() -> None:
    db = server.db
    cursor = db.reports.find(
        {"status": {"$ne": "ended"}},
        {"_id": 0, "id": 1, "type": 1, "subtype": 1, "extras": 1, "lat": 1, "lng": 1},
    )
    total = 0
    done = 0
    skipped = 0
    async for r in cursor:
        total += 1
        try:
            cone = await server.refresh_drift_cone(
                r["id"], float(r["lat"]), float(r["lng"]),
                r.get("type"), r.get("subtype"), r.get("extras"),
            )
        except Exception as e:  # noqa: BLE001
            print(f"  ! {r['id']}: {e}")
            continue
        if cone:
            done += 1
            print(f"  ✓ {r['id']:>10} {r.get('type'):>14}/{r.get('subtype') or '-':<20} → bearing={cone['bearing_deg']:>5.1f}° dist={cone['distance_km']:.2f} km")
        else:
            skipped += 1
    print(f"\nBackfill complete. scanned={total} computed={done} skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
