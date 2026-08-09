import os
import sys
import time

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
from core.auth import make_jwt  # noqa: E402

import requests  # noqa: E402

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_BACKEND_URL") or "http://localhost:8001").rstrip("/")
tok = make_jwt("user_0b6070a69154")
h = {"Authorization": f"Bearer {tok}"}

# 1) Route eau profonde avec marée → attendu : route ZH + message "MARÉE BASSE"
t0 = time.time()
r = requests.post(f"{BASE}/api/routes/compute", json={
    "start": {"lat": 47.610, "lng": -2.825}, "end": {"lat": 47.595, "lng": -2.851},
    "draft_m": 1.5, "depth_margin_m": 0.5, "use_tide": True}, headers=h, timeout=300)
print("deep route:", r.status_code, f"{time.time()-t0:.1f}s")
j = r.json()
print("  tide_m(route):", j.get("tide_m"), "threshold:", j.get("threshold_m"), "min_depth:", j.get("min_depth_m"))
for w in j.get("warnings", []):
    print("  ⚠", w[:120])

# 2) Route Golfe → Vannes avec marée → repli marée attendu si ZH tronque
t0 = time.time()
r2 = requests.post(f"{BASE}/api/routes/compute", json={
    "start": {"lat": 47.554, "lng": -2.905}, "end": {"lat": 47.6553, "lng": -2.7594},
    "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": True}, headers=h, timeout=300)
print("vannes route:", r2.status_code, f"{time.time()-t0:.1f}s")
j2 = r2.json()
print("  tide_m(route):", j2.get("tide_m"), "offset:", (j2.get("end_snapped") or {}).get("offset_m"),
      "compute_s:", j2.get("compute_s"))
for w in j2.get("warnings", []):
    print("  ⚠", w[:120])
