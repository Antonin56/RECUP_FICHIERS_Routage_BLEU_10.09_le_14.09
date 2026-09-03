"""SignalMar — Tests du lecteur de dalles PC (core/tile_bathy.py, 03/09/2026).

100 % LOCAL et LECTURE SEULE : aucun appel réseau, aucun calcul de route,
aucun moteur (A-I) sollicité — conforme à l'ordre armateur.
Données : les 6 dalles de test livrées par l'armateur (Lorient/Étel) dans
data/tiles/tandem_20m/ (index de 71 dalles, 4 finales + 2 _orig présentes).
Référence croisée : core.bathy (mosaïque SignalMar, même produit TANDEM).
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
import pytest

from core.bathy import get_grid
from core.tile_bathy import DEFAULT_INDEX, TileBathy

pytestmark = pytest.mark.skipif(
    not DEFAULT_INDEX.exists(), reason="dalles PC non livrées")

# Limite nord du produit TANDEM : au-delà, la mosaïque SignalMar bascule
# sur la couche Litto3D Lorient que les dalles PC n'ont pas — on borne les
# comparaisons pour ne tester que le périmètre commun.
TANDEM_NORTH = 47.7251

# Dalles finales livrées : clé → (lat0, lng0) de l'index.
DELIVERED = {
    "476_-32": (47.7001, -3.20003),
    "476_-33": (47.7001, -3.30003),
    "477_-32": (47.8001, -3.20003),
    "477_-33": (47.8001, -3.30003),
}


@pytest.fixture(scope="module")
def reader() -> TileBathy:
    return TileBathy()


@pytest.fixture(scope="module")
def mosaic():
    return get_grid()


def test_index_metadata(reader):
    assert reader.convention == \
        "depth_m_below_ZH_positive_down;NaN=land_or_nodata"
    assert reader.crs == "EPSG:4326"
    assert reader.row_order == "north_to_south"
    layer = reader.layers[0]
    assert layer.name == "tandem_20m"
    assert layer.tile_size == 500
    assert layer.cell_deg == 0.0002
    assert len(layer.tiles) == 71


def test_stats_partial_delivery(reader):
    st = reader.stats()["tandem_20m"]
    assert st["tiles_indexed"] == 71
    assert st["tiles_present"] == 4          # jeu de test armateur 03/09


def test_depth_matches_mosaic(reader, mosaic):
    """1600 points seedés dans les 4 dalles livrées : identité stricte
    avec la mosaïque SignalMar (mêmes données TANDEM, îles bakées)."""
    rng = random.Random(42)
    checked = 0
    for key, (lat0, lng0) in DELIVERED.items():
        for _ in range(400):
            lat = lat0 - rng.random() * 0.1
            lng = lng0 + rng.random() * 0.1
            if lat > TANDEM_NORTH:
                continue                     # hors périmètre commun
            tv = reader.depth_at(lat, lng)
            mv = mosaic.depth_at(lat, lng)
            assert (tv is None) == (mv is None), (key, lat, lng, tv, mv)
            if tv is not None:
                assert abs(tv - mv) <= 1e-6, (key, lat, lng, tv, mv)
            checked += 1
    assert checked > 900


def test_island_bake_is_none(reader):
    """Une cellule d'île bakée (NaN final, finie dans _orig) → None."""
    layer = reader.layers[0]
    key, (lat0, lng0) = "476_-32", DELIVERED["476_-32"]
    final = np.load(layer.dir / layer.tiles[key]["file"], mmap_mode="r")
    orig = np.load(layer.dir / "tile_20m_476_-32_orig.npy", mmap_mode="r")
    baked = np.argwhere(np.isnan(np.asarray(final))
                        & np.isfinite(np.asarray(orig)))
    assert len(baked) == layer.tiles[key]["land_cells_baked"] == 1022
    r, c = (int(v) for v in baked[len(baked) // 2])
    lat = lat0 - (r + 0.5) * 0.0002
    lng = lng0 + (c + 0.5) * 0.0002
    assert reader.depth_at(lat, lng) is None


def test_missing_tile_file_is_graceful(reader):
    """Port-Navalo (dalle 475_-30 dans l'index, fichier NON livré) →
    None sans exception, dalle comptée manquante."""
    assert reader.depth_at(47.5445, -2.9210) is None
    assert "475_-30" in reader.stats()["tandem_20m"]["missing_files"]


def test_out_of_coverage(reader):
    assert reader.depth_at(48.5, -3.25) is None        # hors index
    assert reader.depth_at(47.65, -2.0) is None        # est du produit


def test_subcell_offset_neighbor_fallback(reader):
    """Coins de dalles décalés d'une fraction de cellule (lng0=-3.20003) :
    un point entre -3.20003 et -3.2 doit être résolu par la dalle VOISINE
    de celle donnée par floor()."""
    lat, lng = 47.65, -3.200025          # floor → ix=-33, contenu par -32
    layer = reader.layers[0]
    assert layer._key_for(lat, lng) == "476_-32"
    assert reader.depth_at(lat, lng) is not None


def test_tiles_for_bbox(reader):
    got = reader.tiles_for_bbox(-3.29, 47.62, -3.15, 47.75)["tandem_20m"]
    assert set(DELIVERED) <= set(got)
    # bbox loin à l'est → aucune des dalles livrées
    far = reader.tiles_for_bbox(-2.5, 47.3, -2.4, 47.4)["tandem_20m"]
    assert not set(DELIVERED) & set(far)
