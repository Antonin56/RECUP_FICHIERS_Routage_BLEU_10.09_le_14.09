"""SignalMar — Itér. 130 REVIEW (T1, review from armateur bug report).

Verifies the specific scenarios listed in the review_request:

BUG 1 (Illur) — engine_c on 4 new pairs (different from those already tested):
    - no wrong_side_marks
    - if 'Illur' is concerned, it appears in side_fixed
    - the C track REALLY differs from A's (bug was: side_fixed reported without
      changing the track)

BUG 2 (cardinals) — no cardinal must appear in wrong_side_marks; when it does,
    entries have name, kind ('lateral' | 'cardinal'), dist_m and side_required
    (plain-text FR like 'au sud' / 'à bâbord'), AND a matching warning.

REVERSIBILITY — A→B and B→A must yield exactly-inverse waypoints (6 decimals)
    and identical distance_m, even after side corrections.

NEVER FAILS — engine_c always returns 200, even land arrival / land departure.
    No 422 'Passage impossible'; insufficient legs go into compromised_legs
    with leg_reasons.

DISPLACEMENT WARNING — when engine_c reversed the computation (engine_rules
    .computed_reversed = true) and an endpoint moved, exposes start_snapped
    (NOT end_snapped) and the warning talks about the DEPARTURE.

FROZEN engines A/B — never expose engine_rules, leg_reasons, leg_margin_m,
    low_margin_legs, side_fixed, wrong_side_marks, endpoint_cardinals;
    two identical engine_a calls yield the same geometry.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"

# 4 new pairs (different from those in test_iter130_engine_c_marks.py)
NEW_PAIRS = [
    ({"lat": 47.5620, "lng": -2.7900}, {"lat": 47.6165, "lng": -2.8230}),
    ({"lat": 47.5800, "lng": -2.8760}, {"lat": 47.5940, "lng": -2.7830}),
    ({"lat": 47.5760, "lng": -2.8060}, {"lat": 47.6010, "lng": -2.7960}),
    ({"lat": 47.5455, "lng": -2.9185}, {"lat": 47.5880, "lng": -2.7570}),
]

VANNES_LAND = {"lat": 47.6559, "lng": -2.7603}   # start on land
GOLFE_TARGET = {"lat": 47.5614, "lng": -2.87473}  # sea

SIDE_TEXTS_LATERAL = {"à bâbord", "à tribord"}
SIDE_TEXTS_CARDINAL = {"au nord", "au sud", "à l'est", "à l'ouest"}


# ── Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json",
                      "X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": ADMIN_PHONE})
    assert r.status_code == 200, r.text[:200]
    r = s.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": ADMIN_PHONE, "code": OTP_CODE,
              "pseudo": f"QAr130_{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, r.text[:200]
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


def _compute(session, start, end, engine_id="engine_c") -> dict:
    r = session.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": start, "end": end, "draft_m": 1.0, "depth_margin_m": 0.5,
              "use_tide": False, "engine_id": engine_id},
        timeout=180,
    )
    assert r.status_code == 200, f"{engine_id} {start}→{end}: {r.status_code} {r.text[:400]}"
    return r.json()


def _geo(res):
    return [(round(w["lat"], 6), round(w["lng"], 6)) for w in res["waypoints"]]


# ── BUG 1 : Illur / wrong_side_marks empty on 4 new pairs ─────────────────
@pytest.mark.parametrize("start,end", NEW_PAIRS)
def test_new_pairs_no_wrong_side_marks(admin, start, end):
    """engine_c never leaves marks on the wrong side on the new 4 pairs."""
    res = _compute(admin, start, end)
    wrong = res.get("wrong_side_marks") or []
    assert not wrong, f"{start}→{end}: wrong_side_marks={wrong}"


@pytest.mark.parametrize("start,end", NEW_PAIRS)
def test_new_pairs_track_differs_from_engine_a_when_side_fixed(admin, start, end):
    """When engine_c reports a side_fixed correction, its track must ACTUALLY
    differ from engine_a's on the same trip (real fix, not lip service)."""
    c = _compute(admin, start, end, "engine_c")
    a = _compute(admin, start, end, "engine_a")
    fixed = c.get("side_fixed") or []
    if fixed:
        assert _geo(c) != _geo(a), (
            f"side_fixed={fixed} annoncé pour {start}→{end} mais tracé identique"
            f" à engine_a ({len(_geo(c))} wpts)")


# ── BUG 2 : cardinals never in wrong_side_marks; shape checks ──────────────
@pytest.mark.parametrize("start,end", NEW_PAIRS)
def test_no_cardinal_in_wrong_side_marks(admin, start, end):
    res = _compute(admin, start, end)
    wrong = res.get("wrong_side_marks") or []
    cards = [v for v in wrong if v.get("kind") == "cardinal"]
    assert not cards, f"{start}→{end}: cardinales dans wrong_side_marks: {cards}"


@pytest.mark.parametrize("start,end", NEW_PAIRS)
def test_wrong_side_shape_and_matching_warning(admin, start, end):
    """When wrong_side_marks is not empty, each entry has name, kind, dist_m,
    side_required in plain FR, AND a matching warning is present."""
    res = _compute(admin, start, end)
    wrong = res.get("wrong_side_marks") or []
    if not wrong:
        pytest.skip("wrong_side_marks vide (comportement attendu)")
    warnings = " ".join(res.get("warnings") or [])
    for v in wrong:
        assert isinstance(v.get("name"), str) and v["name"]
        assert v.get("kind") in {"lateral", "cardinal"}
        assert isinstance(v.get("dist_m"), (int, float))
        sr = v.get("side_required")
        assert isinstance(sr, str) and sr
        allowed = SIDE_TEXTS_LATERAL if v["kind"] == "lateral" else SIDE_TEXTS_CARDINAL
        assert sr in allowed, f"side_required={sr!r} pas en clair (allowed={allowed})"
        assert v["name"] in warnings, (
            f"aucun avertissement ne mentionne « {v['name']} » : {warnings[:400]}")


# ── REVERSIBILITY on the 4 new pairs ───────────────────────────────────────
@pytest.mark.parametrize("start,end", NEW_PAIRS)
def test_reversibility_new_pairs(admin, start, end):
    fwd = _compute(admin, start, end)
    bwd = _compute(admin, end, start)
    g1 = _geo(fwd)
    g2 = list(reversed(_geo(bwd)))
    assert g1 == g2, (
        f"{start}→{end} : géométrie non réversible "
        f"({len(g1)} vs {len(g2)} points)")
    assert abs(fwd.get("distance_m", 0) - bwd.get("distance_m", 0)) < 1.0, (
        f"distance_m diffère fwd={fwd.get('distance_m')} bwd={bwd.get('distance_m')}")


# ── NEVER FAILS — land start / land end ────────────────────────────────────
def test_engine_c_never_fails_land_arrival(admin):
    res = _compute(admin, {"lat": 47.5580, "lng": -2.8560}, VANNES_LAND)
    assert res.get("waypoints"), "waypoints vides"
    # Insufficient legs go into compromised_legs with leg_reasons
    if res.get("compromised_legs"):
        reasons = res.get("leg_reasons") or {}
        for i in res["compromised_legs"]:
            assert str(i) in reasons, f"leg_reasons manque pour idx {i}"
            assert reasons[str(i)] in {"shallow", "low_margin"}


def test_engine_c_never_fails_land_departure(admin):
    res = _compute(admin, VANNES_LAND, GOLFE_TARGET)
    assert res.get("waypoints"), "waypoints vides"


# ── DISPLACEMENT WARNING — reversed computation, moved START ───────────────
def test_reversed_moved_endpoint_is_reported_as_departure(admin):
    """Cas armateur du 03/08 : départ à terre à Vannes → mer.
    Le moteur calcule mer→terre en interne (computed_reversed=true) et déplace
    ce qui, dans le sens interne, est l'ARRIVÉE. Après retournement, la
    réponse doit exposer start_snapped (PAS end_snapped) et l'avertissement
    doit parler du DÉPART."""
    res = _compute(admin, VANNES_LAND, GOLFE_TARGET)
    er = res.get("engine_rules") or {}
    if not er.get("computed_reversed"):
        pytest.skip("computed_reversed=false — pas le cas attendu ici")
    if "start_snapped" not in res and "end_snapped" not in res:
        pytest.skip("aucune extrémité déplacée (pas la config attendue)")
    assert "start_snapped" in res, (
        f"start_snapped attendu (départ à terre), got keys={list(res.keys())[:20]}")
    assert "end_snapped" not in res, "end_snapped ne doit PAS être exposé"
    warnings = " ".join(res.get("warnings") or []).lower()
    assert "départ" in warnings and "arrivée déplacée" not in warnings, (
        f"warnings doivent parler du DÉPART déplacé, pas de l'arrivée : {warnings[:400]}")


# ── FROZEN ENGINES A / B ───────────────────────────────────────────────────
_FORBIDDEN_FIELDS = ("engine_rules", "leg_reasons", "leg_margin_m",
                     "low_margin_legs", "side_fixed", "wrong_side_marks",
                     "endpoint_cardinals")


@pytest.mark.parametrize("engine_id", ["engine_a", "engine_b"])
def test_frozen_engines_have_no_v3_fields(admin, engine_id):
    start, end = NEW_PAIRS[0]
    res = _compute(admin, start, end, engine_id)
    for key in _FORBIDDEN_FIELDS:
        assert key not in res, f"{engine_id} expose interdit : {key}"


def test_engine_a_is_deterministic(admin):
    start, end = NEW_PAIRS[0]
    a1 = _compute(admin, start, end, "engine_a")
    a2 = _compute(admin, start, end, "engine_a")
    assert _geo(a1) == _geo(a2), "engine_a n'est pas déterministe"
