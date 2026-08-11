"""SignalMar — Itér. 134 (11/08/2026) : MOTEUR E (signalmar.v5) — côté
ABSOLU du balisage + arrivée jamais tronquée. Moteur D FIGÉ le 11.08.26.

Consignes armateur :
* « encore des ratées de balises » → couple très écarté du chenal de Vannes
  (rouge 47.612655,-2.828126, gap 245 m) recoupé à 139 m dans 4 m d'eau ;
* « le moteur refuse l'arrivée au Crouesty, balisage clair » → l'entrée du
  port était SCELLÉE par les zones de balises (faux couples des chenaux en
  coude + rayons fixes 60-200 m dans un chenal balisé tous les 50-100 m) ;
* « JAMAIS d'exception de terrain » → uniquement des règles universelles :
  couples RÉCIPROQUES, plafond de DENSITÉ, balisage PRIME sur le MNT pour
  finir la route (tronçons rouges).
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from core.seamarks import (  # noqa: E402
    ISOLATED_SIDE_BATHY, SIDE_ABSOLUTE, get_seamarks,
)

ILLUR = (47.5827118, -2.7951316)
MLNG_ILLUR = 111_320.0 * math.cos(math.radians(ILLUR[0]))


@pytest.fixture(scope="module")
def sm():
    idx = get_seamarks()
    assert idx is not None
    return idx


@pytest.fixture(scope="module")
def eng():
    from core.routing_engines.algos.signalmar_v5 import SignalmarV5
    return SignalmarV5()


def _closest(pts, lat, lng, mlng):
    from core.routing_engines.algos.signalmar_v2.standoff import _closest_on
    return _closest_on(pts, lat, lng, mlng)


def _mark_at(sm, lat, lng):
    return min((m for m in sm.marks if m.get("kind") == "lateral"),
               key=lambda m: (m["lat"] - lat) ** 2 + (m["lng"] - lng) ** 2)


# ── 1. Enregistrement + gel des moteurs précédents ────────────────────────
def test_v5_enregistre_et_geles_intacts():
    from core.routing_engines.algos import ALGO_REGISTRY
    assert "signalmar.v5" in ALGO_REGISTRY
    for k, cls in [("signalmar.v2", "SignalmarV2"), ("signalmar.v4", "SignalmarV4")]:
        assert type(ALGO_REGISTRY[k]).__name__ == cls


# ── 2. Couples RÉCIPROQUES (mode E) — faux couples des coudes supprimés ──
def test_couples_reciproques_au_crouesty(sm):
    huit = _mark_at(sm, 47.54011, -2.90423)      # rouge « 8 »
    no5 = _mark_at(sm, 47.54004, -2.90301)       # verte « No5 »
    coude = _mark_at(sm, 47.54168, -2.90101)     # verte anonyme du coude
    tok = SIDE_ABSOLUTE.set(True)
    try:
        assert sm._pair_of(huit) is no5, "8↔No5 : vraie porte, réciproque"
        assert sm._pair_of(no5) is huit
        assert sm._pair_of(coude) is None, (
            "la verte du coude ne doit PLUS s'apparier à la rouge 8 (290 m "
            "EN AMONT) — c'était le faux couple qui scellait l'entrée")
    finally:
        SIDE_ABSOLUTE.reset(tok)
    # Mode gelé (B/D) : appariement historique inchangé (plus proche opposée).
    assert sm._pair_of(coude) is huit


# ── 3. Bug « Grand Mouton » : couple écarté, mauvais côté à 139 m ────────
def test_couple_ecarte_chenal_vannes_respecte(eng):
    red = (47.612655, -2.828126)
    mlng = 111_320.0 * math.cos(math.radians(red[0]))
    r = eng.compute_auto(47.53214474552446, -2.92678544441799,
                         47.615738117406266, -2.8154603141514327,
                         1.5, 0.5, 10.0)
    pts = [(w["lat"], w["lng"]) for w in r["waypoints"]]
    d, _, p = _closest(pts, *red, mlng)
    names = [v.get("name") for v in (r.get("wrong_side_marks") or [])]
    assert not names, f"aucune balise du mauvais côté attendue, obtenu {names}"
    if d < 200.0:
        sm = get_seamarks()
        m = _mark_at(sm, *red)
        t1 = ISOLATED_SIDE_BATHY.set(True); t2 = SIDE_ABSOLUTE.set(True)
        try:
            de, dn = sm.mark_dir_confident(m)
        finally:
            SIDE_ABSOLUTE.reset(t2); ISOLATED_SIDE_BATHY.reset(t1)
        u = (dn, -de)   # rouge → passage à TRIBORD de D
        ve = (p[1] - red[1]) * mlng
        vn = (p[0] - red[0]) * 110_574.0
        assert ve * u[0] + vn * u[1] > 0, "la rouge doit être laissée à bâbord"


# ── 4. Bug « Crouesty » : l'arrivée n'est JAMAIS refusée ─────────────────
def test_arrivee_crouesty_atteinte(eng):
    end = (47.541667984725095, -2.898089118531395)
    r = eng.compute_auto(47.600792170105066, -2.8566121456947395,
                         end[0], end[1], 1.0, 0.5, 10.0)
    assert not r.get("end_snapped"), "l'arrivée ne doit plus être « déplacée »"
    last = r["waypoints"][-1]
    mlng = 111_320.0 * math.cos(math.radians(end[0]))
    d_end = math.hypot((last["lat"] - end[0]) * 110_574.0,
                       (last["lng"] - end[1]) * mlng)
    assert d_end < 30.0, f"dernier waypoint à {d_end:.0f} m du point demandé"
    # Le chenal découvre au ZH : le tronçon final DOIT être marqué à risque.
    assert r.get("compromised_legs") and r.get("risk") is True
    names = [v.get("name") for v in (r.get("wrong_side_marks") or [])]
    assert not names, f"suivi du chenal balisé : aucun mauvais côté ({names})"


# ── 5. Non-régression Illur (acquis du Moteur D) ─────────────────────────
def test_illur_au_nord_dans_les_deux_sens(eng):
    for args in [(47.5455, -2.9185, 47.5870, -2.7820),
                 (47.5870, -2.7820, 47.5455, -2.9185)]:
        r = eng.compute_auto(*args, 1.5, 0.5, 10.0)
        pts = [(w["lat"], w["lng"]) for w in r["waypoints"]]
        d, _, p = _closest(pts, *ILLUR, MLNG_ILLUR)
        if d > 600.0:
            continue
        assert p[0] > ILLUR[0], "la route doit passer au NORD d'Illur"
        names = [v.get("name") for v in (r.get("wrong_side_marks") or [])]
        assert "Illur" not in names
