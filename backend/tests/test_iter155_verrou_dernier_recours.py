"""ITER155 — VERROU DERNIER RECOURS pour engine_i.

Le Moteur I doit forcer SIDE_RULES_OPEN=False pendant TOUT son calcul,
même sur un cas qui pousse la cascade API à armer le « dernier recours »
ou le mode « eau peu profonde ». Résultat exigé :
  - soit une route done avec wrong_side_marks == []
  - soit une erreur contenant « Pas de route » / « MAUVAIS CÔTÉ » /
    « non navigable » / « balisage »
  - JAMAIS une route done avec wrong_side_marks non vide.

engine_f (moteur de référence) peut, lui, lever les règles en dernier
recours : c'est le comportement inchangé (test de comparaison purement
informatif — pas d'assertion inversée).
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

# Cas cascade dégradée : arrivée très peu profonde (proposé par l'armateur).
START = {"lat": 47.6800, "lng": -3.4200}
END = {"lat": 47.7065, "lng": -3.3549}
DRAFT = 2.5
MARGIN = 0.5


@pytest.fixture(scope="module")
def h():
    r = requests.post(f"{BASE_URL}/api/auth/login", headers=QA, timeout=60,
                      json={"email": EMAIL, "password": PWD})
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text[:200]
    return {"Authorization": f"Bearer {tok}",
            "Content-Type": "application/json", **QA}


def _route(h, engine, timeout=260):
    body = {"start": START, "end": END, "draft_m": DRAFT,
            "depth_margin_m": MARGIN, "use_tide": False, "engine_id": engine}
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


def _err_msg(j) -> str:
    return str(j.get("error") or j.get("detail") or j.get("message") or "").lower()


def test_engine_i_verrou_dernier_recours_cascade_degradee(h):
    """Le verrou SIDE_RULES_OPEN=False d'engine_i tient même quand la
    cascade API pousserait à ouvrir les règles."""
    j = _route(h, "engine_i")
    st = j.get("status")
    assert st in ("done", "error"), j
    if st == "done":
        r = j["result"]
        wsm = r.get("wrong_side_marks") or []
        assert wsm == [], (
            "engine_i a rendu une route done AVEC wrong_side_marks non "
            f"vide (verrou dernier recours cassé) : {wsm}")
    else:
        msg = _err_msg(j)
        expected = ("pas de route", "mauvais côté", "mauvais cote",
                    "balisage", "non navigable")
        assert any(k in msg for k in expected), (
            f"Erreur inattendue pour engine_i : {msg!r}")


def test_engine_f_comportement_inchange_cascade(h):
    """engine_f peut lever les règles en dernier recours : on vérifie
    juste qu'il RÉPOND (done ou error propre) — pas d'assertion sur le
    contenu (comportement inchangé attendu, non régressé par ITER155)."""
    j = _route(h, "engine_f")
    assert j.get("status") in ("done", "error"), j
