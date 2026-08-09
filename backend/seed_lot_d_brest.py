#!/usr/bin/env python3
"""Lot D (13/07/2026) — 10 signalements DÉRIVANTS au large de Brest/Iroise,
tous à > 20-40 km de TOUTE terre (Ouessant, Molène, Sein compris) pour
vérification des cônes VENT + COURANT avec les données de vent du secteur.
Validité : 48 h (appliquée après création)."""
import requests, time
from datetime import datetime, timezone, timedelta

BASE = "http://localhost:8001/api"
H = {"Content-Type": "application/json", "X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}

requests.post(f"{BASE}/auth/otp/request", headers=H, json={"phone": "0760071445"})
tok = requests.post(f"{BASE}/auth/otp/verify", headers=H,
                    json={"phone": "0760071445", "code": "123456"}).json()["token"]
AH = {**H, "Authorization": f"Bearer {tok}"}

# Tous types ÉLIGIBLES à la dérive (cône garanti).
LOT_D = [
    ("D-Iroise O 1",  48.30, -5.45, "obstacle_nav", "conteneur", None),
    ("D-Iroise O 2",  48.40, -5.60, "obstacle_nav", "ofni", None),
    ("D-Iroise SO 1", 48.20, -5.80, "pollution", "hydrocarbures", None),
    ("D-Iroise SO 2", 48.10, -5.70, "obstacle_nav", "conteneur", None),
    ("D-Large O 1",   48.30, -5.90, "pollution", "dechets", None),
    ("D-Large O 2",   48.45, -5.90, "obstacle_nav", "ofni", None),
    ("D-Large SO 1",  47.95, -5.50, "obstacle_nav", "conteneur", None),
    ("D-Large SO 2",  48.00, -6.00, "animal_marin", "oiseau", {"health": "dead_floating"}),
    ("D-Large O 3",   48.25, -6.20, "pollution", "hydrocarbures", None),
    ("D-Large NO",    48.55, -5.70, "obstacle_nav", "conteneur", None),
]

ids, ok = [], 0
for name, lat, lng, t, st, extras in LOT_D:
    body = {"type": t, "subtype": st, "lat": lat, "lng": lng,
            "description": f"TEST LOT {name} — dérivant au large de Brest (vent+courant)"}
    if extras:
        body["extras"] = extras
    r = requests.post(f"{BASE}/reports", headers=AH, json=body)
    if r.status_code == 200:
        d = r.json()
        dc = d.get("drift_cone") or {}
        ids.append(d["id"])
        print(f"OK  {name:14s} {d.get('short_id')} cone={'oui' if dc else 'NON'} "
              f"wind_only={dc.get('wind_only')} vent={dc.get('wind_source')}")
        ok += 1
    else:
        print(f"ERR {name:14s} {r.status_code} {r.text[:80]}")
    time.sleep(2.5)  # anti rate-limit API élévation
print(f"\n{ok}/10 créés")
