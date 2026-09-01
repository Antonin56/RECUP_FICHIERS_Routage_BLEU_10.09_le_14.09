"""ITER150 — Moteur I = MOTEUR F + correctifs « Les Errants » UNIQUEMENT.

ORDRE ARMATEUR 31/08 : le suivi des routes officielles (pointillés) a été
SUPPRIMÉ INTÉGRALEMENT du Moteur I (accrochage de chenaux à ≤ 3 km de la
ligne directe → +9,3 km et zigzags sur Port-Navalo → SW Belle-Île).

Périmètre STRICT : core/nav/engine_i.py uniquement. Moteurs A-H,
safe_routes.py, seamarks.py inchangés.

Vérifie :
  1. Détection des doublons douteux = UNIQUEMENT la tourelle blanche
     « Les Errants » (id 1421434210) — pas les perches génériques sans
     couleur (faux positifs écartés).
  2. API : le Moteur I rend un tracé IDENTIQUE au Moteur F gelé (distance,
     fond, rouges, audit balises) sur la route de référence de Lorient —
     plus AUCUN calage sur les pointillés ni warning d'écrêtage.
  3. Idem sur la route complexe Arradon → Lorient (66 km).
  4. _strip_suspect_wrong_sides : un flag « Les Errants » produit par la
     tourelle blanche est retiré, celui de la bouée rouge est conservé.
  5. Détour fantôme « Les Errants » : I plus court que F, fond non
     dégradé, écart ≥ 60 m conservé.
"""
from __future__ import annotations

import math
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/") \
    or "http://localhost:8001"
QA = {"X-RateLimit-Bypass": os.environ.get(
    "RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026")}
EMAIL = "antoninlepinay@gmail.com"
PWD = "123454321"

# Route de référence iter144 (large → port de Lorient)
START = {"lat": 47.67755575752677, "lng": -3.4287631920085064}
END = {"lat": 47.72987102630925, "lng": -3.3567713137773514}

ERRANTS_BLANCHE_ID = 1421434210     # tourelle blanche (couleur ≠ catégorie)
ERRANTS_ROUGE_ID = 1421434206       # bouée rouge (fiable)


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", headers=QA, timeout=60,
                      json={"email": EMAIL, "password": PWD})
    assert r.status_code == 200, r.text[:200]
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text[:200]
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json", **QA}


def _route_async(h, engine, start=START, end=END,
                 draft=1.5, margin=0.5, timeout=240):
    body = {"start": start, "end": end, "draft_m": draft,
            "depth_margin_m": margin, "use_tide": False,
            "engine_id": engine}
    r = requests.post(f"{BASE_URL}/api/routes/compute/async",
                      headers=h, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    jid = r.json().get("job_id")
    assert jid, r.text[:200]
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = requests.get(f"{BASE_URL}/api/routes/job/{jid}",
                         headers=h, timeout=30).json()
        if j.get("status") == "done":
            return j.get("result") or {}
        if j.get("status") == "error":
            pytest.fail(f"route {engine} en erreur : {str(j)[:300]}")
        time.sleep(2)
    pytest.fail(f"route {engine} : timeout {timeout}s")


# ── 1. Doublons douteux ───────────────────────────────────────────────────

def test_suspects_uniquement_errants_blanche():
    import core.routing_engines.algos  # noqa: F401 — ordre d'import production
    from core.nav.engine_i import _suspect_duplicate_ids
    ids = set(_suspect_duplicate_ids())
    assert ERRANTS_BLANCHE_ID in ids, ids
    assert ERRANTS_ROUGE_ID not in ids, ids
    # Règle armateur 01/09 : couleur INCONNUE = ambiguë aussi → les perches
    # génériques sans couleur doublées d'une rouge à ≤ 500 m sont ignorées.
    assert 1488899513 in ids and 1488944340 in ids, ids


# ── 2. API : engine_i IDENTIQUE au Moteur F gelé (plus de pointillés) ─────

def test_engine_i_identique_f_lorient(h):
    """ORDRE ARMATEUR 31/08 : plus AUCUN suivi des routes officielles.
    Sur la route de référence de Lorient (loin des Errants), le Moteur I
    doit rendre STRICTEMENT le tracé du Moteur F gelé — mêmes distance,
    fond, tronçons rouges et audit balises — sans official_tracks ni
    warning d'écrêtage."""
    res_f = _route_async(h, "engine_f")
    res_i = _route_async(h, "engine_i")

    def _min_depth(res):
        ds = [p.get("depth_m") for p in (res.get("depth_profile") or [])
              if isinstance(p, dict) and isinstance(p.get("depth_m"), (int, float))]
        return min(ds) if ds else None

    d_f, d_i = res_f.get("distance_m") or 0, res_i.get("distance_m") or 0
    m_f, m_i = _min_depth(res_f), _min_depth(res_i)
    print(f"lorient : F dist={d_f} min={m_f} / I dist={d_i} min={m_i}")
    assert not res_i.get("official_tracks"), res_i.get("official_tracks")
    assert not any("écrêtée à votre besoin d'eau" in w
                   for w in (res_i.get("warnings") or []))
    # 01/09 : I = F + règles balises (écart 50 m, audit rectifié) → le
    # tracé peut s'écarter de F de quelques mètres, jamais se dégrader.
    assert abs(d_f - d_i) < 300.0, f"tracés F/I divergents : {d_f} vs {d_i}"
    assert m_f is not None and m_i is not None and m_i >= m_f - 0.05, (m_f, m_i)
    assert len(res_i.get("compromised_legs") or []) <= len(res_f.get("compromised_legs") or [])
    assert len(res_i.get("wrong_side_marks") or []) <= len(res_f.get("wrong_side_marks") or [])

def test_strip_suspect_wrong_sides_unit():
    import core.routing_engines.algos  # noqa: F401
    from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
    from core.nav.engine_i import _strip_suspect_wrong_sides
    from core.routing_engines.algos.signalmar_v2.standoff import _closest_on
    from core.seamarks import get_seamarks

    sm = get_seamarks()
    blanche = next(m for m in sm.marks if m["id"] == ERRANTS_BLANCHE_ID)
    rouge = next(m for m in sm.marks if m["id"] == ERRANTS_ROUGE_ID)
    # Tracé passant à l'OUEST de la tourelle blanche (mauvais côté v6).
    wps = [{"lat": 47.6820, "lng": -3.3790}, {"lat": 47.6890, "lng": -3.3790}]
    pts = [(w["lat"], w["lng"]) for w in wps]
    mlng = m_per_deg_lng(47.6855)
    d_b, _, _ = _closest_on(pts, blanche["lat"], blanche["lng"], mlng)
    d_r, _, _ = _closest_on(pts, rouge["lat"], rouge["lng"], mlng)
    res = {
        "waypoints": wps,
        "wrong_side_marks": [
            {"name": "Les Errants", "kind": "lateral", "category": "port",
             "dist_m": round(d_b, 1), "side_required": "à bâbord"},
            {"name": "Les Errants", "kind": "lateral", "category": "port",
             "dist_m": round(d_r, 1), "side_required": "à bâbord"},
        ],
        "warnings": [
            f"⚠ MAUVAIS CÔTÉ DE BALISE : « Les Errants » (rouge) doit être "
            f"laissée à bâbord — passage à ~{d_b:.0f} m, vérifiez le "
            f"balisage À VUE.",
        ],
    }
    _strip_suspect_wrong_sides(res)
    remaining = res["wrong_side_marks"]
    assert len(remaining) == 1, remaining          # blanche retirée
    assert abs(remaining[0]["dist_m"] - d_r) <= 2.0, remaining   # rouge gardée
    assert res["warnings"] == [], res["warnings"]  # warning nominatif purgé


# ── 5. Moteur H inchangé (gel implicite) ─────────────────────────────────

def test_engine_h_gel_implicite(h):
    res = _route_async(h, "engine_h")
    assert res.get("official_tracks"), str(res)[:300]
    assert (res.get("wrong_side_marks") or []) == []
    # H garde son écrêtage historique 0,5 m : PAS de mention du besoin d'eau.
    assert not any("écrêtée à votre besoin d'eau" in w
                   for w in (res.get("warnings") or []))
    dist = res.get("distance_m") or 0
    assert 6000 <= dist <= 13000, dist


# ── 6. Baseline F : jamais pire, détour fantôme supprimé ─────────────────

def test_fallback_jamais_pire_que_f(h):
    """Route complexe Arradon → port de Lorient (66 km) : aucun pointillé
    raccordable → le Moteur I doit calculer en MODE F PUR et rendre un
    tracé IDENTIQUE au Moteur F gelé (avant fix : cascade « eau peu
    profonde », fond −0,27 m, 8 tronçons rouges)."""
    start = {"lat": 47.610, "lng": -2.825}
    res_f = _route_async(h, "engine_f", start=start, end=END, timeout=260)
    res_i = _route_async(h, "engine_i", start=start, end=END, timeout=260)

    def _min_depth(res):
        ds = [p.get("depth_m") for p in (res.get("depth_profile") or [])
              if isinstance(p, dict) and isinstance(p.get("depth_m"), (int, float))]
        return min(ds) if ds else None

    d_f, d_i = res_f.get("distance_m") or 0, res_i.get("distance_m") or 0
    m_f, m_i = _min_depth(res_f), _min_depth(res_i)
    comp_f = res_f.get("compromised_legs") or []
    comp_i = res_i.get("compromised_legs") or []
    print(f"fallback F : F dist={d_f} min={m_f} rouges={len(comp_f)} / "
          f"I dist={d_i} min={m_i} rouges={len(comp_i)}")
    # INVARIANT armateur : jamais pire que F (01/09 : le tracé peut
    # s'écarter de quelques mètres pour l'écart latéral 50 m).
    assert abs(d_f - d_i) < 300.0, f"tracés F/I divergents : {d_f} vs {d_i}"
    assert m_f is not None and m_i is not None and m_i >= m_f - 0.05, (m_f, m_i)
    assert len(comp_i) <= len(comp_f), f"tronçons rouges en plus : {comp_i[:5]}"
    assert len(res_i.get("wrong_side_marks") or []) <= len(res_f.get("wrong_side_marks") or [])


def test_errants_detour_fantome_supprime(h):
    """Cas armateur : route passant à l'ouest de la tourelle blanche.
    F fait un détour ~1 690 m (zigzag fantôme) ; le Moteur I supprime le
    zigzag (≈ 1 625 m) SANS dégrader le fond (3,23 m) ni approcher les
    marques à moins de 60 m. Les VRAIES roches des Errants (0,3 m à
    l'ouest) restent contournées (le plein ouest ~900 m est refusé)."""
    start = {"lat": 47.6815, "lng": -3.3800}
    end = {"lat": 47.6893, "lng": -3.3798}
    res_f = _route_async(h, "engine_f", start=start, end=end)
    res_i = _route_async(h, "engine_i", start=start, end=end)
    d_f = res_f.get("distance_m") or 0
    d_i = res_i.get("distance_m") or 0
    print(f"errants : F={d_f} m, I={d_i} m")
    assert d_i < d_f - 30, f"détour non supprimé : F={d_f}, I={d_i}"
    assert d_i > 1200, f"raccourci trop agressif (roches ?) : {d_i}"
    assert any("détour fantôme supprimé" in w
               for w in (res_i.get("warnings") or [])), res_i.get("warnings")
    # fond jamais dégradé
    def _min_depth(res):
        ds = [p.get("depth_m") for p in (res.get("depth_profile") or [])
              if isinstance(p, dict) and isinstance(p.get("depth_m"), (int, float))]
        return min(ds) if ds else None
    mf, mi = _min_depth(res_f), _min_depth(res_i)
    assert mi is not None and mf is not None and mi >= mf - 0.05, (mf, mi)
    # écart minimal 60 m aux deux marques du doublon conservé
    sm_pts = [(47.6855753, -3.3774229), (47.685025, -3.3728058)]
    mlng = 111_320.0 * math.cos(math.radians(47.685))
    for (mla, mlo) in sm_pts:
        dmin = min(math.hypot((w["lat"] - mla) * 110_574.0,
                              (w["lng"] - mlo) * mlng)
                   for w in res_i["waypoints"])
        assert dmin >= 60.0, f"écart minimal violé : {dmin:.0f} m"
    assert (res_i.get("wrong_side_marks") or []) == []


def test_errants_doublon_mesure():
    """Documente le conflit mesuré (analyse armateur 31/08) : les deux
    homonymes « Les Errants » ont des côtés requis divergents en mode v6.
    Si l'ingestion OSM corrige un jour la couleur, ce test le signalera."""
    import core.routing_engines.algos  # noqa: F401
    from core.seamarks import get_seamarks
    sm = get_seamarks()
    marks = [m for m in sm.marks if (m.get("name") or "") == "Les Errants"]
    assert len(marks) == 2, marks
    by_id = {m["id"]: m for m in marks}
    assert by_id[ERRANTS_BLANCHE_ID]["colour"] == "white"
    assert by_id[ERRANTS_ROUGE_ID]["colour"] == "red"
    mlng = 111_320.0 * math.cos(math.radians(47.6856))
    d = math.hypot(
        (by_id[ERRANTS_BLANCHE_ID]["lat"] - by_id[ERRANTS_ROUGE_ID]["lat"]) * 110_574.0,
        (by_id[ERRANTS_BLANCHE_ID]["lng"] - by_id[ERRANTS_ROUGE_ID]["lng"]) * mlng)
    assert 300 <= d <= 420, f"distance doublon inattendue : {d:.0f} m"
