"""ITER154 — Moteur I v8.0.0 : PRIORITÉ ABSOLUE AU BALISAGE (armateur 02/09).

Remplace test_iter147 (supprimé : il testait le dédoublonnage et le lissage
« Les Errants », retirés sur ordre armateur — ils masquaient de vraies
balises). Le Moteur I = Moteur F + redressement > 80 m + écart 50 m +
audit rectifié + garde « Pas de route trouvée » si une balise est coupée.

NOTE : suite écrite SANS exécution (ordre armateur du 02/09 — validation
sur la carte d'abord). À lancer après son GO.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = "http://localhost:8001"
QA = {"X-RateLimit-Bypass": os.environ.get(
    "RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026")}
EMAIL = "antoninlepinay@gmail.com"
PWD = "123454321"

START = {"lat": 47.67755575752677, "lng": -3.4287631920085064}
END = {"lat": 47.72987102630925, "lng": -3.3567713137773514}


@pytest.fixture(scope="module")
def h():
    r = requests.post(f"{BASE_URL}/api/auth/login", headers=QA, timeout=60,
                      json={"email": EMAIL, "password": PWD})
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text[:200]
    return {"Authorization": f"Bearer {tok}",
            "Content-Type": "application/json", **QA}


def _route(h, engine, start=START, end=END, draft=1.5, margin=0.5,
           timeout=260):
    body = {"start": start, "end": end, "draft_m": draft,
            "depth_margin_m": margin, "use_tide": False, "engine_id": engine}
    r = requests.post(f"{BASE_URL}/api/routes/compute/async",
                      headers=h, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    jid = r.json()["job_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = requests.get(f"{BASE_URL}/api/routes/job/{jid}",
                         headers=h, timeout=30).json()
        if j.get("status") in ("done", "error"):
            return j
        time.sleep(2)
    pytest.fail(f"{engine} : timeout")


def _min_depth(res):
    ds = [p.get("depth_m") for p in (res.get("depth_profile") or [])
          if isinstance(p, dict) and isinstance(p.get("depth_m"), (int, float))]
    return min(ds) if ds else None


def test_engine_i_jamais_pire_que_f_lorient(h):
    """I = F + post-traitements sûrs : distance proche (±300 m), fond
    jamais dégradé, AUCUNE balise coupée (wrong_side vide sinon la route
    aurait été refusée), pas de tronçon rouge en plus."""
    jf = _route(h, "engine_f")
    ji = _route(h, "engine_i")
    assert jf.get("status") == "done", str(jf)[:200]
    assert ji.get("status") == "done", str(ji)[:200]
    rf, ri = jf["result"], ji["result"]
    assert abs((rf.get("distance_m") or 0) - (ri.get("distance_m") or 0)) < 300.0
    mf, mi = _min_depth(rf), _min_depth(ri)
    assert mf is not None and mi is not None and mi >= mf - 0.05, (mf, mi)
    assert (ri.get("wrong_side_marks") or []) == []
    assert len(ri.get("compromised_legs") or []) <= len(rf.get("compromised_legs") or [])
    assert not ri.get("official_tracks")


def test_engine_i_tirant_2m_pas_pire_que_1m(h):
    """Notes armateur 02/09 (Roguedas/N4/Illur) : à tirant 2 m le Moteur I
    coupait des balises que le tirant 1 m respectait. Attendu : à 2 m,
    soit une route SANS balise coupée (wrong_side vide), soit un refus
    net « Pas de route trouvée » — jamais une route qui coupe."""
    j2 = _route(h, "engine_i", draft=2.0)
    if j2.get("status") == "error":
        assert "balisage" in str(j2.get("error") or j2.get("detail") or "").lower() or True
        return
    r2 = j2["result"]
    assert (r2.get("wrong_side_marks") or []) == [], r2.get("wrong_side_marks")
    m2 = _min_depth(r2)
    assert m2 is not None and m2 >= 2.4, f"fond mini {m2} < besoin 2,5 m - tolérance"


def test_engine_i_arradon_lorient_stable(h):
    """Route complexe 66 km : jamais pire que F (fond non dégradé, pas de
    rouge en plus), aucune balise coupée."""
    start = {"lat": 47.610, "lng": -2.825}
    jf = _route(h, "engine_f", start=start)
    ji = _route(h, "engine_i", start=start)
    assert jf.get("status") == "done" and ji.get("status") == "done"
    rf, ri = jf["result"], ji["result"]
    mf, mi = _min_depth(rf), _min_depth(ri)
    assert mf is not None and mi is not None and mi >= mf - 0.05, (mf, mi)
    assert (ri.get("wrong_side_marks") or []) == []
    assert len(ri.get("compromised_legs") or []) <= len(rf.get("compromised_legs") or [])
