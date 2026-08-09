"""Iteration 19 — Secours category + at-sea seed audit (hotfix).

Validates:
- B1: GET /api/reports returns 30 demo reports, all is_demo=true; 5 random
      coords cross-checked against Open-Meteo Marine to confirm at-sea.
- B2: ≥1 secours/snsm, ≥1 secours/pompiers, ≥1 autorites/*, no autorites/snsm.
- B3: POST /api/reports {type:'secours', subtype:'pompiers'} → 200.
      POST with type:'old_garbage' → 422.
"""
import os
import random
import httpx
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

MAINT = {"email": "antoninlepinay@gmail.com", "password": "123454321"}


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def maint_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=MAINT, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def demo_reports(maint_token):
    r = requests.get(f"{BASE_URL}/api/reports",
                     headers=_hdr(maint_token), timeout=20)
    assert r.status_code == 200, r.text
    return [x for x in r.json() if x.get("is_demo")]


# ----------- B1 ---------------------------------------------------------------
class TestB1DemoSeedAtSea:
    def test_30_demo_reports_returned(self, demo_reports):
        assert len(demo_reports) == 30, f"expected 30 demo reports, got {len(demo_reports)}"

    def test_all_flagged_demo(self, demo_reports):
        assert all(r.get("is_demo") is True for r in demo_reports)

    def test_no_demo_on_hoedic_land(self, demo_reports):
        """Strict bbox check on Hoëdic island core (47.335-47.355 N,
        -2.890 to -2.855 W) — one of the 3 land zones explicitly named
        by the user. Quiberon/Belle-Île can't be reliably checked by
        bbox since the surrounding shallow channels overlap; we rely on
        Open-Meteo (test_random_5_pass_open_meteo) + full audit below.
        """
        HOEDIC = (47.335, 47.355, -2.890, -2.855)
        bad = []
        for r in demo_reports:
            lat, lng = r["lat"], r["lng"]
            la, lb, lo, lh = HOEDIC
            if la <= lat <= lb and lo <= lng <= lh:
                bad.append((r["id"], lat, lng))
        assert not bad, f"demo reports inside Hoëdic land bbox: {bad}"

    def test_all_30_pass_open_meteo(self, demo_reports):
        """Authoritative check — every single demo coord must return
        wave data from Open-Meteo Marine (same geofence the runtime uses).
        """
        bad = []
        with httpx.Client(timeout=15) as cli:
            for r in demo_reports:
                lat = round(r["lat"], 4)
                lng = round(r["lng"], 4)
                try:
                    resp = cli.get(
                        "https://marine-api.open-meteo.com/v1/marine",
                        params={"latitude": lat, "longitude": lng,
                                "hourly": "wave_height", "forecast_days": 1},
                    )
                except Exception as e:
                    pytest.skip(f"Open-Meteo unreachable: {e}")
                if resp.status_code != 200:
                    bad.append((r["id"], lat, lng, f"HTTP {resp.status_code}"))
                    continue
                arr = ((resp.json().get("hourly") or {}).get("wave_height")) or []
                if not any(v is not None for v in arr):
                    bad.append((r["id"], lat, lng, "no wave data"))
        assert not bad, f"non-sea demo coords per Open-Meteo: {bad}"

    def test_random_5_pass_open_meteo(self, demo_reports):
        """Cross-check 5 random coords against Open-Meteo Marine."""
        random.seed(42)
        sample = random.sample(demo_reports, 5)
        with httpx.Client(timeout=10) as cli:
            for r in sample:
                lat = round(r["lat"], 4)
                lng = round(r["lng"], 4)
                resp = cli.get(
                    "https://marine-api.open-meteo.com/v1/marine",
                    params={"latitude": lat, "longitude": lng,
                            "hourly": "wave_height", "forecast_days": 1},
                )
                if resp.status_code != 200:
                    pytest.skip(f"Open-Meteo flaky for {lat},{lng}: {resp.status_code}")
                arr = ((resp.json().get("hourly") or {}).get("wave_height")) or []
                has_wave = any(v is not None for v in arr)
                assert has_wave, f"NOT at sea per Open-Meteo: {lat},{lng}"


# ----------- B2 ---------------------------------------------------------------
class TestB2CategorySplit:
    def test_has_secours_snsm(self, demo_reports):
        snsm = [r for r in demo_reports
                if r["type"] == "secours" and r.get("subtype") == "snsm"]
        assert len(snsm) >= 1, "expected ≥1 secours/snsm in demo seed"

    def test_has_secours_pompiers(self, demo_reports):
        pomp = [r for r in demo_reports
                if r["type"] == "secours" and r.get("subtype") == "pompiers"]
        assert len(pomp) >= 1, "expected ≥1 secours/pompiers in demo seed"

    def test_has_autorites(self, demo_reports):
        au = [r for r in demo_reports if r["type"] == "autorites"]
        assert len(au) >= 1, "expected ≥1 autorites in demo seed"

    def test_no_autorites_snsm(self, demo_reports):
        leak = [r for r in demo_reports
                if r["type"] == "autorites" and r.get("subtype") == "snsm"]
        assert not leak, f"autorites/snsm should have moved to secours/snsm: {leak}"


# ----------- B3 ---------------------------------------------------------------
class TestB3SecoursPostAcceptance:
    def test_post_secours_pompiers_ok(self, maint_token):
        r = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(maint_token),
            json={"type": "secours", "subtype": "pompiers",
                  "lat": 47.45, "lng": -3.05,
                  "description": "TEST_iter19 secours pompiers"},
            timeout=20,
        )
        assert r.status_code == 200, f"secours/pompiers rejected: {r.status_code} {r.text}"
        j = r.json()
        assert j["type"] == "secours"
        assert j["subtype"] == "pompiers"
        # cleanup
        requests.delete(f"{BASE_URL}/api/reports/{j['id']}",
                        headers=_hdr(maint_token), timeout=10)

    def test_post_secours_snsm_ok(self, maint_token):
        r = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(maint_token),
            json={"type": "secours", "subtype": "snsm",
                  "lat": 47.45, "lng": -3.05,
                  "description": "TEST_iter19 secours snsm"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["type"] == "secours"
        assert j["subtype"] == "snsm"
        requests.delete(f"{BASE_URL}/api/reports/{j['id']}",
                        headers=_hdr(maint_token), timeout=10)

    def test_post_old_garbage_type_rejected(self, maint_token):
        r = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(maint_token),
            json={"type": "old_garbage", "lat": 47.45, "lng": -3.05,
                  "description": "should 422"},
            timeout=15,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
