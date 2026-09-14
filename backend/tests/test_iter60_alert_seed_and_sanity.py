"""Iteration 60 — Sound-alert refactor: seed TEST ALERTES + backend sanity.

Creates the 5 reports the frontend test plan needs (Golfe du Morbihan) and
verifies GET /api/reports returns them with the expected extras.
"""

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://nav-routing-speed.preview.emergentagent.com").rstrip("/")
BYPASS = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
PHONE = "0760071445"
OTP = "123456"

# 5 reports around Golfe du Morbihan (center ≈ 47.55, -2.78)
TEST_REPORTS = [
    {"type": "autorites",    "subtype": "gendarmerie",  "lat": 47.5560, "lng": -2.7620, "extras": {}},
    {"type": "obstacle_nav", "subtype": "conteneur",    "lat": 47.5620, "lng": -2.7800, "extras": {}},
    {"type": "animal_marin", "subtype": "mammifere",    "lat": 47.5500, "lng": -2.7950, "extras": {}},
    {"type": "animal_marin", "subtype": "oiseau",       "lat": 47.5460, "lng": -2.7700, "extras": {"health": "blesse"}},
    {"type": "pollution",    "subtype": "hydrocarbures","lat": 47.5580, "lng": -2.7500, "extras": {}},
]


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", **BYPASS})
    return s


@pytest.fixture(scope="module")
def token(api):
    r = api.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 200, r.text
    time.sleep(0.5)
    r = api.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": PHONE, "code": OTP})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    api.headers["Authorization"] = f"Bearer {tok}"
    return tok


class TestSeedAndSanity:
    def test_seed_5_test_alertes(self, api, token):
        created_ids = []
        for spec in TEST_REPORTS:
            payload = {
                **spec,
                "description": f"TEST ALERTES — {spec['type']}/{spec['subtype']} (auto-seed iteration 60)",
            }
            r = api.post(f"{BASE_URL}/api/reports", json=payload)
            assert r.status_code in (200, 201), f"create {spec}: {r.status_code} {r.text}"
            body = r.json()
            assert body.get("id"), body
            assert body["type"] == spec["type"]
            assert body["subtype"] == spec["subtype"]
            # Verify extras persisted (esp. health for oiseau)
            if spec["extras"]:
                assert (body.get("extras") or {}).get("health") == spec["extras"].get("health"), body
            created_ids.append(body["id"])
        assert len(created_ids) == 5

    def test_get_reports_near_golfe_contains_test_alertes(self, api, token):
        r = api.get(f"{BASE_URL}/api/reports?lat=47.55&lng=-2.78&radius_km=20")
        assert r.status_code == 200, r.text
        data = r.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        assert isinstance(items, list)
        # Filter TEST ALERTES seeded above
        tests = [i for i in items if "TEST ALERTES" in (i.get("description") or "")]
        assert len(tests) >= 5, f"expected ≥5 TEST ALERTES near Golfe, got {len(tests)}"
        # Check the oiseau has extras.health == 'blesse'
        birds = [i for i in tests if i.get("subtype") == "oiseau"]
        assert birds, "oiseau blessé missing"
        assert (birds[0].get("extras") or {}).get("health") == "blesse", birds[0]

    def test_types_all_present(self, api, token):
        r = api.get(f"{BASE_URL}/api/reports?lat=47.55&lng=-2.78&radius_km=20")
        items = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
        types_present = {(i.get("type"), i.get("subtype")) for i in items if "TEST ALERTES" in (i.get("description") or "")}
        for spec in TEST_REPORTS:
            assert (spec["type"], spec["subtype"]) in types_present, f"missing {spec['type']}/{spec['subtype']}"
