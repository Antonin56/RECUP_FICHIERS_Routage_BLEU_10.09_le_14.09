"""Iteration 59 — Public /api/public/report/{code} endpoint tests.

Feature: anonymized public preview served without auth for the web share
page /s/[CODE]. Validates:
- 200 + expected fields (rounded coords, excerpt<=103, author_pseudo, no leak).
- 404 for unknown code.
- 422 for too-short code.
- Case-insensitivity (lowercase code accepted).
- No auth header required.
"""
import os
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_USER_ID = "user_0b6070a69154"


@pytest.fixture(scope="module")
def known_code():
    """23/07/2026 — l'ancien code en dur (EWYQ6PGU) a été purgé le 10/07 :
    le test crée SON propre signalement (admin, en mer) puis le supprime."""
    import sys
    sys.path.insert(0, "/app/backend")
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    from core.auth import make_jwt
    h = {"Authorization": f"Bearer {make_jwt(ADMIN_USER_ID)}", **QA}
    r = requests.post(f"{BASE_URL}/api/reports", headers=h, json={
        "type": "obstacle_nav",
        "lat": 47.4512, "lng": -3.0521,
        "description": ("TEST_iter59 — conteneur semi-immergé dérivant au "
                        "large, danger sérieux pour la navigation de nuit, "
                        "vu à 14h30 par mer calme, dérive vers le sud-est."),
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    rid = r.json().get("id") or r.json().get("report_id")
    d = requests.get(f"{BASE_URL}/api/reports/{rid}", headers=h, timeout=15).json()
    yield d["short_id"]
    requests.delete(f"{BASE_URL}/api/reports/{rid}", headers=h, timeout=15)


@pytest.fixture
def bare_session():
    """A session that DOES NOT carry auth headers (verifies public access)."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestPublicReportPreview:
    """GET /api/public/report/{code} — no auth."""

    def test_known_code_returns_200_and_expected_shape(self, bare_session, known_code):
        r = bare_session.get(f"{BASE_URL}/api/public/report/{known_code}")
        assert r.status_code == 200, r.text
        data = r.json()
        # Required fields
        expected_keys = {
            "short_id", "type", "subtype", "approx_lat", "approx_lng",
            "description_excerpt", "created_at", "confirm_count",
            "author_pseudo", "status", "photo",
        }
        assert expected_keys.issubset(data.keys()), (
            f"Missing keys: {expected_keys - set(data.keys())}"
        )
        assert data["short_id"] == known_code

    def test_approx_coords_rounded_to_one_decimal(self, bare_session, known_code):
        r = bare_session.get(f"{BASE_URL}/api/public/report/{known_code}")
        assert r.status_code == 200
        d = r.json()
        # 0.1° rounding → the number times 10 must be an integer
        assert round(d["approx_lat"] * 10) == d["approx_lat"] * 10, (
            f"approx_lat not 0.1° rounded: {d['approx_lat']}"
        )
        assert round(d["approx_lng"] * 10) == d["approx_lng"] * 10, (
            f"approx_lng not 0.1° rounded: {d['approx_lng']}"
        )
        # Sanity: not full precision leak — at most 1 digit after the dot.
        lat_s = f"{d['approx_lat']:.10f}".rstrip("0").rstrip(".")
        lng_s = f"{d['approx_lng']:.10f}".rstrip("0").rstrip(".")
        for s in (lat_s, lng_s):
            if "." in s:
                assert len(s.split(".")[1]) <= 1, f"precision leak: {s}"

    def test_excerpt_length_capped_and_no_real_name(self, bare_session, known_code):
        r = bare_session.get(f"{BASE_URL}/api/public/report/{known_code}")
        d = r.json()
        excerpt = d["description_excerpt"]
        assert isinstance(excerpt, str)
        # 100 chars + "..." = 103 max
        assert len(excerpt) <= 103, f"excerpt too long: {len(excerpt)}"
        # Pseudo must exist, and there must be NO 'author_name' or 'name' key
        assert d.get("author_pseudo"), "author_pseudo missing"
        assert "author_name" not in d, "real name leaked via author_name"
        assert "name" not in d, "real name leaked via name"
        assert "author_id" not in d, "author_id leaked"

    def test_no_auth_header_needed(self, bare_session, known_code):
        # Explicitly assert we send NO Authorization header.
        assert "Authorization" not in bare_session.headers
        r = bare_session.get(f"{BASE_URL}/api/public/report/{known_code}")
        assert r.status_code == 200

    def test_case_insensitive_lowercase_works(self, bare_session, known_code):
        r = bare_session.get(
            f"{BASE_URL}/api/public/report/{known_code.lower()}"
        )
        assert r.status_code == 200, r.text
        assert r.json()["short_id"] == known_code

    def test_unknown_code_returns_404_with_french_detail(self, bare_session):
        r = bare_session.get(f"{BASE_URL}/api/public/report/NOPE9999")
        assert r.status_code == 404
        assert r.json().get("detail") == "Aucun signalement avec ce code."

    def test_too_short_code_returns_422(self, bare_session):
        r = bare_session.get(f"{BASE_URL}/api/public/report/ab")
        assert r.status_code == 422

    def test_status_is_one_of_expected_values(self, bare_session, known_code):
        r = bare_session.get(f"{BASE_URL}/api/public/report/{known_code}")
        assert r.json()["status"] in ("active", "ended", "expired")
