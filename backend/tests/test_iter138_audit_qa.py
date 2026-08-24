"""Itération 138 (14/08/2026) — correctifs de l'audit QA externe.

Couvre côté API : gel réel des moteurs (FND-001/002), refus des moteurs
inconnus/désactivés (FND-003), job relisible (FND-012), codes d'erreur
(FND-028/024/015/014), et côté moteur F : plus JAMAIS de tronçon sur la
TERRE FERME (P0/FND-004, arrivée Crouesty à terre).
"""
import math

import pytest

from core.bathy import M_PER_DEG_LAT, get_grid, m_per_deg_lng
from core.routing_engines.algos import get_algo

# Cas P0 de l'audit : arrivée demandée À TERRE (port du Crouesty).
P0_START = (47.515, -2.93)
P0_END = (47.548, -2.905)
LAND_LIMIT = -3.5


@pytest.fixture(scope="module")
def res_p0():
    return get_algo("signalmar.v6").compute_auto(
        *P0_START, *P0_END, 1.5, 0.5, 10.0, tide_m=0.0)


def test_p0_aucun_troncon_sur_terre(res_p0):
    """Le tracé complet, échantillonné tous les ~25 m, ne traverse JAMAIS la
    terre ferme (fond < −3,5 m au ZH) — avant : dernier tronçon à −13,8 m."""
    grid = get_grid()
    wps = res_p0["waypoints"]
    worst = 99.0
    for i in range(len(wps) - 1):
        a, b = wps[i], wps[i + 1]
        seg = math.hypot((b["lat"] - a["lat"]) * M_PER_DEG_LAT,
                         (b["lng"] - a["lng"]) * m_per_deg_lng(a["lat"]))
        n = max(2, int(seg / 25.0) + 1)
        for s in range(n + 1):
            t = s / n
            d = grid.depth_at(a["lat"] + (b["lat"] - a["lat"]) * t,
                              a["lng"] + (b["lng"] - a["lng"]) * t)
            if d is not None:
                worst = min(worst, d)
    assert worst >= LAND_LIMIT, f"tronçon sur terre (fond {worst:.1f} m)"
    assert res_p0["min_depth_m"] >= LAND_LIMIT


def test_p0_arrivee_a_terre_honnete(res_p0):
    """L'arrivée à terre est SIGNALÉE : end_snapped + avertissement franc,
    plus de message « suit le chenal balisé » mensonger."""
    snap = res_p0.get("end_snapped")
    assert snap and snap.get("reason") == "arrivee_a_terre"
    assert float(snap["offset_m"]) > 50.0
    warns = res_p0.get("warnings") or []
    assert any(w.startswith("⚠ ARRIVÉE DEMANDÉE À TERRE") for w in warns)
    assert not any("suit le chenal balisé jusqu'au point demandé" in w
                   for w in warns)


def test_p0_moteur_e_fige_inchange():
    """Gel du Moteur E : il rend toujours son tracé historique (tronçon à
    terre compris) — preuve que le correctif ne touche que le Moteur F."""
    res = get_algo("signalmar.v5").compute_auto(
        *P0_START, *P0_END, 1.5, 0.5, 10.0, tide_m=0.0)
    assert res["min_depth_m"] < -5.0  # le bug historique est conservé sur E


def test_gel_moteurs_et_resolution_stricte():
    """FND-001/002/003 — champ frozen posé, garde-fous du manager."""
    import asyncio
    import os
    from motor.motor_asyncio import AsyncIOMotorClient
    from core.routing_engines import manager as M

    async def _run():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[
            os.environ.get("DB_NAME", "signalmar")]
        await M.ensure_seed(db)
        for eid in M.FROZEN_ENGINE_IDS:
            doc = await M.get_engine(db, eid)
            if doc is None:
                continue
            assert doc.get("frozen") is True
            with pytest.raises(ValueError):
                await M.rename_engine(db, eid, "QA_FROZEN_PROBE")
            with pytest.raises(ValueError):
                await M.delete_engine(db, eid)
            with pytest.raises(ValueError):
                await M.set_active_flag(db, eid, False)
        # noms uniques (FND-038)
        with pytest.raises(ValueError):
            await M.duplicate_engine(db, source_id="engine_a", name="Moteur A")

    asyncio.run(_run())
