"""Repro bug armateur 26/07 — route Vilaine « Foireuse 3 » coupée à Tréhiguier."""
import json, sys
import requests
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from core.auth import make_jwt

tok = make_jwt("user_0b6070a69154")
B = "https://nav-routing-speed.preview.emergentagent.com/api"
h = {"Authorization": f"Bearer {tok}"}

def compute(end_lat, end_lng, label, use_tide=True, extra=0.0):
    body = {
        "start": {"lat": 47.61, "lng": -2.825},
        "end": {"lat": end_lat, "lng": end_lng},
        "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 50,
        "use_tide": use_tide,
    }
    if extra:
        body["safety_extra_m"] = extra
    r = requests.post(f"{B}/routes/compute", json=body, headers=h, timeout=120)
    print(f"=== {label} → HTTP {r.status_code}")
    j = r.json()
    if r.status_code == 200:
        wps = j.get("waypoints") or []
        print("  wp:", len(wps), "| dernier:", wps[-1] if wps else None,
              "| dist", round(j.get("distance_m", 0)), "| min_depth", j.get("min_depth_m"))
        for w in (j.get("warnings") or []):
            print("  ⚠", w)
        lm = j.get("low_margin")
        if lm: print("  low_margin:", lm)
        print("  risk:", j.get("risk"), "| compromised:", bool(j.get("compromised_from")))
    else:
        det = j.get("detail")
        if isinstance(det, dict):
            print("  code:", det.get("code"), "| msg:", det.get("message"))
            fb = det.get("fallback_route")
            if fb:
                print("  fallback wp:", len(fb.get("waypoints", [])), "compromised_from:", fb.get("compromised_from"))
        else:
            print(" ", det)

# 1) destination exacte de l'armateur (aval/amont barrage ?)
compute(47.4969, -2.3846, "Foireuse (47.4969,-2.3846) avec marée")
# 2) juste en AVAL du barrage (chenal balisé No15-23)
compute(47.4995, -2.3950, "Aval barrage (47.4995,-2.3950) avec marée")
# 3) milieu du chenal (-2.41)
compute(47.4930, -2.4100, "Chenal -2.41 avec marée")
# 4) destination armateur SANS marée (comportement de base)
compute(47.4969, -2.3846, "Foireuse SANS marée", use_tide=False)
