"""ITER165 (V1.6 UI/UX & offline zone) — Backend non-invasive checks only.
Ordre armateur : AUCUN calcul de route. On ne teste que :
  - /api/bathy/seamarks : plafond ≤5000 et défaut 600
  - /api/tiles/dalles-list : polygon → liste de tiles conservée
"""
import os
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")


class TestSeamarksLimit:
    def test_seamarks_bbox_high_limit(self):
        r = requests.get(
            f"{BASE_URL}/api/bathy/seamarks",
            params={"bbox": "-2.95,47.5,-2.85,47.6", "limit": 2000},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert "marks" in j
        marks = j["marks"]
        # ~545 attendu ; endpoint accepte désormais limit>600 sans 422
        assert 400 <= len(marks) <= 2000, f"unexpected marks count: {len(marks)}"

    def test_seamarks_limit_over_5000_is_422(self):
        r = requests.get(
            f"{BASE_URL}/api/bathy/seamarks",
            params={"bbox": "-2.95,47.5,-2.85,47.6", "limit": 9999},
            timeout=30,
        )
        assert r.status_code == 422

    def test_seamarks_default_limit_600(self):
        r = requests.get(
            f"{BASE_URL}/api/bathy/seamarks",
            params={"bbox": "-2.95,47.5,-2.85,47.6"},
            timeout=30,
        )
        assert r.status_code == 200
        marks = r.json().get("marks", [])
        assert len(marks) <= 600


class TestDallesList:
    def test_dalles_list_polygon(self):
        r = requests.get(
            f"{BASE_URL}/api/tiles/dalles-list",
            params={"poly": "47.5,-3.0;47.5,-2.8;47.6,-2.8;47.6,-3.0"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert "tiles" in j or isinstance(j, list)
        tiles = j.get("tiles") if isinstance(j, dict) else j
        assert isinstance(tiles, list)
        assert len(tiles) >= 1
