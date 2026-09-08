# SignalMar — ITER163 remise à plat: tiles OVH + bathy seamarks (non-invasif, aucun calcul de route)
import io
import os
import time

import pytest
import requests
from PIL import Image

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://calcul-optimize.preview.emergentagent.com"
).rstrip("/")


class TestTilesSource:
    def test_bathy_tiles_source(self):
        r = requests.get(f"{BASE_URL}/api/bathy/tiles-source", timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("source") == "ovh", j
        b = j.get("bounds")
        assert b and b[0] == -5.3 and b[1] == 43.3 and b[2] == -1.0 and b[3] == 48.9, j


class TestDalles:
    def test_z12_morbihan_opaque_png(self):
        r = requests.get(f"{BASE_URL}/api/tiles/dalles/12/2015/1431.png", timeout=90)
        assert r.status_code == 200, r.text
        img = Image.open(io.BytesIO(r.content))
        assert img.size == (256, 256), img.size
        # Vérifier des pixels opaques (alpha > 0)
        if img.mode == "RGBA":
            alphas = img.split()[3].getextrema()
            assert alphas[1] > 0, f"aucun pixel opaque, alpha extrema={alphas}"

    def test_z12_cache_relecture_rapide(self):
        # 1er accès a chauffé le cache, 2e doit être rapide
        t0 = time.monotonic()
        r = requests.get(f"{BASE_URL}/api/tiles/dalles/12/2015/1431.png", timeout=15)
        dt = time.monotonic() - t0
        assert r.status_code == 200
        assert dt < 5.0, f"relecture cache lente: {dt:.2f}s"

    def test_z8_transparent(self):
        r = requests.get(f"{BASE_URL}/api/tiles/dalles/8/125/89.png", timeout=30)
        assert r.status_code == 200, r.text
        img = Image.open(io.BytesIO(r.content))
        # z<10 doit être transparent (taille 1x1 minimale ou 256x256 acceptés)
        if img.mode == "RGBA":
            alphas = img.split()[3].getextrema()
            assert alphas[1] == 0, f"z8 non transparent, alpha extrema={alphas}"


class TestSeamarks:
    def test_gregan_present(self):
        r = requests.get(
            f"{BASE_URL}/api/bathy/seamarks",
            params={"bbox": "-2.93,47.55,-2.90,47.58"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        marks = j if isinstance(j, list) else j.get("marks") or j.get("seamarks") or []
        names = [(m.get("name") or "") for m in marks]
        assert any("Grégan" in n or "Gregan" in n for n in names), f"Grégan absent: {names[:20]}"

    def test_arcachon_more_than_50(self):
        r = requests.get(
            f"{BASE_URL}/api/bathy/seamarks",
            params={"bbox": "-1.30,44.55,-1.10,44.75"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        marks = j if isinstance(j, list) else j.get("marks") or j.get("seamarks") or []
        assert len(marks) > 50, f"Arcachon: seulement {len(marks)} balises"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
