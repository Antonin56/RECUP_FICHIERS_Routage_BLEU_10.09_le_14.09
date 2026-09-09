"""ITER164 — SignalMar : STOP calcul + MASTER PLAN données (dalles) + A* pondéré.

Tests NON-INVASIFS UNIQUEMENT (aucun calcul de route déclenché) :
- STATIQUE : ContextVar ASTAR_TUNING défaut None + A* pondéré via _astar sur
  grille synthétique numpy 12x12 (jamais via un moteur).
- STATIQUE : engine_j.py arme _J_ASTAR_TUNING autour de super().compute_auto
  avec reset en finally (revue de code).
- HTTP : endpoints /api/tiles/dalles-list, /api/tiles/dalles-npy/{name},
  /api/tiles/dalles-fine-list, et rendu /api/tiles/dalles/{z}/{x}/{y}.png.
"""
import io
import os
import re

import numpy as np
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


# ── UNITAIRE 2 : ContextVar ASTAR_TUNING défaut None + A* pondéré ──────────
class TestAstarTuning:
    def test_astar_tuning_default_is_none(self):
        from core.routing_engines.algos.signalmar_v1.core import ASTAR_TUNING
        assert ASTAR_TUNING.get() is None

    def test_astar_synthetic_grid_paths_match_and_cap_returns_none(self):
        from core.routing_engines.algos.signalmar_v1 import core as sm_core

        nav = np.ones((12, 12), dtype=bool)
        cost_extra = np.zeros((12, 12), dtype=np.float64)
        start = (0, 0)
        goal = (11, 11)

        # Sans tuning (défaut A-I).
        assert sm_core.ASTAR_TUNING.get() is None
        path_default = sm_core._astar(nav, cost_extra, start, goal, 1.0, 1.0)
        assert path_default is not None
        assert path_default[0] == start and path_default[-1] == goal

        # Avec tuning (2.0, 50_000) (Moteur J).
        tok = sm_core.ASTAR_TUNING.set((2.0, 50_000))
        try:
            path_j = sm_core._astar(nav, cost_extra, start, goal, 1.0, 1.0)
        finally:
            sm_core.ASTAR_TUNING.reset(tok)
        assert path_j == path_default, "Le tracé A* doit être IDENTIQUE (grille uniforme)"

        # Reset propre.
        assert sm_core.ASTAR_TUNING.get() is None

        # Avec cap très petit (2.0, 5) → None.
        tok = sm_core.ASTAR_TUNING.set((2.0, 5))
        try:
            path_capped = sm_core._astar(nav, cost_extra, start, goal, 1.0, 1.0)
        finally:
            sm_core.ASTAR_TUNING.reset(tok)
        assert path_capped is None, "Cap 5 nœuds → le but ne doit pas être atteint"

    def test_engine_j_arms_astar_tuning_around_super(self):
        """Revue de code STATIQUE : engine_j.py arme _J_ASTAR_TUNING via
        ContextVar avec reset en finally autour de super().compute_auto."""
        with open("/app/backend/core/nav/engine_j.py") as f:
            src = f.read()
        assert "_J_ASTAR_TUNING = (2.0, 50_000)" in src
        assert "ASTAR_TUNING.set(_J_ASTAR_TUNING)" in src
        assert "ASTAR_TUNING.reset(" in src
        assert "super().compute_auto" in src
        # L'ordre logique : set → try → super().compute_auto → finally reset
        set_pos = src.index("ASTAR_TUNING.set(_J_ASTAR_TUNING)")
        super_pos = src.index("super().compute_auto")
        reset_pos = src.index("ASTAR_TUNING.reset(")
        assert set_pos < super_pos < reset_pos


# ── STATIQUE 1 : engine_i.py intact ────────────────────────────────────────
class TestEngineIntact:
    def test_engine_i_untouched_since_ref_commit(self):
        import subprocess
        r = subprocess.run(
            ["git", "-C", "/app", "diff", "2b000634", "HEAD", "--",
             "backend/core/nav/engine_i.py"],
            capture_output=True, text=True, check=True,
        )
        assert r.stdout.strip() == "", (
            f"engine_i.py DOIT être intact vs 2b000634 :\n{r.stdout[:500]}")


# ── NON-INVASIF 3 : /api/tiles/dalles-list ─────────────────────────────────
class TestDallesList:
    def test_dalles_list_success(self):
        r = requests.get(
            f"{API}/tiles/dalles-list",
            params={"poly": "47.5,-3.0;47.5,-2.8;47.6,-2.8;47.6,-3.0"},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tiles" in data and "total_bytes" in data
        n = len(data["tiles"])
        assert 8 <= n <= 16, f"Attendu ~12 dalles, obtenu {n}"
        # ~12 Mo ≈ 12 * 1_000_128 (chaque dalle = 500x500 float32 + 128 header)
        assert 8_000_000 <= data["total_bytes"] <= 16_000_000
        # Structure d'une dalle.
        t0 = data["tiles"][0]
        assert set(t0.keys()) >= {"name", "bbox", "size_bytes"}
        assert t0["size_bytes"] == 1_000_128

    def test_dalles_list_invalid_poly_422(self):
        r = requests.get(
            f"{API}/tiles/dalles-list",
            params={"poly": "47.5,-3.0;47.5,-2.8"},  # 2 points
            timeout=30,
        )
        assert r.status_code == 422


# ── NON-INVASIF 4 : /api/tiles/dalles-npy/{name} ───────────────────────────
class TestDallesNpy:
    def test_dalles_npy_success(self):
        # 1er GET peut prendre 30-60 s (téléchargement OVH puis cache disque).
        r = requests.get(
            f"{API}/tiles/dalles-npy/tile_47.5_-2.9.npy",
            timeout=120,
        )
        assert r.status_code == 200, r.text
        assert len(r.content) == 1_000_128
        arr = np.load(io.BytesIO(r.content))
        assert arr.shape == (500, 500)
        assert arr.dtype == np.float32

    @pytest.mark.parametrize("bad", [
        "tile_x.npy",
        "tile_47.5_-2.9.txt",
        "malicious.npy",
    ])
    def test_dalles_npy_invalid_name_422(self, bad):
        r = requests.get(f"{API}/tiles/dalles-npy/{bad}", timeout=30)
        assert r.status_code == 422, f"{bad} → {r.status_code}"

    def test_dalles_npy_traversal_blocked(self):
        """`../etc/passwd` : le path traversal est bloqué par l'ingress (404)
        AVANT même d'atteindre l'endpoint. Point important : jamais 200 avec
        contenu system."""
        r = requests.get(f"{API}/tiles/dalles-npy/../etc/passwd", timeout=30)
        assert r.status_code in (404, 422), r.status_code
        # Sécurité : le corps ne doit rien renvoyer de suspect.
        assert b"root:" not in r.content


# ── NON-INVASIF 5 : /api/tiles/dalles-fine-list ────────────────────────────
class TestDallesFineList:
    def test_dalles_fine_list_empty(self):
        r = requests.get(
            f"{API}/tiles/dalles-fine-list",
            params={"bbox": "-3.0,47.5,-2.8,47.6"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data == {"tiles": []}

    def test_dalles_fine_list_invalid_bbox_422(self):
        r = requests.get(
            f"{API}/tiles/dalles-fine-list",
            params={"bbox": "not,a,bbox"},
            timeout=30,
        )
        assert r.status_code == 422


# ── NON-INVASIF 6 : /api/tiles/dalles/{z}/{x}/{y}.png ──────────────────────
class TestDallesPng:
    def test_z8_opaque(self):
        # Bretagne sud, z8 : x=125, y=89 couvre ~47-48°N / -3.5..0°E.
        r = requests.get(f"{API}/tiles/dalles/8/125/89.png", timeout=120)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("image/png")
        from PIL import Image
        img = Image.open(io.BytesIO(r.content))
        arr = np.array(img)
        assert arr.shape[2] == 4  # RGBA
        alpha_max = int(arr[..., 3].max())
        assert alpha_max == 255, f"z8 doit avoir des pixels OPAQUES (alpha_max={alpha_max})"

    def test_z7_fully_transparent(self):
        r = requests.get(f"{API}/tiles/dalles/7/62/44.png", timeout=60)
        assert r.status_code == 200
        from PIL import Image
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        arr = np.array(img)
        alpha_max = int(arr[..., 3].max())
        assert alpha_max == 0, f"z7 doit être TOTALEMENT transparent (alpha_max={alpha_max})"


# ── STATIQUE 7 : frontend files (offline-dalles, map.tsx, bootstrap/tiles/bathy) ──
class TestFrontendStatic:
    def test_offline_dalles_module(self):
        p = "/app/frontend/src/lib/offline-dalles.ts"
        with open(p) as f:
            src = f.read()
        for sym in ["listDallesForPolygon", "downloadDalles", "checkFineTiles",
                    "AsyncStorage", "MANIFEST_KEY"]:
            assert sym in src, f"{sym} manquant dans {p}"

    def test_map_offline_zone_ui(self):
        with open("/app/frontend/app/(tabs)/map.tsx") as f:
            src = f.read()
        for tid in ["offline-zone-bar", "offline-zone-analyze",
                    "offline-zone-download", "route-retry-engine"]:
            assert f'testID="{tid}"' in src, f"testID {tid} manquant"
        for sym in ["offlinePoints", "offlineTiles", "offlineBusy"]:
            assert sym in src, f"état {sym} manquant"
        # reason 'stop' présent
        assert 'reason: "stop"' in src or "reason:\"stop\"" in src.replace(" ", "")

    def test_longpress_menu_offline_entry(self):
        with open("/app/frontend/src/screens/map/modals/LongPressMenuModal.tsx") as f:
            src = f.read()
        assert 'testID="longpress-offline-zone"' in src

    def test_bootstrap_max_zoom_21(self):
        with open("/app/frontend/src/components/marine-map/js/bootstrap.ts") as f:
            src = f.read()
        assert "maxZoom: 21" in src

    def test_tiles_osm_and_openseamap_max_zooms(self):
        with open("/app/frontend/src/components/marine-map/js/tiles.ts") as f:
            src = f.read()
        # OSM : maxZoom 21 / maxNativeZoom 19
        assert re.search(r"maxZoom:\s*21,\s*maxNativeZoom:\s*19", src)
        # OpenSeaMap : maxNativeZoom 18
        assert "maxNativeZoom: 18" in src

    def test_bathy_dalles_z8_and_maxnative_19(self):
        with open("/app/frontend/src/components/marine-map/js/bathy.ts") as f:
            src = f.read()
        assert "map.getZoom() >= 8" in src
        assert "maxZoom: 21" in src and "maxNativeZoom: 19" in src
