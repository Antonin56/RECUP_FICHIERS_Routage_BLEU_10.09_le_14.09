"""SignalMar — ROUTES OFFICIELLES SÛRES pour le Moteur H (26/08/2026, GO armateur).

Consomme ``data/bathy/safe_routes.json`` (ways OSM ingérées : recommended_track,
navigation_line, two-way_route — les pointillés « routes sûres » des cartes) :

- les ALIGNEMENTS (navigation_line) sont des lignes de visée vers un amer :
  ils débordent la partie navigable → ÉCRÊTÉS par la bathy (on ne garde que
  les tronçons en eau, profondeur ≥ 0,5 m au ZH) ;
- les tracés CHARTÉS (recommended_track, two-way_route) ne sont PAS écrêtés
  par la bathy (la carte fait foi sur une donnée à artefacts) mais sont,
  eux aussi, coupés là où ils passeraient du mauvais côté d'une latérale ;
- toutes les polylignes sont fusionnées en un RÉSEAU (jonctions ≤ 300 m) ;
- ``plan_tracks(start, end, attach_m)`` renvoie les chemins « sur route
  officielle » à suivre (règle armateur : si une route sûre existe on se cale
  dessus ; si elle ne va pas jusqu'à destination on la suit au plus proche et
  le moteur calcule le reste).

Aucun moteur A-G ne passe par ce module : Moteur H uniquement.
"""
from __future__ import annotations

import heapq
import json
import math
from typing import Optional

from core.bathy import DATA_DIR, M_PER_DEG_LAT, get_grid, m_per_deg_lng
from core.routing_engines.algos.signalmar_v4 import _required_side
from core.seamarks import get_seamarks

SAFE_ROUTES_PATH = DATA_DIR / "safe_routes.json"
_CLIP_MIN_DEPTH = 0.5      # m au ZH — en deçà, l'alignement est « à terre »
_SIDE_INFLUENCE_M = 200.0  # m — au-delà, une latérale n'impose pas son côté
_CLIP_STEP_M = 60.0        # pas d'échantillonnage bathy
_MIN_TRACK_M = 200.0       # tronçon écrêté plus court : ignoré
_JOIN_M = 300.0            # jonction entre extrémités de tracés voisins
_MIN_PATH_M = 300.0        # chemin sur route officielle plus court : inutile

Pt = tuple[float, float]   # (lat, lng)


def _d_m(a: Pt, b: Pt) -> float:
    return math.hypot((a[0] - b[0]) * M_PER_DEG_LAT,
                      (a[1] - b[1]) * m_per_deg_lng(a[0]))


class TrackNetwork:
    """Réseau des routes officielles : nœuds = sommets des polylignes,
    arêtes = tronçons + jonctions entre extrémités proches."""

    def __init__(self) -> None:
        self.nodes: list[Pt] = []
        self.names: list[str] = []          # nom du tracé porteur par nœud
        self.adj: list[list[tuple[int, float]]] = []
        self._endpoints: list[int] = []

    def _add_polyline(self, pts: list[Pt], name: str) -> None:
        idx = []
        for p in pts:
            idx.append(len(self.nodes))
            self.nodes.append(p)
            self.names.append(name)
            self.adj.append([])
        for a, b in zip(idx, idx[1:]):
            w = _d_m(self.nodes[a], self.nodes[b])
            self.adj[a].append((b, w))
            self.adj[b].append((a, w))
        if idx:
            self._endpoints.extend((idx[0], idx[-1]))

    def _join_endpoints(self) -> None:
        """Jonctions entre extrémités de tracés voisins (≤ ``_JOIN_M``).

        Une jonction est un segment SYNTHÉTIQUE, absent de la carte : elle est
        donc soumise à la règle de balisage comme les tracés eux-mêmes. Sans
        ce contrôle le réseau ré-ouvre un passage du mauvais côté d'une
        latérale ENTRE deux extrémités pourtant conformes — les tronçons
        étaient filtrés, les raccords ne l'étaient pas (iter145).
        """
        sm = get_seamarks()
        eps = self._endpoints
        for i, e in enumerate(eps):
            for f in eps[i + 1:]:
                if self.names[e] == self.names[f]:
                    continue
                w = _d_m(self.nodes[e], self.nodes[f])
                if w > _JOIN_M:
                    continue
                if sm is not None and any(
                        _wrong_side(sm, p)
                        for p in _sample([self.nodes[e], self.nodes[f]])):
                    continue
                self.adj[e].append((f, w))
                self.adj[f].append((e, w))

    def nearest(self, p: Pt) -> tuple[int, float]:
        best, best_d = -1, float("inf")
        for i, n in enumerate(self.nodes):
            d = _d_m(p, n)
            if d < best_d:
                best, best_d = i, d
        return best, best_d

    def dijkstra(self, src: int) -> tuple[list[float], list[int]]:
        dist = [float("inf")] * len(self.nodes)
        prev = [-1] * len(self.nodes)
        dist[src] = 0.0
        h = [(0.0, src)]
        while h:
            d, u = heapq.heappop(h)
            if d > dist[u]:
                continue
            for v, w in self.adj[u]:
                nd = d + w
                if nd < dist[v]:
                    dist[v], prev[v] = nd, u
                    heapq.heappush(h, (nd, v))
        return dist, prev

    def path_pts(self, prev: list[int], dst: int) -> list[Pt]:
        out: list[Pt] = []
        u = dst
        while u != -1:
            out.append(self.nodes[u])
            u = prev[u]
        return out[::-1]


_network: Optional[TrackNetwork] = None


def _wrong_side(sm, p: Pt) -> bool:
    """True si p est du mauvais côté d'une latérale proche à direction
    FIABLE. Ce module (alignements clipés bathy) ne passe jamais par le
    raster interdit du balisage utilisé par les Moteurs A-G : sans ce
    garde-fou, une route officielle peut caler le traé du mauvais côté
    d'une bouée (cas N° 3 / Banc du Turc, iter144)."""
    if sm is None:
        return False
    mlng = m_per_deg_lng(p[0])
    for m in sm.marks:
        if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
            continue
        d = math.hypot((m["lat"] - p[0]) * M_PER_DEG_LAT, (m["lng"] - p[1]) * mlng)
        if d > _SIDE_INFLUENCE_M:
            continue
        u = _required_side(sm, m)
        if u is None:
            continue
        ve = (p[1] - m["lng"]) * mlng
        vn = (p[0] - m["lat"]) * M_PER_DEG_LAT
        if ve * u[0] + vn * u[1] <= 0.0:
            return True   # mauvais côté
    return False


def _sample(pts: list[Pt]):
    """Points échantillonnés (~60 m) le long d'une polyligne, extrémités
    incluses."""
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(_d_m(a, b) / _CLIP_STEP_M))
        for k in range(n + 1):
            yield (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)


def _split_runs(pts: list[Pt], keep) -> list[list[Pt]]:
    """Tronçons CONSÉCUTIFS d'une polyligne dont les deux extrémités
    échantillonnées (~60 m) satisfont ``keep``. Les tronçons plus courts que
    ``_MIN_TRACK_M`` sont écartés."""
    runs: list[list[Pt]] = []
    cur: list[Pt] = []
    for a, b in zip(pts, pts[1:]):
        seg = _d_m(a, b)
        n = max(1, int(seg / _CLIP_STEP_M))
        for k in range(n):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            q = (a[0] + (b[0] - a[0]) * (k + 1) / n,
                 a[1] + (b[1] - a[1]) * (k + 1) / n)
            if keep(p) and keep(q):
                if not cur:
                    cur = [p]
                cur.append(q)
            elif cur:
                runs.append(cur)
                cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs
            if len(r) >= 2 and sum(_d_m(x, y) for x, y in zip(r, r[1:])) >= _MIN_TRACK_M]


def _clip_by_bathy(pts: list[Pt]) -> list[list[Pt]]:
    """Tronçons EN EAU d'une polyligne (échantillonnage ~60 m), en excluant
    aussi les points du mauvais côté d'une latérale fiable."""
    grid = get_grid()
    if grid is None:
        return [pts]
    sm = get_seamarks()

    def wet(p: Pt) -> bool:
        d = grid.depth_at(p[0], p[1])
        return d is not None and d >= _CLIP_MIN_DEPTH and not _wrong_side(sm, p)

    return _split_runs(pts, wet)


def _clip_wrong_side(pts: list[Pt]) -> list[list[Pt]]:
    """Tronçons d'un tracé CHARTÉ (recommended_track / two-way_route) qui
    respectent le balisage latéral.

    Ces tracés ne sont volontairement PAS écrêtés par la bathy : la donnée de
    profondeur porte des artefacts (lidar Litto3D, iter144) et la carte fait
    foi — les hauts-fonds résiduels restent signalés en tronçons rouges par
    le moteur. La règle de BALISAGE, elle, vaut pour TOUS les tracés : sans
    ce filtre, un recommended_track (jamais écrêté, cf. get_network)
    réinjecte dans le réseau un passage du mauvais côté d'une latérale
    (iter145 : N° 3 et Banc du Turc restaient franchis à contre-bord).

    Un tracé entièrement conforme est renvoyé INTACT — ni ré-échantillonné
    ni soumis au seuil ``_MIN_TRACK_M`` : seuls les tracés qui violent
    effectivement le balisage sont découpés.
    """
    sm = get_seamarks()
    if sm is None:
        return [pts]

    def ok(p: Pt) -> bool:
        return not _wrong_side(sm, p)

    if all(ok(p) for p in _sample(pts)):
        return [pts]
    return _split_runs(pts, ok)


def get_network() -> Optional[TrackNetwork]:
    """Réseau singleton (None si le fichier de données est absent)."""
    global _network
    if _network is not None:
        return _network
    if not SAFE_ROUTES_PATH.exists():
        return None
    data = json.loads(SAFE_ROUTES_PATH.read_text())
    net = TrackNetwork()
    for f in data.get("features", []):
        kind = f.get("kind")
        if kind not in ("recommended_track", "navigation_line", "two-way_route"):
            continue                       # fairways = polygones, hors réseau
        pts = [(float(a), float(b)) for a, b in f.get("coords", [])]
        if len(pts) < 2 or f.get("closed"):
            continue
        name = f.get("name") or f"{kind} {f.get('id')}"
        if kind == "navigation_line":      # alignement : écrêté par la bathy
            runs = _clip_by_bathy(pts)
        else:                              # tracé charté : balisage seulement
            runs = _clip_wrong_side(pts)
        for run in runs:
            net._add_polyline(run, name)
    net._join_endpoints()
    _network = net
    return net


def _components(net: TrackNetwork) -> list[list[int]]:
    seen = [False] * len(net.nodes)
    comps: list[list[int]] = []
    for s in range(len(net.nodes)):
        if seen[s]:
            continue
        stack, comp = [s], []
        seen[s] = True
        while stack:
            u = stack.pop()
            comp.append(u)
            for v, _w in net.adj[u]:
                if not seen[v]:
                    seen[v] = True
                    stack.append(v)
        comps.append(comp)
    return comps


def _seg_dist_m(p: Pt, a: Pt, b: Pt) -> float:
    """Distance (m) du point p au segment a→b (plan local)."""
    mlng = m_per_deg_lng(a[0])
    ax, ay = a[1] * mlng, a[0] * M_PER_DEG_LAT
    bx, by = b[1] * mlng, b[0] * M_PER_DEG_LAT
    px, py = p[1] * mlng, p[0] * M_PER_DEG_LAT
    vx, vy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy)
                     / max(vx * vx + vy * vy, 1e-9)))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def _best_comp(net, comps, used, cur: Pt, target: Pt,
               attach_m: float, bias: float):
    """Meilleure composante raccordable sur le CORRIDOR cur→target :
    (idxs du chemin, comp) ou None. Une composante est éligible si elle
    approche le corridor à ≤ attach_m (départ, arrivée OU milieu du trajet —
    cas Grand Mouton : l'entrée du Golfe est à mi-route). Tolérance
    0,5 × attach sur le score (la ligne droite ignore la terre : le vrai
    hors-piste coûte plus cher)."""
    direct = _d_m(cur, target)
    best, best_score = None, bias * direct + 0.5 * attach_m
    for comp in comps:
        if comp[0] in used:
            continue
        if min(_seg_dist_m(net.nodes[i], cur, target) for i in comp) > attach_m:
            continue
        entry = min(comp, key=lambda i: _d_m(cur, net.nodes[i]))
        d_in = _d_m(cur, net.nodes[entry])
        dist, prev = net.dijkstra(entry)
        exit_i, exit_c = -1, float("inf")
        for i in comp:
            if not math.isfinite(dist[i]):
                continue
            c = dist[i] + bias * _d_m(net.nodes[i], target)
            if c < exit_c:
                exit_i, exit_c = i, c
        if exit_i < 0 or dist[exit_i] < _MIN_PATH_M:
            continue
        score = bias * d_in + exit_c
        if score < best_score:
            idxs: list[int] = []
            u = exit_i
            while u != -1:
                idxs.append(u)
                u = prev[u]
            best_score = score
            best = (idxs[::-1], comp)
    return best


def plan_tracks(start: Pt, end: Pt, attach_m: float,
                bias: float = 1.4) -> list[dict]:
    """Chemins « sur routes officielles » ordonnés du départ vers l'arrivée.

    ``bias`` (> 1) = coût du HORS-PISTE : un mètre hors route officielle
    « coûte » bias mètres — c'est ce qui fait préférer le pointillé au vol
    d'oiseau (ajustable via params.track_bias). Passes : systèmes côté
    DÉPART (jusqu'à 2, ex. Lorient), puis système côté ARRIVÉE (passe
    inversée depuis la destination, ex. le Golfe sur Lorient → Golfe).
    Chaque chemin : {"pts": [(lat, lng), …], "names": [str, …]}."""
    net = get_network()
    if net is None or not net.nodes:
        return []
    comps = _components(net)
    out: list[dict] = []
    used: set[int] = set()

    def _emit(idxs: list[int], comp: list[int]) -> None:
        used.update(comp)
        out.append({
            "pts": [net.nodes[i] for i in idxs],
            "names": list(dict.fromkeys(net.names[i] for i in idxs)),
        })

    cur = start
    for _pass in range(2):
        found = _best_comp(net, comps, used, cur, end, attach_m, bias)
        if found is None:
            break
        idxs, comp = found
        _emit(idxs, comp)
        cur = net.nodes[idxs[-1]]
        if _d_m(cur, end) <= _MIN_PATH_M:
            break
    # Passe INVERSE : un système proche de l'ARRIVÉE, hors de portée du
    # raccordement côté départ (systèmes disjoints).
    if _d_m(cur, end) > attach_m:
        found = _best_comp(net, comps, used, end, cur, attach_m, bias)
        if found is not None:
            idxs, comp = found
            _emit(idxs[::-1], comp)
    return out


def reset_cache() -> None:
    global _network
    _network = None
