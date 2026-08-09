#!/usr/bin/env python3
"""Seed du lot de 30 signalements TEST (13/07/2026) — vérification bande 20 km.
Lot A : 10 dans le golfe du Morbihan (dont fond du golfe près de Séné).
Lot B : 10 entre le golfe et Belle-Île (Mor Braz / baie de Quiberon).
Lot C : 10 au-delà de 20 km des côtes (dont sud-est de Belle-Île).
"""
import requests, json, sys

BASE = "http://localhost:8001/api"
H = {"Content-Type": "application/json", "X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}

requests.post(f"{BASE}/auth/otp/request", headers=H, json={"phone": "0760071445"})
tok = requests.post(f"{BASE}/auth/otp/verify", headers=H,
                    json={"phone": "0760071445", "code": "123456"}).json()["token"]
AH = {**H, "Authorization": f"Bearer {tok}"}

# (lot, lat, lng, type, subtype, extras)
LOTS = [
    # ── Lot A : golfe du Morbihan ──
    ("A-Séné fond du golfe",   47.6155, -2.7280, "obstacle_nav", "conteneur", None),
    ("A-Séné anse",            47.6100, -2.7420, "pollution", "hydrocarbures", None),
    ("A-Conleau",              47.6220, -2.7680, "obstacle_nav", "tronc", None),
    ("A-Île d'Arz E",          47.5760, -2.7300, "animal_marin", "mammifere", None),
    ("A-Île aux Moines N",     47.5950, -2.7890, "obstacle_nav", "conteneur", None),
    ("A-Arradon S",            47.5850, -2.8100, "autorites", "gendarmerie", None),
    ("A-Golfe centre",         47.5700, -2.8000, "obstacle_nav", "ofni", None),
    ("A-Golfe S",              47.5620, -2.7800, "animal_marin", "oiseau", {"health": "alive_injured"}),
    ("A-Golfe SE",             47.5560, -2.7620, "pollution", "dechets", None),
    ("A-Port-Navalo entrée",   47.5480, -2.8480, "obstacle_nav", "conteneur", None),
    # ── Lot B : entre golfe et Belle-Île ──
    ("B-Mor Braz N",           47.5000, -2.9000, "obstacle_nav", "conteneur", None),
    ("B-Quiberon E",           47.4800, -2.9500, "pollution", "hydrocarbures", None),
    ("B-Mor Braz centre",      47.4600, -3.0000, "obstacle_nav", "tronc", None),
    ("B-Quiberon SE",          47.4400, -3.0500, "animal_marin", "mammifere", None),
    ("B-Mor Braz E",           47.4200, -2.9200, "obstacle_nav", "ofni", None),
    ("B-Mor Braz S",           47.4000, -2.9800, "autorites", "douanes", None),
    ("B-Belle-Île NE",         47.3800, -3.0800, "obstacle_nav", "conteneur", None),
    ("B-Houat S",              47.3600, -2.9000, "pollution", "dechets", None),
    ("B-La Teignouse",         47.3400, -3.0200, "obstacle_nav", "tronc", None),
    ("B-Hoedic N",             47.3800, -2.8500, "animal_marin", "oiseau", {"health": "dead_floating"}),
    # ── Lot C : > 20 km des côtes (dont SE de Belle-Île) ──
    ("C-SE Belle-Île 1",       47.0500, -3.0500, "obstacle_nav", "conteneur", None),
    ("C-SE Belle-Île 2",       47.0800, -2.9500, "pollution", "hydrocarbures", None),
    ("C-S Belle-Île",          47.0200, -3.2000, "obstacle_nav", "tronc", None),
    ("C-SSO Belle-Île",        47.0500, -3.3500, "animal_marin", "mammifere", None),
    ("C-SE large 1",           46.9800, -2.8500, "obstacle_nav", "ofni", None),
    ("C-O Belle-Île large",    47.1500, -3.6000, "autorites", "marine_nationale", None),
    ("C-Large S 1",            46.9000, -3.1000, "obstacle_nav", "conteneur", None),
    ("C-Large S 2",            46.8500, -3.4000, "pollution", "dechets", None),
    ("C-Large SO",             47.0000, -3.5500, "obstacle_nav", "tronc", None),
    ("C-Large SE 2",           46.9500, -2.9500, "animal_marin", "oiseau", {"health": "dead_floating"}),
]

ok = err = 0
for name, lat, lng, t, st, extras in LOTS:
    body = {"type": t, "subtype": st, "lat": lat, "lng": lng,
            "description": f"TEST LOT {name} — vérification bande côtière 20 km"}
    if extras:
        body["extras"] = extras
    r = requests.post(f"{BASE}/reports", headers=AH, json=body)
    if r.status_code == 200:
        d = r.json()
        dc = d.get("drift_cone") or {}
        print(f"OK  {name:24s} {d.get('short_id')} cone={'oui' if dc else 'non'} wind_only={dc.get('wind_only')}")
        ok += 1
    else:
        print(f"ERR {name:24s} {r.status_code} {r.text[:90]}")
        err += 1
print(f"\n{ok} créés, {err} erreurs")
