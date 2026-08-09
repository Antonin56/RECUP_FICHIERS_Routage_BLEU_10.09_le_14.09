"""SignalMar — Moteur C : MARGE LATÉRALE MESURÉE (03/08/2026).

RÈGLE 3 (consigne armateur) : « 50 m par défaut partout. Peut être réduite
jusqu'à 20 m pour respecter le balisage (priorité 1) ou la profondeur
(priorité 2). Si moins de 20 m est inévitable, le tronçon doit être tracé en
ROUGE avec un avertissement. »

Le masque de l'A* garantit la marge À LA MAILLE DE CALCUL (75-110 m hors zone
pilote) : il ne suffit donc pas à PROUVER la marge réelle. On la MESURE ici en
PLEINE résolution, tronçon par tronçon : autour de chaque point échantillonné,
on sonde des couronnes de 20 m puis 50 m dans 16 directions. Le premier rayon
qui touche une cellule non navigable (fond < seuil, terre, sans donnée) donne
la marge du tronçon.
"""
from __future__ import annotations

import math

from core.bathy import M_PER_DEG_LAT, get_grid, m_per_deg_lng

#: 16 directions (est, nord) unitaires.
_DIRS = [
    (math.cos(2 * math.pi * k / 16), math.sin(2 * math.pi * k / 16))
    for k in range(16)
]
#: Pas d'échantillonnage le long d'un tronçon (m) et plafond de points.
_STEP_M = 25.0
_MAX_SAMPLES = 240


def leg_clearances(
    waypoints: list[dict], min_depth: float, radii: tuple[float, ...] = (20.0, 50.0),
) -> list[float]:
    """Marge latérale mesurée (m) pour chaque tronçon. La valeur retournée est
    le plus petit rayon de ``radii`` touchant du non-navigable, ou
    ``2 × max(radii)`` si aucun ne touche (marge franchement supérieure)."""
    grid = get_grid()
    if grid is None or len(waypoints) < 2:
        return []
    lat_mid = sum(w["lat"] for w in waypoints) / len(waypoints)
    mlng = m_per_deg_lng(lat_mid)
    out: list[float] = []
    ordered = sorted(radii)
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        seg_m = math.hypot((b["lat"] - a["lat"]) * M_PER_DEG_LAT,
                           (b["lng"] - a["lng"]) * mlng)
        n = max(1, min(_MAX_SAMPLES, int(seg_m / _STEP_M)))
        worst = ordered[-1] * 2.0
        for k in range(n + 1):
            t = k / n
            lat = a["lat"] + (b["lat"] - a["lat"]) * t
            lng = a["lng"] + (b["lng"] - a["lng"]) * t
            for r in ordered:
                if r >= worst:
                    break
                hit = False
                for de, dn in _DIRS:
                    d = grid.depth_at(lat + (dn * r) / M_PER_DEG_LAT,
                                      lng + (de * r) / mlng)
                    if d is None or float(d) < min_depth:
                        hit = True
                        break
                if hit:
                    worst = r
                    break
        out.append(worst)
    return out


__all__ = ["leg_clearances"]
