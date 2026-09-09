"""SignalMar — MOTEUR J (04/09/2026, GO armateur) : Moteur I sur DALLES OVH.

Moteur d'ESSAI pour COMPARAISON : logique de routage STRICTEMENT identique
au Moteur I v8.1.0 (héritage direct, aucune copie de code), mais la source
bathymétrique est remplacée le temps du calcul par les dalles du serveur
OVH de l'armateur (https://…/signalmar_datas/tiles/, hiérarchie côté PC :
Litto3D 5 m > Côtier 20 m > Façade 100 m) via ``core.bathy.GRID_OVERRIDE``
(ContextVar — même mécanique éprouvée que SIDE_RULES_OPEN, aucune fuite
vers les calculs concurrents des moteurs A-I).

Si le serveur OVH est injoignable, le calcul se REPLIE sur la mosaïque
SHOM locale (résultat = Moteur I) avec un avertissement explicite.

⚠️ RÈGLES : engine_f_frozen.py intouchable ; engine_i.py non modifié ;
tout écart Moteur I ↔ Moteur J provient DES DONNÉES uniquement.
"""
from __future__ import annotations

from typing import Any

from core.bathy import GRID_OVERRIDE
from core.nav.engine_i import EngineI
from core.routing_engines.algos.signalmar_v1.core import ASTAR_TUNING
from core.tile_bathy import LABEL_ARCHIVE, LABEL_OVH, get_remote_grid

# 08/09/2026 (ordre armateur, PERFORMANCE) — A* PONDÉRÉ pour le Moteur J :
# poids heuristique 2.0 + plafond 50 000 nœuds (calcul fluide). Posé par
# ContextVar le temps du calcul → moteurs A-I strictement inchangés.
_J_ASTAR_TUNING = (2.0, 50_000)


class EngineJ(EngineI):
    id = "signalmar.j"
    version = "1.0.0"
    description = (
        "Moteur J (essai, 04/09/26) : logique du Moteur I v8.1.0 à "
        "l'identique, mais bathymétrie = dalles du serveur OVH de "
        "l'armateur (Litto3D 5 m > Côtier 20 m > Façade 100 m). Repli sur "
        "la mosaïque locale si le serveur ne répond pas. Créé pour "
        "comparer l'effet des données sur les tracés — moteurs A-I "
        "inchangés."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        remote = get_remote_grid()
        tok_a = ASTAR_TUNING.set(_J_ASTAR_TUNING)
        try:
            if remote is None:
                res = super().compute_auto(
                    start_lat, start_lng, end_lat, end_lng,
                    draft_m, depth_margin_m, lateral_margin_m,
                    tide_m=tide_m, params=params)
                res.setdefault("warnings", []).append(
                    f"Bathy : {LABEL_ARCHIVE} — serveur OVH injoignable, calcul "
                    "sur la mosaïque SHOM locale (résultat = Moteur I).")
                return res
            token = GRID_OVERRIDE.set(remote)
            try:
                res = super().compute_auto(
                    start_lat, start_lng, end_lat, end_lng,
                    draft_m, depth_margin_m, lateral_margin_m,
                    tide_m=tide_m, params=params)
            finally:
                GRID_OVERRIDE.reset(token)
        finally:
            ASTAR_TUNING.reset(tok_a)
        res.setdefault("warnings", []).append(
            f"Bathy : {LABEL_OVH} — dalles PC armateur "
            "(Litto3D 5 m > Côtier 20 m > Façade 100 m).")
        return res
