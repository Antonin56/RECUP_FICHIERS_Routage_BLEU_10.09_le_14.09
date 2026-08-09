"""SignalMar — One-shot photo compression migration.

Resizes every base64 image stored in `reports.photos` to max 800px on the long
side and re-encodes as JPEG q=70. Demo photos drop from ~1.3 MB to ~80 KB —
crucial for mobile JS heap (previous size caused an OOM crash on Android).

Idempotent: the compressed payload is always smaller than the original, so
re-running it on already-compressed images is a no-op (size delta ≈ 0).
"""

import asyncio
import base64
import io
import os
import re
from typing import Optional

from PIL import Image
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

_DATA_URI = re.compile(r"^data:image/[^;]+;base64,(.+)$", re.S)


def compress_b64(src: str, max_side: int = 800, quality: int = 70) -> Optional[str]:
    """Return a compressed base64 data-URI, or None if the input isn't an image."""
    try:
        m = _DATA_URI.match(src)
        payload = m.group(1) if m else src
        raw = base64.b64decode(payload)
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        # Long-side resize keeping aspect ratio.
        w, h = img.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        out = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{out}"
    except Exception as e:
        print(f"   ! compression failed: {e}")
        return None


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    cursor = db.reports.find({"photos": {"$ne": []}}, {"_id": 0, "id": 1, "photos": 1})
    total_before = 0
    total_after = 0
    rewritten = 0
    skipped = 0
    async for r in cursor:
        photos = r.get("photos") or []
        new_photos = []
        rid = r["id"]
        changed = False
        for src in photos:
            before = len(src)
            total_before += before
            # If photo is already small (< 150 KB), skip — likely already compressed.
            if before < 150_000:
                new_photos.append(src)
                total_after += before
                skipped += 1
                continue
            compressed = compress_b64(src)
            if compressed is None:
                new_photos.append(src)
                total_after += before
                continue
            new_photos.append(compressed)
            total_after += len(compressed)
            changed = True
        if changed:
            await db.reports.update_one({"id": rid}, {"$set": {"photos": new_photos}})
            rewritten += 1
    print(
        f"✅ Compression done. {rewritten} reports rewritten, "
        f"{skipped} photos already small. "
        f"Total {total_before / 1024 / 1024:.1f} MB → {total_after / 1024 / 1024:.1f} MB "
        f"(−{(1 - total_after / max(total_before, 1)) * 100:.0f}%)."
    )
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
