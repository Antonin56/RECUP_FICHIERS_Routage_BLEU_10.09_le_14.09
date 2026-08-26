"""SignalMar — Contraintes de balisage IALA zone A (21/07/2026, GO armateur).

Traduit les balises OSM ingérées (scripts/ingest_seamarks.py) en zones
INTERDITES rasterisées dans le masque navigable du moteur de route :

- LATÉRALES (règle du sens conventionnel, validée par l'armateur) : le sens
  conventionnel va DU LARGE VERS L'ABRI. « Verte à tribord en entrant » et
  « verte à bâbord en sortant » désignent LE MÊME côté absolu de la bouée →
  chaque latérale interdit un DEMI-DISQUE fixe, valable dans les deux sens.
  Le côté est déterminé par la direction conventionnelle locale D (vers
  l'abri), calculée comme le gradient d'un champ « distance au large à
  travers l'eau » (BFS géodésique depuis la bordure océanique de la grille).
      verte (starboard-hand) : le bateau passe à GAUCHE de D → interdit le
      côté droit de D ;  rouge (port-hand) : l'inverse.
- CARDINALES : le danger est du côté opposé au nom (cardinale Nord placée au
  nord du danger) → demi-disque interdit côté danger.
- DANGER ISOLÉ : disque interdit centré sur la balise (passage libre du côté
  le plus court — l'A* choisit).
- MARQUES SPÉCIALES : petit disque d'écart.
- Latérale sans côté NI couleur (7 sur 204) : ignorée (jamais « danger »,
  règle armateur) — à corriger dans OSM ou via table d'exceptions.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import ndimage

from core.bathy import BathyGrid, get_grid, get_zone_grid

SEAMARKS_PATH = Path(__file__).resolve().parent.parent / "data" / "bathy" / "seamarks.json"
HAZARDS_PATH = Path(__file__).resolve().parent.parent / "data" / "bathy" / "hazards.json"
MOORINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "bathy" / "moorings.json"
FARMS_PATH = Path(__file__).resolve().parent.parent / "data" / "bathy" / "marine_farms.json"

# ── 27/07/2026 (consigne armateur, vidéo Drenec) — ZONES DE CULTURE MARINE
# (parcs à huîtres, bouchots, fermes marines) : JAMAIS traversées, même en
# eau, même en dernier recours. Chaque polygone est couvert par un semis de
# disques interdits (pas 70 m, rayon 60 m → interdit l'intérieur + ~50 m de
# garde autour) ; les fermes ponctuelles (nœud OSM) ont un rayon fixe.
R_FARM_NODE_M = 100.0
R_FARM_COVER_M = 60.0
_FARM_COVER_STEP_M = 70.0


def _point_in_poly(lat: float, lng: float, poly: list[list[float]]) -> bool:
    """Ray casting — poly = [[lat, lng], ...] (anneau, fermé ou non)."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i][0], poly[i][1]
        yj, xj = poly[j][0], poly[j][1]
        if (yi > lat) != (yj > lat) and \
                lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _farm_cover(poly: list[list[float]]) -> list[tuple[float, float, float]]:
    """Semis de disques couvrant l'intérieur + le bord d'un polygone de parc."""
    lats_p = [p[0] for p in poly]
    lngs_p = [p[1] for p in poly]
    lat0, lat1 = min(lats_p), max(lats_p)
    lng0, lng1 = min(lngs_p), max(lngs_p)
    mlng = max(1.0, 111_320.0 * math.cos(math.radians((lat0 + lat1) / 2)))
    step_lat = _FARM_COVER_STEP_M / 110_574.0
    step_lng = _FARM_COVER_STEP_M / mlng
    # Sommets (bord) + centroïde (petits parcs plus fins que le pas).
    out: list[tuple[float, float, float]] = [
        (p[0], p[1], R_FARM_COVER_M) for p in poly
    ]
    out.append((sum(lats_p) / len(lats_p), sum(lngs_p) / len(lngs_p), R_FARM_COVER_M))
    la = lat0
    while la <= lat1:
        lo = lng0
        while lo <= lng1:
            if _point_in_poly(la, lo, poly):
                out.append((la, lo, R_FARM_COVER_M))
            lo += step_lng
        la += step_lat
    return out

# ── 26/07/2026 (demande armateur) — ZONES DE MOUILLAGE interdites ─────────
# Disque interdit autour de chaque bouée de mouillage (route qui slalomait
# entre les bouées de Larmor-Baden). Exemption : bouées proches (< 400 m) du
# départ/de l'arrivée (on mouille, ou on quitte son mouillage). Si AUCUNE
# route n'existe sans traverser les mouillages, le routeur ré-essaie avec
# les mouillages OUVERTS + avertissement (contextvar ci-dessous).
R_MOORING_M = 45.0
MOORING_EXEMPT_M = 400.0
import contextvars  # noqa: E402
MOORINGS_OPEN = contextvars.ContextVar("sm_moorings_open", default=False)
# 27/07/2026 (analyse vidéo 15h45) — le « dernier recours » est désormais
# ÉTAGÉ : d'abord mouillages ouverts SEULS (MOORINGS_OPEN), puis seulement
# si nécessaire les règles de CÔTÉ latéral levées (SIDE_RULES_OPEN). Avant,
# un seul mode levait tout d'un coup (côtés + écart minimal + mouillages) →
# routes SUR les balises (Holavre à 11 m, bouée n°6) et hors des chenaux.
SIDE_RULES_OPEN = contextvars.ContextVar("sm_side_rules_open", default=False)
# 10/08/2026 (consigne armateur, Moteur D UNIQUEMENT) — MODE « côté des
# latérales ISOLÉES par asymétrie bathymétrique ». Activé exclusivement par
# l'algo signalmar.v4 (Moteur D) le temps d'un calcul : les Moteurs A, B et
# C restent STRICTEMENT inchangés (caches séparés, cf. _mark_dir).
ISOLATED_SIDE_BATHY = contextvars.ContextVar("sm_isolated_side_bathy", default=False)
# 11/08/2026 (consigne armateur, Moteur E UNIQUEMENT — signalmar.v5) — CÔTÉ
# ABSOLU : « il y a encore des ratées de balises » (couple très écarté du
# chenal de Vannes, rouge recoupée à 139 m dans 4 m d'eau). Sous ce mode,
# le demi-disque interdit du mauvais côté est PLEIN (sans condition de
# fond) pour les isolées confiantes ET pour les couples (rayon ≤ 0,8 ×
# l'écartement, plafond 200 m). Moteurs A/B/C/D STRICTEMENT inchangés.
SIDE_ABSOLUTE = contextvars.ContextVar("sm_side_absolute", default=False)
# 13/08/2026 (consigne armateur, Moteur F UNIQUEMENT — signalmar.v6) — le
# Moteur E est FIGÉ à cette date. Le Moteur F démarre comme copie EXACTE du
# Moteur E ; toutes les corrections futures (balises de chenal à l'arrivée,
# « la Truie » au départ d'Arradon…) devront être gardées par CE contextvar
# afin de ne JAMAIS modifier le comportement des Moteurs A/B/C/D/E.
SIDE_ABSOLUTE_V6 = contextvars.ContextVar("sm_side_absolute_v6", default=False)
# 25/08/2026 — règles de COHÉRENCE de direction des chenaux (faux couples,
# héritage de voisinage). Armées UNIQUEMENT par les moteurs dont le document
# porte ``params.dir_coherence`` (Moteur G) : F reste au comportement validé.
DIR_COHERENCE_V6 = contextvars.ContextVar("sm_dir_coherence_v6", default=False)
# Garde anti-récursion de l'héritage de direction (25/08).
_DIR_INFER_GUARD = contextvars.ContextVar("sm_dir_infer_guard", default=False)
# 27/08/2026 (perf Moteur F « route < 10 s ») — cache de ``rasterize_blocked``
# pour la durée d'UN calcul v6 : les réparations sidefix relancent des
# ``compute_route`` locaux sur les MÊMES fenêtres (252 rasterisations ≈ 2,7 s
# sur Lorient → Golfe). None (défaut) = désactivé : Moteurs A-E strictement
# inchangés. Le masque retourné n'est jamais muté par les appelants
# (consommé via ``nav &= ~blocked``).
RASTER_CACHE: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "sm_raster_cache", default=None)

# 27/07/2026 — ZONES DE MOUILLAGE SURFACIQUES (seamark:type=anchorage,
# ingest_anchorages.py) : mêmes règles que les bouées de mouillage
# (exemption départ/arrivée < 400 m, ouvertes en dernier recours).
ANCHORAGES_PATH = Path(__file__).resolve().parent.parent / "data" / "bathy" / "anchorages.json"
R_ANCH_NODE_M = 80.0

# Rayons des zones interdites (mètres).
R_LATERAL_M = 60.0          # demi-disque du mauvais côté d'une latérale
R_CARDINAL_M = 120.0        # rayon « clearance » toutes directions (redressement)
# 29/07/2026 (retour test en mer — « route passée au NORD d'une cardinale
# SUD ») : IALA impose de passer du côté NOMMÉ de la marque. Le demi-disque
# interdit CÔTÉ DANGER passe à 300 m pour les cardinales dont la direction est
# connue — à 120 m, l'A* trouvait de l'eau profonde juste derrière la balise
# et passait du mauvais côté. Les cardinales de direction inconnue gardent le
# disque plein de 120 m (un disque plein de 300 m fermerait des passes
# légitimes), et le rayon « clearance » du redressement reste à 120 m (il
# s'applique de TOUS les côtés, y compris le côté sain).
R_CARDINAL_WRONG_SIDE_M = 300.0
R_ISOLATED_M = 80.0         # disque complet danger isolé
R_SPECIAL_M = 40.0          # écart léger marque spéciale
# 26/07/2026 (retour armateur, La Vilaine : route à 7 m de la bouée n°8) —
# ÉCART MINIMAL TOUTES DIRECTIONS autour des latérales/cardinales : même du
# « bon » côté on ne frôle pas une bouée quand il y a la place. Adaptatif
# (≤ 25 % de l'écartement du couple) pour ne jamais fermer un chenal étroit.
R_MARK_STANDOFF_M = 60.0
# 28/07/2026 (consigne support/armateur) — PLANCHER du standoff : ≤ 25 % de
# l'écartement du couple autorisait géométriquement le passage « sur la
# balise » quand le rayon tombait sous la maille (n°6 du chenal de Vannes :
# couple à 78 m → 19,4 m < maille 20 m → disque SAUTÉ). Le standoff ne
# descend plus jamais sous ce plancher et n'est plus jamais sauté en maille
# fine (le disque bloque au moins la cellule de la balise).
R_MARK_STANDOFF_MIN_M = 15.0
# 23/07/2026 (règle armateur) — en ZONE PEU PROFONDE (fond < tirant d'eau +
# marge + 2 m), le balisage latéral est respecté SCRUPULEUSEMENT : le mauvais
# côté d'une latérale est interdit jusqu'à 200 m là où c'est peu profond. En
# eaux profondes, l'écart standard suffit (passage validé Teignouse).
R_LATERAL_STRICT_M = 200.0
# 22/07/2026 (lot armateur) — DANGERS : roches (couvrantes/découvrantes/à
# fleur d'eau/submergées), épaves dangereuses ou de profondeur inconnue,
# obstructions. Disque complet.
R_HAZARD_M = 60.0
# Catégories d'épave TOUJOURS bloquées.
WRECK_DANGEROUS = {"dangerous", "hull_showing", "mast_showing", "distributed_remains"}

# Champ « distance au large » : calculé UNE FOIS sur une grille décimée.
_SHELTER_STEP = 8           # 20 m × 8 = 160 m par cellule — suffisant
# 22/07/2026 — distance max de recherche du couple rouge/verte d'une latérale
# (les paires d'un chenal sont espacées de 40-250 m de part et d'autre).
_PAIR_MAX_M = 350.0
# Distance max de recherche de la latérale du même côté (axe du chenal).
_AXIS_MAX_M = 600.0
# ── 10/08/2026 (consigne armateur : « priorité absolue au sens conventionnel,
# les moteurs ne passent jamais du bon côté d'une latérale ISOLÉE ») ────────
# Le côté de passage d'une latérale est INVARIANT au sens de parcours : une
# verte dont le chenal est à l'ouest se passe à l'OUEST dans les deux sens
# (« à tribord en entrant » = « à bâbord en sortant » = le même côté absolu).
# Pour une latérale SANS couple, ce côté est déterminé par l'ASYMÉTRIE
# BATHYMÉTRIQUE : une latérale marque une limite chenal/danger, l'eau
# navigable (profonde) est d'un côté, le danger (peu profond/découvrant) de
# l'autre. Signal bien plus fiable que le gradient « distance au large »
# (faux de 90° dans les chenaux étroits — bug chenal de Vannes, Vilaine).
# Rayons d'échantillonnage du fond de part et d'autre de la balise (m).
_NAV_SIDE_RADII = (30.0, 60.0, 100.0, 150.0, 200.0)
# Écart minimal de score (fond moyen écrêté, m) pour trancher le côté.
_NAV_SIDE_MIN_GAP_M = 1.5
# Le côté DANGER doit être réellement peu profond (score < seuil) : évite de
# « trancher » une asymétrie fortuite en eau franche.
_NAV_SIDE_DANGER_MAX_M = 6.0


class SeamarkIndex:
    def __init__(self, grid: BathyGrid) -> None:
        data = json.loads(SEAMARKS_PATH.read_text())
        self.marks: list[dict] = data["marks"]
        self.fetched_at: str = data.get("fetched_at", "")
        # 22/07/2026 — dangers (roches/épaves/obstructions, ingest_hazards.py).
        self.hazards: list[dict] = []
        if HAZARDS_PATH.exists():
            self.hazards = json.loads(HAZARDS_PATH.read_text()).get("hazards", [])
        # 26/07/2026 — bouées de mouillage (ingest_moorings.py).
        self.moorings: list[dict] = []
        if MOORINGS_PATH.exists():
            self.moorings = json.loads(MOORINGS_PATH.read_text()).get("moorings", [])
        # 27/07/2026 — zones de culture marine (ingest_marine_farms.py) :
        # semis de disques interdits (lat, lng, rayon_m), np.ndarray (N, 3).
        self.farm_circles: np.ndarray = np.zeros((0, 3), dtype=np.float64)
        if FARMS_PATH.exists():
            circles: list[tuple[float, float, float]] = []
            for f in json.loads(FARMS_PATH.read_text()).get("farms", []):
                poly = f.get("poly")
                if poly and len(poly) >= 3:
                    circles.extend(_farm_cover(poly))
                elif f.get("lat") is not None:
                    circles.append((f["lat"], f["lng"], R_FARM_NODE_M))
            if circles:
                self.farm_circles = np.asarray(circles, dtype=np.float64)
        # 27/07/2026 — zones de mouillage surfaciques (ingest_anchorages.py),
        # même représentation en semis de disques que les parcs.
        self.anchorage_circles: np.ndarray = np.zeros((0, 3), dtype=np.float64)
        if ANCHORAGES_PATH.exists():
            circles_a: list[tuple[float, float, float]] = []
            for z in json.loads(ANCHORAGES_PATH.read_text()).get("anchorages", []):
                poly = z.get("poly")
                if poly and len(poly) >= 3:
                    circles_a.extend(_farm_cover(poly))
                elif z.get("lat") is not None:
                    circles_a.append((z["lat"], z["lng"], R_ANCH_NODE_M))
            if circles_a:
                self.anchorage_circles = np.asarray(circles_a, dtype=np.float64)
        self._grid = grid
        self._shelter: Optional[np.ndarray] = None  # champ décimé
        self._gy: Optional[np.ndarray] = None
        self._gx: Optional[np.ndarray] = None
        # 23/07/2026 (extension Atlantique) — INDEX SPATIAL des latérales :
        # _pair_of/_same_side_axis passaient de O(n) à O(n²) avec ~10 000
        # balises sur toute la façade. Seaux de 0,02° (~2,2 km ≫ rayons de
        # recherche 350/600 m) → voisinage 3×3 suffisant.
        self._lat_buckets: dict[tuple[int, int], list[dict]] = {}
        for m in self.marks:
            if m.get("kind") == "lateral":
                k = (int(m["lat"] * 50), int(m["lng"] * 50))
                self._lat_buckets.setdefault(k, []).append(m)

    def _laterals_near(self, lat: float, lng: float) -> list[dict]:
        """Latérales dans le voisinage 3×3 seaux (~±2 km) du point."""
        kr, kc = int(lat * 50), int(lng * 50)
        out: list[dict] = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                out.extend(self._lat_buckets.get((kr + dr, kc + dc), ()))
        return out

    @staticmethod
    def hazard_blocks(h: dict, min_depth: float) -> bool:
        """Un danger bloque-t-il la route ? Roches : TOUJOURS (règle armateur —
        couvrantes/découvrantes = à éviter à tout prix ; le MNT 20 m peut rater
        une tête de roche). Épaves/obstructions : dangereuses, profondeur
        inconnue, ou profondeur < seuil + 1 m de garde."""
        kind = h.get("kind")
        if kind == "rock":
            return True
        cat = h.get("category", "")
        depth = h.get("depth_m")
        if kind == "wreck" and cat in WRECK_DANGEROUS:
            return True
        if cat == "non-dangerous" and depth is None:
            return False
        if depth is not None:
            return float(depth) < min_depth + 1.0
        return True  # profondeur inconnue → prudence

    # ── Champ « distance au large » (BFS à travers l'eau) ───────────────
    def _build_shelter(self) -> None:
        g = self._grid
        step = _SHELTER_STEP
        depth = np.asarray(g.grid[::step, ::step], dtype=np.float32)
        water = np.isfinite(depth) & (depth > 0.0)
        # Graines = LE LARGE. 23/07/2026 (généralisation Atlantique) : toute
        # BORDURE de grille en eau FRANCHE (> 5 m) — Manche au nord, océan à
        # l'ouest/au sud. Le seuil 5 m exclut les rivières/estuaires qui
        # sortent de l'emprise (Vilaine, Loire amont) dont le semis
        # contaminerait le champ (bug du 21/07 : sens conventionnels
        # inversés, entrée du Golfe fermée). Comportement zone pilote
        # inchangé : ses bordures profondes sont le sud et l'ouest.
        deep = water & (depth > 5.0)
        seeds = np.zeros_like(water)
        seeds[0, :] = deep[0, :]           # bord nord
        seeds[-1, :] = deep[-1, :]         # bord sud
        seeds[:, 0] = deep[:, 0]           # bord ouest
        seeds[:, -1] = deep[:, -1]         # bord est (Manche au nord-est)
        # BFS géodésique : dilatations successives restreintes à l'eau.
        dist = np.full(water.shape, np.inf, dtype=np.float32)
        dist[seeds] = 0.0
        frontier = seeds.copy()
        reached = seeds.copy()
        st = ndimage.generate_binary_structure(2, 2)
        it = 0
        max_it = water.shape[0] + water.shape[1]
        while frontier.any() and it < max_it:
            it += 1
            nxt = ndimage.binary_dilation(reached, structure=st) & water & ~reached
            if not nxt.any():
                break
            dist[nxt] = it
            reached |= nxt
            frontier = nxt
        # Terre / cellules non atteintes : PROPAGER la valeur de l'eau la
        # plus proche (sinon le gradient près des côtes pointe vers la terre
        # — bug du 21/07 : sens conventionnels faussés aux abords des rochers).
        if np.isfinite(dist).any():
            invalid = ~np.isfinite(dist)
            if invalid.any():
                _, (ir, ic) = ndimage.distance_transform_edt(invalid, return_indices=True)
                dist = dist[ir, ic]
        else:
            dist = np.zeros_like(dist)
        smooth = ndimage.gaussian_filter(dist, sigma=4.0)
        gy, gx = np.gradient(smooth)  # gy: vers le sud (lignes+), gx: vers l'est
        self._shelter = smooth
        self._gy, self._gx = gy, gx

    def conventional_dir(self, lat: float, lng: float) -> Optional[tuple[float, float]]:
        """Direction conventionnelle locale (unitaire, composantes est/nord) —
        pointe vers l'ABRI (distance au large croissante). None si indéfini."""
        if self._shelter is None:
            self._build_shelter()
        g = self._grid
        r, c = g.rc(lat, lng)
        rr = int(np.clip(r // _SHELTER_STEP, 0, self._gy.shape[0] - 1))
        cc = int(np.clip(c // _SHELTER_STEP, 0, self._gy.shape[1] - 1))
        de = float(self._gx[rr, cc])          # +est
        dn = float(-self._gy[rr, cc])         # lignes croissent vers le sud → nord = -gy
        n = math.hypot(de, dn)
        if n < 1e-9:
            return None
        return de / n, dn / n

    # ── 22/07/2026 (bug armateur « je ne peux faire aucune route ») ──────
    # Dans un chenal ÉTROIT (chenal de Vannes), le gradient « distance au
    # large » est bruité (cap mesuré 121° pour un chenal orienté ≈ 25°) : les
    # demi-disques interdits pivotent et FERMENT le chenal. Or les latérales
    # vont par COUPLES rouge/verte de part et d'autre du chenal, et la règle
    # IALA A (« rouge à bâbord, verte à tribord en entrant ») fixe le sens
    # conventionnel SANS ambiguïté à partir du seul vecteur rouge→verte :
    # D = ce vecteur tourné de -90° (la verte reste à droite). Bien plus
    # fiable que le gradient — utilisé en priorité quand un couple existe.
    def _pair_of(self, m: dict) -> Optional[dict]:
        """Latérale de catégorie OPPOSÉE la plus proche (≤ _PAIR_MAX_M) —
        le « couple » rouge/verte qui borde un chenal. None si isolée.

        11/08/2026 (Moteur E — SIDE_ABSOLUTE, cache séparé) : un vrai couple
        est RÉCIPROQUE — chacune est l'opposée la plus proche de l'autre.
        Sans ce test, les chenaux denses en COUDE créaient des FAUX couples
        le long de l'axe (Crouesty : la verte du coude « appariée » à la
        rouge n°8 à 290 m EN AMONT, alors que n°8 forme sa porte avec No5 à
        92 m → fausses portes + faux côtés qui SCELLAIENT l'entrée).
        Critère purement géométrique, valable partout, sans exception."""
        v5 = SIDE_ABSOLUTE.get()
        ck = "_pair_v5" if v5 else "_pair"
        if ck in m:
            return m[ck]
        best = self._nearest_opposite(m)
        if v5 and best is not None and self._nearest_opposite(best) is not m:
            best = None
        m[ck] = best
        return best

    def _nearest_opposite(self, m: dict) -> Optional[dict]:
        if "_nopp" in m:
            return m["_nopp"]
        cat = m.get("category")
        other = "port" if cat == "starboard" else "starboard"
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        best: Optional[dict] = None
        best_d2 = _PAIR_MAX_M ** 2
        for o in self._laterals_near(m["lat"], m["lng"]):
            if o is m or o.get("category") != other:
                continue
            de_ = (o["lng"] - m["lng"]) * mlng
            dn_ = (o["lat"] - m["lat"]) * 110_574.0
            d2 = de_ * de_ + dn_ * dn_
            if d2 < best_d2:
                best_d2, best = d2, o
        m["_nopp"] = best
        return best

    def _nearest_lateral_m(self, m: dict) -> float:
        """Distance (m) à la latérale la plus proche (toutes catégories,
        ≤ _PAIR_MAX_M) — inf si vraiment seule. Sert de PLAFOND DE DENSITÉ
        (11/08, Moteur E) : dans un chenal dense (balises tous les 60-120 m,
        ex. Crouesty), les zones de mauvais côté à l'échelle 200 m se
        recouvrent mutuellement et SCELLENT le chenal — le rayon est plafonné
        à 0,6 × cette distance. Règle d'échelle universelle, sans exception
        de terrain."""
        if "_nld" in m:
            return m["_nld"]
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        best = float("inf")
        for o in self._laterals_near(m["lat"], m["lng"]):
            if o is m:
                continue
            de_ = (o["lng"] - m["lng"]) * mlng
            dn_ = (o["lat"] - m["lat"]) * 110_574.0
            d = math.hypot(de_, dn_)
            if d < best:
                best = d
        m["_nld"] = best
        return best

    def _nearest_other_lateral_m(self, m: dict) -> float:
        """Distance (m) à la latérale la plus proche HORS partenaire de
        couple (11/08 soir, Moteur E — bug armateur « No2 pas respectée ») :
        le plafond de densité 0,6 × voisine utilisait le PARTENAIRE lui-même
        (No1 à 199 m) et écrasait le rayon 0,8 × écartement (159 m) → route
        acceptée à 127 m du MAUVAIS côté. La densité pertinente pour un
        couple = les AUTRES balises du chenal. inf si aucune."""
        if "_nld_x5" in m:
            return m["_nld_x5"]
        pair = self._pair_of(m)
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        best = float("inf")
        for o in self._laterals_near(m["lat"], m["lng"]):
            if o is m or o is pair:
                continue
            de_ = (o["lng"] - m["lng"]) * mlng
            dn_ = (o["lat"] - m["lat"]) * 110_574.0
            d = math.hypot(de_, dn_)
            if d < best:
                best = d
        m["_nld_x5"] = best
        return best

    def _mark_dir(self, m: dict) -> Optional[tuple[float, float]]:
        """Direction conventionnelle pour UNE latérale.

        Chaîne HISTORIQUE (Moteurs A/B/C, inchangée) : couple rouge/verte
        le plus proche (≤ _PAIR_MAX_M) si disponible, sinon gradient.

        10/08/2026 — sous ISOLATED_SIDE_BATHY (Moteur D uniquement), une
        latérale ISOLÉE tente d'abord l'ASYMÉTRIE BATHYMÉTRIQUE (l'eau
        profonde = le chenal) avant le gradient. Cache séparé (_dir_v4) :
        les moteurs gelés ne voient JAMAIS la valeur du mode D."""
        if ISOLATED_SIDE_BATHY.get() or SIDE_ABSOLUTE.get():
            ck = "_dir_v5" if SIDE_ABSOLUTE.get() else "_dir_v4"
            if ck in m:
                return m[ck]
            d = self.mark_dir_confident(m)
            if d is None:
                d = self.conventional_dir(m["lat"], m["lng"])
            m[ck] = d
            return d
        if "_dir" in m:
            return m["_dir"]
        d = self._pair_dir(m)
        if d is None:
            d = self.conventional_dir(m["lat"], m["lng"])
        m["_dir"] = d
        return d

    def mark_dir_confident(self, m: dict) -> Optional[tuple[float, float]]:
        """Direction conventionnelle FIABLE seulement (couple rouge/verte ou
        asymétrie bathymétrique nette) — None si aucun signal sûr
        (l'appelant choisit alors son propre repli). Utilisé par les
        Moteurs D/E pour ne jamais trancher un côté sur un signal bruité."""
        if m.get("category") not in ("port", "starboard"):
            return None
        ck = "_dir_conf_v5" if SIDE_ABSOLUTE.get() else "_dir_conf"
        # 26/08/2026 — le cache v5 ne doit JAMAIS court-circuiter le mode V6
        # (sinon un None v5 mis en cache par un appel A-E empêche l'héritage
        # v6 : bug Kerpenhir/Les Rouzins). On ne retourne le cache v5 que
        # hors mode V6 ; en mode V6 on le réutilise comme base seulement.
        v6_mode = DIR_COHERENCE_V6.get() and not _DIR_INFER_GUARD.get()
        if v6_mode and "_dir_conf_v6" in m:
            return m["_dir_conf_v6"]
        if not v6_mode and ck in m:
            return m[ck]
        if ck in m:
            d = m[ck]
        else:
            d = self._pair_dir(m)
            if d is None:
                w = self.navigable_side(m)
                if w is not None:
                    we, wn = w
                    # Verte : la route passe à BÂBORD de D → bâbord(D) = w
                    # ⇒ D = w tourné de −90°. Rouge : tribord(D) = w ⇒ +90°.
                    d = (wn, -we) if m["category"] == "starboard" else (-wn, we)
            m[ck] = d
        # 25/08/2026 (Moteur F UNIQUEMENT, bugs armateur Lorient/Croisic/
        # Kerpenhir) — deux failles, deux replis SÛRS :
        # 1. FAUX COUPLE : « La Petite Jument » (rouge, chenal de Lorient)
        #    est appariée à une verte du chenal voisin de Kernevel → côté
        #    requis INVERSÉ. Si le côté requis contredit le CÔTÉ NAVIGABLE
        #    mesuré par la bathy (eau profonde), la BATHY PRIME.
        # 2. latérale SANS direction (ni couple ni signal bathy — fréquent
        #    en ATL100) : elle HÉRITE du consensus des latérales fiables
        #    voisines (« Les Rouzins », « Kerpenhir » n'étaient JAMAIS
        #    imposées) — jamais utilisé pour CONTREDIRE un signal existant.
        # Gated SIDE_ABSOLUTE_V6 : Moteurs A-E strictement inchangés.
        if v6_mode:
            tok = _DIR_INFER_GUARD.set(True)
            try:
                if d is not None:
                    w = self.navigable_side(m)
                    if w is not None:
                        de, dn = d
                        u = (dn, -de) if m["category"] == "port" else (-dn, de)
                        if u[0] * w[0] + u[1] * w[1] < 0.0:
                            we, wn = w
                            d = ((wn, -we) if m["category"] == "starboard"
                                 else (-wn, we))
                    else:
                        # 26/08 (bug Lorient « N° 4 ») — faux couple SANS
                        # signal bathy : si la direction du couple est
                        # OPPOSÉE au consensus des latérales fiables
                        # voisines, le consensus prime (même philosophie
                        # que le repli bathy ci-dessus).
                        cons = self._neighbor_dir_consensus(m)
                        if (cons is not None
                                and d[0] * cons[0] + d[1] * cons[1] < 0.0):
                            d = cons
                            m["_dir_v6_inferred"] = True
                else:
                    d = self._neighbor_dir_consensus(m)
                    if d is not None:
                        # marque héritée : fiabilité moindre (portée réduite
                        # côté réparation — cf. sidefix).
                        m["_dir_v6_inferred"] = True
            finally:
                _DIR_INFER_GUARD.reset(tok)
            m["_dir_conf_v6"] = d
            return d
        return d

    def _neighbor_dir_consensus(self, m: dict) -> Optional[tuple[float, float]]:
        """Consensus (moyenne normalisée) des directions conventionnelles
        FIABLES des ≤ 3 latérales les plus proches (≤ 1 000 m, hors la
        marque elle-même et son éventuel partenaire de couple)."""
        partner = self._pair_of(m)
        mlng = 111320.0 * math.cos(math.radians(m["lat"]))
        cands: list[tuple[float, dict]] = []
        for o in self._laterals_near(m["lat"], m["lng"]):
            if o is m or o is partner:
                continue
            if o.get("category") not in ("port", "starboard"):
                continue
            dist = math.hypot((o["lat"] - m["lat"]) * 111320.0,
                              (o["lng"] - m["lng"]) * mlng)
            if dist <= 1000.0:
                cands.append((dist, o))
        cands.sort(key=lambda t: t[0])
        se = sn = 0.0
        n = 0
        for _dist, o in cands:
            od = self.mark_dir_confident(o)
            if od is None:
                continue
            se += od[0]
            sn += od[1]
            n += 1
            if n >= 3:
                break
        norm = math.hypot(se, sn)
        if n == 0 or norm < 0.5:
            return None
        return (se / norm, sn / norm)

    def _pair_dir(self, m: dict) -> Optional[tuple[float, float]]:
        """Direction conventionnelle depuis le COUPLE rouge/verte (None si la
        latérale est isolée). Cf. note du 22/07 en tête de _pair_of."""
        cat = m.get("category")
        if cat not in ("port", "starboard"):
            return None
        o = self._pair_of(m)
        if o is None:
            return None
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        de_ = (o["lng"] - m["lng"]) * mlng
        dn_ = (o["lat"] - m["lat"]) * 110_574.0
        # w = vecteur ROUGE → VERTE (m→autre si m est rouge, inverse sinon).
        we, wn = (de_, dn_) if cat == "port" else (-de_, -dn_)
        # 22/07/2026 — couples EN QUINCONCE (décalés le long du chenal,
        # ex. entrée du port de Vannes) : w a une grosse composante
        # le long du chenal et D pivote de 60-90°. L'axe du chenal =
        # l'alignement des latérales du MÊME côté : on ne garde de w
        # que sa composante PERPENDICULAIRE à cet axe.
        axis = self._same_side_axis(m)
        if axis is not None:
            ae, an = axis
            dot = we * ae + wn * an
            pe, pn = we - dot * ae, wn - dot * an
            if math.hypot(pe, pn) >= 15.0:
                we, wn = pe, pn
        n = math.hypot(we, wn)
        if n < 1e-9:
            return None
        return (-wn / n, we / n)   # w tourné de -90° : verte à droite de D

    # ── 10/08/2026 — CÔTÉ NAVIGABLE d'une latérale ISOLÉE (bathymétrie) ──
    def _side_score(self, m: dict, ue: float, un: float) -> float:
        """Score de navigabilité du côté (ue, un) vu depuis la balise :
        moyenne des fonds écrêtés à [−2, 8] m (terre/hors grille = −2) sur
        3 azimuts (±25°) × rayons _NAV_SIDE_RADII — grille la plus FINE."""
        grid = get_grid() or self._grid
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        vals: list[float] = []
        for ang in (-25.0, 0.0, 25.0):
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            de, dn = ue * ca - un * sa, ue * sa + un * ca
            for r in _NAV_SIDE_RADII:
                d = grid.depth_at(m["lat"] + dn * r / 110_574.0,
                                  m["lng"] + de * r / mlng)
                vals.append(-2.0 if d is None else min(max(float(d), -2.0), 8.0))
        return sum(vals) / len(vals)

    def navigable_side(self, m: dict) -> Optional[tuple[float, float]]:
        """Côté NAVIGABLE d'une latérale (vecteur unitaire est/nord depuis la
        balise, pointant vers l'eau où la route DOIT passer) — invariant au
        sens de parcours. None si l'asymétrie bathymétrique est ambiguë.
        AUCUNE exception de terrain (11/08, consigne armateur : les règles
        doivent fonctionner partout en Europe) :

        1. axe du chenal connu → comparaison des deux côtés perpendiculaires ;
        2. sinon balayage de 12 azimuts : le secteur le moins profond est le
           DANGER, la route passe à l'opposé (si l'écart est net)."""
        if m.get("category") not in ("port", "starboard"):
            return None
        # 11/08 soir (Moteur E) — cache séparé : le mode E ajoute un repli
        # « chenal lointain » (_far_channel_side) que le Moteur D figé ne
        # doit jamais voir.
        ck = "_navside_v5" if SIDE_ABSOLUTE.get() else "_navside"
        if ck in m:
            return m[ck]
        out: Optional[tuple[float, float]] = None
        axis = self._same_side_axis(m)
        if axis is not None:
            ae, an = axis
            cands = [(-an, ae), (an, -ae)]
            s0, s1 = (self._side_score(m, *cands[0]),
                      self._side_score(m, *cands[1]))
            deep, shallow = (0, 1) if s0 >= s1 else (1, 0)
            scores = (s0, s1)
            if (scores[deep] - scores[shallow] >= _NAV_SIDE_MIN_GAP_M
                    and scores[shallow] < _NAV_SIDE_DANGER_MAX_M):
                out = cands[deep]
        else:
            cands = [(math.sin(math.radians(b)), math.cos(math.radians(b)))
                     for b in range(0, 360, 30)]
            scores = [self._side_score(m, ue, un) for ue, un in cands]
            i_min = min(range(len(scores)), key=scores.__getitem__)
            w = (-cands[i_min][0], -cands[i_min][1])
            s_opp = self._side_score(m, *w)
            if (s_opp - scores[i_min] >= _NAV_SIDE_MIN_GAP_M
                    and scores[i_min] < _NAV_SIDE_DANGER_MAX_M):
                out = w
        if out is None and SIDE_ABSOLUTE.get():
            out = self._far_channel_side(m)
        m[ck] = out
        return out

    # ── 11/08 soir (Moteur E — bug armateur « Grand Mouton pas respectée »)
    # Une latérale posée SUR son danger (roche au pied de la bouée) noie
    # l'asymétrie proche : les échantillons à 30-60 m touchent la roche de
    # TOUS les côtés (Grand Mouton : 2,4 m à l'ouest à 30 m alors que le
    # chenal de Port-Navalo, 24 m, est à 150 m ouest) → navigable_side
    # ambigu → aucun blocage de côté. Repli CHAMP LOINTAIN, universel :
    # 1. il existe un vrai danger AU PIED de la bouée (fond < 5 m à ≤ 60 m) ;
    # 2. le côté le plus profond à 100-200 m (écrêtage 20 m : on cherche un
    #    CHENAL, pas une fosse) domine son opposé d'au moins 4 m.
    # → le chenal est de ce côté, la route passe là. Moteur E uniquement.
    _FAR_RADII = (100.0, 150.0, 200.0)

    def _far_score(self, m: dict, ue: float, un: float) -> float:
        """Score « chenal lointain » du côté (ue, un) : moyenne des fonds
        écrêtés à [−2, 20] m sur 3 azimuts (±25°) × rayons 100-200 m."""
        grid = get_grid() or self._grid
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        vals: list[float] = []
        for ang in (-25.0, 0.0, 25.0):
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            de, dn = ue * ca - un * sa, ue * sa + un * ca
            for r in self._FAR_RADII:
                d = grid.depth_at(m["lat"] + dn * r / 110_574.0,
                                  m["lng"] + de * r / mlng)
                vals.append(-2.0 if d is None else min(max(float(d), -2.0), 20.0))
        return sum(vals) / len(vals)

    def _far_channel_side(self, m: dict) -> Optional[tuple[float, float]]:
        grid = get_grid() or self._grid
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        # 1. danger au pied de la bouée ? (fond mini < 5 m dans un rayon 60 m)
        near_min: Optional[float] = None
        for r in (0.0, 30.0, 60.0):
            for b in range(0, 360, 45):
                if r == 0.0 and b:
                    continue
                ue, un = math.sin(math.radians(b)), math.cos(math.radians(b))
                d = grid.depth_at(m["lat"] + un * r / 110_574.0,
                                  m["lng"] + ue * r / mlng)
                if d is not None and (near_min is None or float(d) < near_min):
                    near_min = float(d)
        if near_min is None or near_min >= 5.0:
            return None
        # 2. côté au chenal le plus net (axe du chenal si connu, sinon 12
        #    azimuts) — écart minimal 4 m avec le côté opposé.
        axis = self._same_side_axis(m)
        if axis is not None:
            ae, an = axis
            cands = [(-an, ae), (an, -ae)]
        else:
            cands = [(math.sin(math.radians(b)), math.cos(math.radians(b)))
                     for b in range(0, 360, 30)]
        scores = [self._far_score(m, ue, un) for ue, un in cands]
        i_max = max(range(len(scores)), key=scores.__getitem__)
        we, wn = cands[i_max]
        s_opp = self._far_score(m, -we, -wn)
        if scores[i_max] - s_opp < 4.0:
            return None
        return (we, wn)

    def _same_side_axis(self, m: dict) -> Optional[tuple[float, float]]:
        """Axe local du chenal ≈ direction (unitaire, ±180°) vers la latérale
        du MÊME côté la plus proche (≤ _AXIS_MAX_M). None si isolée."""
        if "_axis" in m:
            return m["_axis"]
        cat = m.get("category")
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        best: Optional[tuple[float, float]] = None
        best_d2 = _AXIS_MAX_M ** 2
        for o in self._laterals_near(m["lat"], m["lng"]):
            if o is m or o.get("category") != cat:
                continue
            de_ = (o["lng"] - m["lng"]) * mlng
            dn_ = (o["lat"] - m["lat"]) * 110_574.0
            d2 = de_ * de_ + dn_ * dn_
            if 100.0 <= d2 < best_d2:   # ≥ 10 m : ignore les doublons OSM
                best_d2, best = d2, (de_, dn_)
        out = None
        if best is not None:
            n = math.hypot(*best)
            out = (best[0] / n, best[1] / n)
        m["_axis"] = out
        return out

    # ── 23/07/2026 — Profondeur du MAUVAIS CÔTÉ d'une latérale (règle
    # « balisage strict en eaux peu profondes »). On échantillonne le fond du
    # côté INTERDIT (perpendiculaire au sens conventionnel) : si ce côté est
    # profond (ex. balise du milieu de la Teignouse, validée terrain), l'écart
    # standard suffit ; s'il est peu profond, balisage STRICT. Caché/marque.
    def _wrong_side_depth(self, m: dict) -> Optional[float]:
        # 10/08 — caches séparés par mode : la direction (donc le mauvais
        # côté) diffère entre moteurs gelés, Moteur D et Moteur E.
        if SIDE_ABSOLUTE.get():
            ck = "_wrong_depth_v5"
        elif ISOLATED_SIDE_BATHY.get():
            ck = "_wrong_depth_v4"
        else:
            ck = "_wrong_depth"
        if ck in m:
            return m[ck]
        best: Optional[float] = None
        g = self._grid
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        d2 = self._mark_dir(m)
        if d2 is None:
            samples = ((100, 0), (-100, 0), (0, 100), (0, -100))  # anneau prudent
        else:
            de, dn = d2
            # Perpendiculaire côté interdit : droite du sens conventionnel pour
            # une verte (starboard), gauche pour une rouge (port).
            if m.get("category") == "starboard":
                pe, pn = dn, -de
            else:
                pe, pn = -dn, de
            samples = tuple((pe * r, pn * r) for r in (40.0, 90.0, 150.0))
        for dxe, dyn in samples:
            d = g.depth_at(m["lat"] + dyn / 110_574.0, m["lng"] + dxe / mlng)
            if d is not None and (best is None or d < best):
                best = d
        m[ck] = best
        return best

    def _lateral_strict(self, m: dict, strict_depth: Optional[float]) -> bool:
        """True si le MAUVAIS CÔTÉ de la latérale est peu profond → strict."""
        if strict_depth is None:
            return False
        zd = self._wrong_side_depth(m)
        return zd is not None and zd < strict_depth

    # ── Rasterisation des interdits dans une fenêtre du moteur ──────────
    def rasterize_blocked(
        self,
        lats: np.ndarray,
        lngs: np.ndarray,
        m_per_deg_lng: float,
        m_per_deg_lat: float,
        min_depth: float = 0.0,
        strict_depth: Optional[float] = None,
        depth: Optional[np.ndarray] = None,
        strict_exempt: Optional[tuple] = None,
    ) -> np.ndarray:
        """Masque bool (len(lats), len(lngs)) des cellules interdites par le
        balisage ET les dangers (roches/épaves/obstructions — 22/07/2026).
        lats décroissantes, lngs croissantes (fenêtre A*)."""
        # 27/08/2026 (perf) — cache par fenêtre, gated v6 (cf. RASTER_CACHE).
        cache = RASTER_CACHE.get()
        cache_key = None
        if cache is not None:
            try:
                cache_key = (
                    len(lats), len(lngs),
                    float(lats[0]), float(lats[-1]),
                    float(lngs[0]), float(lngs[-1]),
                    round(float(min_depth), 4),
                    None if strict_depth is None else round(float(strict_depth), 4),
                    None if strict_exempt is None
                    else tuple(tuple(p) for p in strict_exempt),
                    MOORINGS_OPEN.get(), SIDE_RULES_OPEN.get(),
                    SIDE_ABSOLUTE.get(), SIDE_ABSOLUTE_V6.get(),
                    ISOLATED_SIDE_BATHY.get(), DIR_COHERENCE_V6.get(),
                )
            except TypeError:
                cache_key = None
            if cache_key is not None:
                hit = cache.get(cache_key)
                if hit is not None:
                    return hit
        ny, nx = len(lats), len(lngs)
        blocked = np.zeros((ny, nx), dtype=bool)
        # 22/07/2026 (bug armateur) — les interdits BALISES sont rasterisés à
        # part : le COULOIR entre chaque couple rouge/verte (= le chenal, eau
        # saine par définition) est ensuite re-creusé dans ce calque, sans
        # jamais rouvrir un danger (roche/épave).
        marks_blocked = np.zeros((ny, nx), dtype=bool)
        lat_n, lat_s = float(lats[0]), float(lats[-1])
        lng_w, lng_e = float(lngs[0]), float(lngs[-1])
        pad = 0.01  # ~1 km : inclure les balises juste hors fenêtre
        cy = abs(float(lats[1] - lats[0])) * m_per_deg_lat if ny > 1 else 20.0
        cx = abs(float(lngs[1] - lngs[0])) * m_per_deg_lng if nx > 1 else 20.0

        def _disc(lat: float, lng: float, radius: float) -> Optional[tuple]:
            """Sous-fenêtre + masque disque autour d'un point. None si hors zone."""
            ry = max(1, int(math.ceil(radius / cy)))
            rx = max(1, int(math.ceil(radius / cx)))
            # 27/07 (perf) — min/max scalaires : np.clip sur scalaire coûtait
            # ~40 % du rasterize (500 k appels avec les parcs + mouillages).
            br = min(max(int(np.searchsorted(-lats, -lat)), 0), ny - 1)
            bc = min(max(int(np.searchsorted(lngs, lng)), 0), nx - 1)
            r0, r1 = max(0, br - ry), min(ny, br + ry + 1)
            c0, c1 = max(0, bc - rx), min(nx, bc + rx + 1)
            if r1 <= r0 or c1 <= c0:
                return None
            dy = (lats[r0:r1, None] - lat) * m_per_deg_lat   # +nord (m)
            dx = (lngs[None, c0:c1] - lng) * m_per_deg_lng   # +est (m)
            inside = dx * dx + dy * dy <= radius * radius
            return r0, r1, c0, c1, dy, dx, inside

        # 22/07/2026 — DANGERS d'abord (disques pleins).
        for h in self.hazards:
            if not (lat_s - pad <= h["lat"] <= lat_n + pad and lng_w - pad <= h["lng"] <= lng_e + pad):
                continue
            if not self.hazard_blocks(h, min_depth):
                continue
            d = _disc(h["lat"], h["lng"], R_HAZARD_M)
            if d is None:
                continue
            r0, r1, c0, c1, _dy, _dx, inside = d
            blocked[r0:r1, c0:c1] |= inside

        # ── 27/07/2026 (consigne armateur, vidéo Drenec) — ZONES DE CULTURE
        # MARINE : interdites SANS AUCUNE exemption (ni marée, ni dernier
        # recours, ni proximité départ/arrivée). « Même s'il y a de l'eau
        # c'est trop dangereux. » En maille très grossière (> 60 m) les
        # disques scellaient les chenaux bordés de parcs (embouchure de la
        # Vilaine) : les passes fines/réparations les font respecter, et le
        # tracé final est audité (avertissement nominatif si traversée).
        if len(self.farm_circles) and max(cy, cx) <= 60.0:
            fc = self.farm_circles
            sel = ((fc[:, 0] >= lat_s - pad) & (fc[:, 0] <= lat_n + pad)
                   & (fc[:, 1] >= lng_w - pad) & (fc[:, 1] <= lng_e + pad))
            for fla, flo, fr in fc[sel]:
                d = _disc(float(fla), float(flo), float(fr))
                if d is None:
                    continue
                r0, r1, c0, c1, _dy, _dx, inside = d
                blocked[r0:r1, c0:c1] |= inside

        # ── 26/07/2026 (demande armateur, capture Larmor-Baden) — ZONES DE
        # MOUILLAGE : interdit de router À TRAVERS un champ de bouées.
        # Exemptions : bouées < 400 m du départ/arrivée (strict_exempt), et
        # mode « mouillages ouverts » (MOORINGS_OPEN, retry aucune-autre-
        # route — le routeur ajoute alors un avertissement). Le tirant d'eau
        # reste contrôlé partout par le masque profondeur.
        if self.moorings and not MOORINGS_OPEN.get():
            for mo in self.moorings:
                if not (lat_s - pad <= mo["lat"] <= lat_n + pad and lng_w - pad <= mo["lng"] <= lng_e + pad):
                    continue
                if strict_exempt:
                    exempt = False
                    for pt in strict_exempt:
                        dd = math.hypot((mo["lat"] - pt[0]) * m_per_deg_lat,
                                        (mo["lng"] - pt[1]) * m_per_deg_lng)
                        if dd < MOORING_EXEMPT_M:
                            exempt = True
                            break
                    if exempt:
                        continue
                d = _disc(mo["lat"], mo["lng"], R_MOORING_M)
                if d is None:
                    continue
                r0, r1, c0, c1, _dy, _dx, inside = d
                blocked[r0:r1, c0:c1] |= inside

        # ── 27/07/2026 (vidéo 15h45, mouillages de Barrarach/Île d'Arz) —
        # ZONES DE MOUILLAGE SURFACIQUES : mêmes règles que les bouées
        # (exemption < 400 m du départ/arrivée, ouvertes en dernier recours).
        # Appliquées en maille FINE seulement (≤ 35 m) : en maille grossière
        # les champs qui bordent un chenal étroit le scellaient (rivière
        # d'Auray) — le raffinement fin fait respecter les zones.
        if len(self.anchorage_circles) and not MOORINGS_OPEN.get() \
                and max(cy, cx) <= 35.0:
            ac = self.anchorage_circles
            sel = ((ac[:, 0] >= lat_s - pad) & (ac[:, 0] <= lat_n + pad)
                   & (ac[:, 1] >= lng_w - pad) & (ac[:, 1] <= lng_e + pad))
            for ala, alo, ar in ac[sel]:
                if strict_exempt:
                    exempt = False
                    for pt in strict_exempt:
                        dd = math.hypot((float(ala) - pt[0]) * m_per_deg_lat,
                                        (float(alo) - pt[1]) * m_per_deg_lng)
                        if dd < MOORING_EXEMPT_M:
                            exempt = True
                            break
                    if exempt:
                        continue
                d = _disc(float(ala), float(alo), float(ar))
                if d is None:
                    continue
                r0, r1, c0, c1, _dy, _dx, inside = d
                blocked[r0:r1, c0:c1] |= inside

        for m in self.marks:
            if not (lat_s - pad <= m["lat"] <= lat_n + pad and lng_w - pad <= m["lng"] <= lng_e + pad):
                continue
            kind = m["kind"]
            if kind == "safe_water":
                continue
            radius = {"lateral": R_LATERAL_M, "cardinal": R_CARDINAL_M,
                      "isolated_danger": R_ISOLATED_M, "special": R_SPECIAL_M}[kind]
            # 11/08 (Moteur E) — ÉCART ADAPTATIF à la densité : dans un
            # chenal étroit balisé tous les 50-100 m (Crouesty), des disques
            # fixes de 60 m se recouvrent d'un bord à l'autre et SCELLENT le
            # chenal. L'écart passe à 0,35 × la latérale voisine la plus
            # proche (plancher 25 m — on longe une bouée à 25 m dans un
            # chenal de port). Balisage isolé / eaux ouvertes : 60 m inchangé.
            if kind == "lateral" and SIDE_ABSOLUTE.get():
                radius = min(radius,
                             max(0.35 * self._nearest_lateral_m(m), 25.0))
            # 29/07 (IALA, retour mer) — cardinale de direction CONNUE : le
            # demi-disque côté danger est élargi à 300 m (voir constante).
            # Exemption < 500 m du départ/de l'arrivée (même règle que le
            # balisage latéral strict : on quitte/rejoint son mouillage même
            # s'il se trouve du « mauvais » côté proche d'une cardinale) —
            # l'écart historique de 120 m reste appliqué.
            if kind == "cardinal" and m.get("category") in (
                    "north", "n", "south", "s", "east", "e", "west", "w"):
                radius = R_CARDINAL_WRONG_SIDE_M
                # 14/08/2026 (Moteur F UNIQUEMENT — bug armateur : cardinale
                # « privilégiée » N de la Truie d'Arradon) — le demi-disque
                # danger (300 m) d'une cardinale ne doit JAMAIS sceller un
                # chenal balisé : quand une LATÉRALE est proche, c'est ELLE
                # qui fait autorité sur la limite du chenal (la cardinale et
                # la latérale marquent le même danger, le chenal est au-delà
                # de la latérale). Rayon plafonné à 0,9 × la latérale la plus
                # proche (plancher 120 m historique). Mesuré : la cardinale N
                # (114 m de la Truie) fermait l'entrée du chenal Truie ↔
                # Le Druic en maille grossière → détour de 1 km par le nord.
                if SIDE_ABSOLUTE_V6.get():
                    radius = min(radius,
                                 max(0.9 * self._nearest_lateral_m(m),
                                     float(R_CARDINAL_M)))
                if strict_exempt:
                    for pt in strict_exempt:
                        dd = math.hypot((m["lat"] - pt[0]) * m_per_deg_lat,
                                        (m["lng"] - pt[1]) * m_per_deg_lng)
                        if dd < 500.0:
                            radius = R_CARDINAL_M
                            break
            # 23/07 (règle armateur) — latérale dont le MAUVAIS CÔTÉ est peu
            # profond (fond < tirant + marge + 2 m) : le mauvais côté est
            # interdit jusqu'à 200 m LÀ OÙ C'EST PEU PROFOND (les veines d'eau
            # profondes restent passables — tolérance validée Teignouse).
            # Exemption < 500 m du départ/de l'arrivée (manœuvres portuaires).
            # 22/07/2026 (bug armateur « je ne peux faire aucune route ») —
            # le STRICT exige une direction FIABLE (couple rouge/verte) : sur
            # une latérale isolée, le gradient « distance au large » peut être
            # faux de 90° (chenal de Vannes) et le demi-disque de 200 m FERME
            # le chenal. Isolée → écart standard 60 m seulement.
            # 10/08 (Moteur D uniquement) — une isolée dont l'asymétrie
            # bathymétrique est NETTE (navigable_side) a une direction fiable :
            # le strict s'applique aussi à elle sous ISOLATED_SIDE_BATHY.
            # Et JAMAIS de strict en maille grossière (> 35 m) : la passe
            # grossière ne sert qu'à la connectivité, les passes fines et le
            # contrôle plein-résolution ré-appliquent la sécurité.
            strict_here = False
            strict_full = False
            side_abs_r = 0.0
            if kind == "lateral" and max(cy, cx) <= 35.0:
                pair_m = self._pair_of(m)
                conf_iso = (pair_m is None and ISOLATED_SIDE_BATHY.get()
                            and self.navigable_side(m) is not None)
                exempt500 = False
                if strict_exempt and (pair_m is not None or conf_iso):
                    # 11/08 soir (Moteur E) — exemption réduite à 200 m (au
                    # lieu de 500 m), ALIGNÉE sur l'audit (_EXEMPT_M) : la
                    # zone 200-500 m autour du départ/de l'arrivée laissait
                    # passer du mauvais côté de « 8 » (432 m de l'arrivée
                    # Crouesty, à marée haute) tout en étant flaguée par
                    # l'audit. On rejoint toujours son mouillage (< 200 m).
                    ex_r = 200.0 if SIDE_ABSOLUTE.get() else 500.0
                    for pt in strict_exempt:
                        dd = math.hypot((m["lat"] - pt[0]) * m_per_deg_lat,
                                        (m["lng"] - pt[1]) * m_per_deg_lng)
                        if dd < ex_r:
                            exempt500 = True
                            break
                # 11/08 (Moteur E — CÔTÉ ABSOLU) : demi-disque PLEIN (sans
                # condition de fond). Isolée confiante : 200 m. COUPLE :
                # plafonné à 0,8 × l'écartement (rouge du chenal de Vannes
                # recoupée à 139 m dans 4 m d'eau). Le tout PLAFONNÉ PAR LA
                # DENSITÉ du balisage (0,6 × la latérale voisine la plus
                # proche) : dans un chenal dense en COUDE (Crouesty), des
                # zones à l'échelle 200 m se recouvrent mutuellement et
                # SCELLERAIENT l'entrée du port.
                dens_cap = 0.0
                if SIDE_ABSOLUTE.get() and not exempt500:
                    if conf_iso:
                        dens_cap = max(0.6 * self._nearest_lateral_m(m),
                                       float(R_LATERAL_M))
                        side_abs_r = min(R_LATERAL_STRICT_M, dens_cap)
                    elif pair_m is not None:
                        # 11/08 soir (bug armateur « No2 pas respectée »,
                        # puis « 8 » recoupée à 61 m à marée haute) — le
                        # plafond de densité écrasait le rayon 0,8 ×
                        # écartement du couple (No1 à 199 m → 119 m ; la
                        # perche voisine de « 8 » → 60 m) alors que le
                        # demi-disque d'un VRAI couple (réciproque) pointe
                        # toujours vers l'EXTÉRIEUR du chenal et que le
                        # couloir libre re-creuse la porte : il ne peut pas
                        # sceller le chenal. La densité (mesurée HORS
                        # partenaire) ne plafonne plus que l'extension
                        # peu-profonde ci-dessous.
                        dens_cap = max(
                            0.6 * self._nearest_other_lateral_m(m),
                            float(R_LATERAL_M))
                        gap_p = math.hypot(
                            (pair_m["lat"] - m["lat"]) * m_per_deg_lat,
                            (pair_m["lng"] - m["lng"]) * m_per_deg_lng)
                        side_abs_r = min(R_LATERAL_STRICT_M,
                                         max(0.8 * gap_p, R_LATERAL_M))
                if ((pair_m is not None or conf_iso)
                        and self._lateral_strict(m, strict_depth)):
                    strict_here = depth is not None and not exempt500
                if strict_here or side_abs_r > 0.0:
                    strict_r = R_LATERAL_STRICT_M
                    if dens_cap > 0.0:
                        # mode E : l'extension peu-profonde est plafonnée par
                        # la densité elle aussi (même géométrie, même risque).
                        strict_r = min(strict_r, dens_cap)
                    radius = max(radius,
                                 strict_r if strict_here else side_abs_r)
                    # 10/08 (Moteur D) — isolée confiante : plein sur 200 m
                    # (une « langue » d'eau profonde entre la bouée et le
                    # danger qu'elle signale n'est PAS un passage — Illur).
                    strict_full = conf_iso and not SIDE_ABSOLUTE.get()
            d = _disc(m["lat"], m["lng"], radius)
            if d is None:
                continue
            r0, r1, c0, c1, dy, dx, inside = d

            if kind in ("isolated_danger", "special"):
                zone = inside
            elif kind == "cardinal":
                cat = m["category"]
                if cat in ("north", "n"):
                    zone = inside & (dy < 0)      # danger au SUD de la balise
                elif cat in ("south", "s"):
                    zone = inside & (dy > 0)
                elif cat in ("east", "e"):
                    zone = inside & (dx < 0)      # danger à l'OUEST
                elif cat in ("west", "w"):
                    zone = inside & (dx > 0)
                else:
                    zone = inside                  # cardinale inconnue : prudence
            else:  # lateral
                # 26/07 (bug armateur, chenal de La Vilaine) — DERNIER
                # RECOURS : le sens conventionnel peut être FAUX hors des
                # chenaux calibrés (champ orienté N dans la Vilaine → demi-
                # disques EN TRAVERS du chenal = no_route à chaque bouée).
                # Quand aucune autre route n'existe (MOORINGS_OPEN), on lève
                # l'interdit de CÔTÉ latéral — profondeur, dangers et
                # cardinales restent appliqués, et le routeur avertit
                # explicitement l'utilisateur de vérifier le balisage à vue.
                # 27/07 (vidéo 15h45 : Holavre à 11 m, bouée n°6 SOUS la
                # route) — la levée du sens conventionnel n'est plus couplée
                # aux mouillages : elle a son propre étage de dernier recours
                # (SIDE_RULES_OPEN), tenté seulement si « mouillages ouverts »
                # ne suffit pas.
                if SIDE_RULES_OPEN.get():
                    # 10/08 (Moteur D, consigne armateur « respect ABSOLU du
                    # balisage ») — le dernier recours / mode eau peu profonde
                    # levait TOUS les côtés latéraux (SIDE_RULES_OPEN) parce
                    # que le sens conventionnel estimé par gradient était
                    # parfois FAUX (Vilaine) et fermait des chenaux. Sous le
                    # mode D, les latérales à direction FIABLE (couple,
                    # override terrain, asymétrie bathymétrique) ne sont
                    # JAMAIS levées : c'est précisément dans les estuaires
                    # découvrants que le balisage compte le plus (mesuré le
                    # 10/08 : No1 laissée du mauvais côté à 9,8 m en Vilaine).
                    # Les latérales AMBIGUËS (gradient) restent levées.
                    if not (ISOLATED_SIDE_BATHY.get()
                            and self.mark_dir_confident(m) is not None):
                        continue
                cat = m["category"]
                if cat not in ("port", "starboard"):
                    continue  # ni côté ni couleur : ignorée (règle armateur)
                d2 = self._mark_dir(m)
                if d2 is None:
                    continue
                de, dn = d2  # direction conventionnelle (vers l'abri)
                # cross > 0 ⇔ point à GAUCHE de D (vu en entrant).
                cross = de * dy - dn * dx
                if cat == "starboard":
                    # verte : bateau à gauche → interdit la DROITE de D.
                    zone = inside & (cross < 0)
                else:
                    # rouge : bateau à droite → interdit la GAUCHE de D.
                    zone = inside & (cross > 0)
                if strict_here or side_abs_r > 0.0:
                    # Écart standard (60 m) inconditionnel + extension stricte
                    # (jusqu'à 200 m) UNIQUEMENT sur les cellules peu profondes
                    # du mauvais côté (l'eau profonde reste passable).
                    # 10/08 (Moteur D) — isolée confiante : demi-disque PLEIN.
                    # 11/08 (Moteur E) — couple : PLEIN jusqu'à 0,8 × gap en
                    # plus de l'extension peu-profonde historique.
                    if not strict_full:
                        inside_std = dx * dx + dy * dy <= R_LATERAL_M * R_LATERAL_M
                        keep = zone & inside_std
                        if strict_here:
                            shallow = depth[r0:r1, c0:c1] < strict_depth
                            keep |= zone & shallow
                        if side_abs_r > 0.0:
                            keep |= zone & (dx * dx + dy * dy
                                            <= side_abs_r * side_abs_r)
                        zone = keep
            marks_blocked[r0:r1, c0:c1] |= zone

        # ── 22/07/2026 — COULOIR LIBRE entre chaque couple rouge/verte ────
        # L'eau entre une latérale bâbord et sa tribord appariée EST le
        # chenal : quelles que soient les erreurs de direction convention-
        # nelle, ce couloir ne doit JAMAIS être fermé par le balisage
        # (chenal de Vannes fermé → « Passage impossible » armateur).
        # Disque au MILIEU du couple, rayon 45 % de l'écartement : couvre le
        # cœur du chenal sans rouvrir l'écart minimal autour des balises.
        seen_pairs: set[tuple[int, int]] = set()
        for m in self.marks:
            if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
                continue
            if not (lat_s - pad <= m["lat"] <= lat_n + pad and lng_w - pad <= m["lng"] <= lng_e + pad):
                continue
            o = self._pair_of(m)
            if o is None:
                continue
            key = (min(id(m), id(o)), max(id(m), id(o)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            mid_lat = (m["lat"] + o["lat"]) / 2
            mid_lng = (m["lng"] + o["lng"]) / 2
            gap = math.hypot((m["lat"] - o["lat"]) * m_per_deg_lat,
                             (m["lng"] - o["lng"]) * m_per_deg_lng)
            d = _disc(mid_lat, mid_lng, max(0.45 * gap, cy, cx))
            if d is None:
                continue
            r0, r1, c0, c1, _dy, _dx, inside = d
            marks_blocked[r0:r1, c0:c1] &= ~inside

        # ── 26/07/2026 (retour armateur, chenal de La Vilaine) — ÉCART
        # MINIMAL TOUTES DIRECTIONS autour de chaque balise latérale/
        # cardinale, appliqué APRÈS le couloir libre : le cœur du chenal
        # reste ouvert mais la route ne se colle plus aux bouées (7 m !).
        # Garde-fous : rayon ≤ 25 % de l'écartement du couple (chenaux
        # étroits passables), sauté en maille grossière (sub-cellule) et
        # < 200 m du départ/arrivée DEMANDÉS.
        # 27/07 (vidéo 15h45 : Holavre à 11 m) — appliqué AUSSI en dernier
        # recours : on ne frôle JAMAIS une balise, quel que soit le mode.
        # (le garde-fou « rayon ≥ maille » ci-dessous suffit : en maille
        # grossière le disque est sauté, les passes fines l'appliquent).
        for m in self.marks:
            if m.get("kind") not in ("lateral", "cardinal"):
                continue
            if not (lat_s - pad <= m["lat"] <= lat_n + pad and lng_w - pad <= m["lng"] <= lng_e + pad):
                continue
            r_std = R_MARK_STANDOFF_M
            o = self._pair_of(m) if m["kind"] == "lateral" else None
            if o is not None:
                gap = math.hypot((m["lat"] - o["lat"]) * m_per_deg_lat,
                                 (m["lng"] - o["lng"]) * m_per_deg_lng)
                # 28/07 (consigne support) — CONTRAINTE DURE : plancher
                # R_MARK_STANDOFF_MIN_M, le rayon ne se réduit plus à ≤ 25 %
                # de l'écartement (passage « sur la n°6 » / « à 11 m »).
                r_std = min(r_std, max(0.25 * gap, R_MARK_STANDOFF_MIN_M))
            # 28/07 — plus JAMAIS sauté en maille fine parce que le rayon est
            # sous la maille (le disque bloque au moins la cellule de la
            # balise). Maille grossière (> 45 m) : passes fines + réparation.
            if max(cy, cx) > 45.0:
                continue
            if strict_exempt:
                skip = False
                for pt in strict_exempt:
                    dd = math.hypot((m["lat"] - pt[0]) * m_per_deg_lat,
                                    (m["lng"] - pt[1]) * m_per_deg_lng)
                    if dd < 200.0:
                        skip = True
                        break
                if skip:
                    continue
            d = _disc(m["lat"], m["lng"], r_std)
            if d is None:
                continue
            r0, r1, c0, c1, _dy, _dx, inside = d
            marks_blocked[r0:r1, c0:c1] |= inside

        out = blocked | marks_blocked
        if cache_key is not None and cache is not None:
            cache[cache_key] = out
        return out

    # ── 27/07/2026 (consigne armateur : « obligatoire de suivre les
    # chenaux ») — PORTES DE CHENAL pour l'attraction A* : chaque couple de
    # latérales rouge/verte est une porte ; l'eau autour d'une porte mais
    # HORS du couloir coûte plus cher → la route passe PAR les portes.
    def gates(
        self, lat_s: float, lat_n: float, lng_w: float, lng_e: float,
    ) -> list[tuple[float, float, float, float, float]]:
        """[(mid_lat, mid_lng, écartement_m, u_est, u_nord)] des couples dans
        la bbox — u = vecteur unitaire TRANSVERSE au chenal, écartement = la
        LARGEUR PERPENDICULAIRE du chenal.

        28/07/2026 (bug vidéo 15h45, chenal de Vannes) — couples EN QUINCONCE
        (No7/No8 décalés le long du chenal) : le vecteur brut du couple
        pointe surtout LE LONG du chenal → l'« attraction de porte » 27/07
        pénalisait le chenal LUI-MÊME et laissait la vasière voisine
        gratuite (route à 280 m à l'est des bouées). Comme _mark_dir, on ne
        garde du vecteur du couple que sa composante PERPENDICULAIRE à
        l'axe du chenal (alignement des latérales du même côté)."""
        out: list[tuple[float, float, float, float, float]] = []
        seen: set[tuple[int, int]] = set()
        for m in self.marks:
            if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
                continue
            if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
                continue
            o = self._pair_of(m)
            if o is None:
                continue
            key = (min(id(m), id(o)), max(id(m), id(o)))
            if key in seen:
                continue
            seen.add(key)
            mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
            ux = (o["lng"] - m["lng"]) * mlng
            uy = (o["lat"] - m["lat"]) * 110_574.0
            axis = self._same_side_axis(m) or self._same_side_axis(o)
            raw = math.hypot(ux, uy)
            if axis is not None:
                ae, an = axis
                dot = ux * ae + uy * an
                pe, pn = ux - dot * ae, uy - dot * an
                perp = math.hypot(pe, pn)
                # Couple en QUINCONCE PUR (décalé surtout le long du chenal,
                # composante transverse < 60 %) : le milieu du couple n'est
                # PAS le milieu du chenal → pas une porte fiable, ignoré
                # (les règles de côté + l'écart minimal restent appliqués).
                if perp < 0.6 * raw:
                    continue
                if perp >= 20.0:
                    ux, uy = pe, pn
            gap = math.hypot(ux, uy)
            if gap <= 20.0:
                continue  # couple dégénéré (doublon OSM / quinconce pur)
            out.append(((m["lat"] + o["lat"]) / 2, (m["lng"] + o["lng"]) / 2,
                        gap, ux / gap, uy / gap))
        return out

    # ── 27/07/2026 — AUDIT DE PASSAGE : écart minimal attendu par balise
    # (même logique que le rasterize) pour vérifier le tracé FINAL et
    # avertir nominativement si la route frôle une balise malgré tout.
    def standoff_circles(
        self, lat_s: float, lat_n: float, lng_w: float, lng_e: float,
    ) -> list[tuple[float, float, float, str]]:
        out: list[tuple[float, float, float, str]] = []
        for m in self.marks:
            if m.get("kind") not in ("lateral", "cardinal"):
                continue
            if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
                continue
            r_std = R_MARK_STANDOFF_M
            # 11/08 soir (Moteur E) — même écart ADAPTATIF à la densité que
            # le masque : dans un chenal de port balisé tous les 50-100 m,
            # passer à 40-50 m d'une perche est NORMAL — l'audit n'avertit
            # plus « écart recommandé 60 m » quand le moteur a précisément
            # visé l'écart adapté (0,35 × la latérale voisine, plancher 25 m).
            if m["kind"] == "lateral" and SIDE_ABSOLUTE.get():
                r_std = min(r_std,
                            max(0.35 * self._nearest_lateral_m(m), 25.0))
            o = self._pair_of(m) if m["kind"] == "lateral" else None
            if o is not None:
                gap = math.hypot((m["lat"] - o["lat"]) * 110_574.0,
                                 (m["lng"] - o["lng"]) * 111_320.0 * math.cos(math.radians(m["lat"])))
                # 28/07 — même plancher que le masque (contrainte dure).
                r_std = min(r_std, max(0.25 * gap, R_MARK_STANDOFF_MIN_M))
            out.append((m["lat"], m["lng"], r_std,
                        m.get("name") or f"balise {m.get('category', '')}".strip()))
        return out

    # ── 22/07/2026 — Points à ÉCART MINIMAL pour le redressement global ──
    def clearance_points(
        self, lat_s: float, lat_n: float, lng_w: float, lng_e: float, min_depth: float,
    ) -> list[tuple[float, float, float]]:
        """(lat, lng, rayon_m) de TOUT ce que le tracé redressé doit éviter :
        balises (rayon plein, conservateur — le redressement ne coupe jamais
        près d'une balise, quel que soit le côté) + dangers bloquants."""
        pts: list[tuple[float, float, float]] = []
        radius_by_kind = {"lateral": R_LATERAL_M, "cardinal": R_CARDINAL_M,
                          "isolated_danger": R_ISOLATED_M, "special": R_SPECIAL_M}
        for m in self.marks:
            if m["kind"] == "safe_water":
                continue
            if lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e:
                r_std = radius_by_kind[m["kind"]]
                # 11/08 (Moteur E) — écart adaptatif à la densité (cf.
                # rasterize) : mêmes rayons pour les contrôles de la passe 3.
                if m["kind"] == "lateral" and SIDE_ABSOLUTE.get():
                    r_std = min(r_std,
                                max(0.35 * self._nearest_lateral_m(m), 25.0))
                pts.append((m["lat"], m["lng"], r_std))
                # 10/08 (Moteur D UNIQUEMENT) — CONTRAINTE DE CÔTÉ pour les
                # contrôles pleine résolution : le redressement/la réparation
                # (_corridor_safe) ne connaissent que des cercles d'écart, si
                # bien que la passe 3 RETENDAIT le tracé du MAUVAIS côté dès
                # 60 m d'écart et de l'eau (mesuré 10/08 : Illur recoupée à
                # 91 m au sud en marge AUTO 10 m). Le demi-disque danger
                # (200 m) de chaque latérale ISOLÉE à côté FIABLE est couvert
                # par un semis de disques d'écart (rayon 45 m, 3 anneaux ×
                # 5 azimuts autour de la direction du danger) — même
                # mécanisme que les parcs marins. Moteurs gelés : inchangés.
                if (ISOLATED_SIDE_BATHY.get() and m["kind"] == "lateral"
                        and self._pair_of(m) is None):
                    w = self.navigable_side(m)
                    if w is not None:
                        # 11/08 (mode E) : anneaux plafonnés par la densité.
                        r_lim = float("inf")
                        if SIDE_ABSOLUTE.get():
                            r_lim = max(0.6 * self._nearest_lateral_m(m), 60.0)
                        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
                        dde, ddn = -w[0], -w[1]     # direction du DANGER
                        for dist in (60.0, 120.0, 180.0):
                            if dist > r_lim - 20.0:
                                break
                            for ang in (0.0, 35.0, -35.0, 70.0, -70.0):
                                ca = math.cos(math.radians(ang))
                                sa = math.sin(math.radians(ang))
                                ue = dde * ca - ddn * sa
                                un = dde * sa + ddn * ca
                                pts.append((m["lat"] + un * dist / 110_574.0,
                                            m["lng"] + ue * dist / mlng, 45.0))
                # 11/08 (Moteur E — CÔTÉ ABSOLU) : même semis pour les
                # COUPLES (le redressement recoupait la rouge du chenal de
                # Vannes à 139 m hors de la porte). Direction du danger =
                # l'OPPOSÉ du couple ; anneaux plafonnés à 0,8 × écartement.
                elif SIDE_ABSOLUTE.get() and m["kind"] == "lateral":
                    pair = self._pair_of(m)
                    d_dir = self._pair_dir(m)
                    if pair is not None and d_dir is not None:
                        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
                        gap = math.hypot(
                            (m["lng"] - pair["lng"]) * mlng,
                            (m["lat"] - pair["lat"]) * 110_574.0)
                        de_, dn_ = d_dir
                        # côté passage : tribord(D) rouge / bâbord(D) verte ;
                        # danger = l'opposé (projection quinconce incluse).
                        ue_p, un_p = ((dn_, -de_) if m["category"] == "port"
                                      else (-dn_, de_))
                        dde, ddn = -ue_p, -un_p
                        # 11/08 soir — aligné sur le masque : 0,8 × écartement
                        # du couple, sans plafond de densité (cf. rasterize).
                        r_abs = min(200.0, max(0.8 * gap, 60.0))
                        for dist in (60.0, 120.0, 180.0):
                            if dist > r_abs - 20.0:
                                break
                            for ang in (0.0, 35.0, -35.0, 70.0, -70.0):
                                ca = math.cos(math.radians(ang))
                                sa = math.sin(math.radians(ang))
                                ue = dde * ca - ddn * sa
                                un = dde * sa + ddn * ca
                                pts.append(
                                    (m["lat"] + un * dist / 110_574.0,
                                     m["lng"] + ue * dist / mlng, 45.0))
        for h in self.hazards:
            if lat_s <= h["lat"] <= lat_n and lng_w <= h["lng"] <= lng_e:
                if self.hazard_blocks(h, min_depth):
                    pts.append((h["lat"], h["lng"], R_HAZARD_M))
        # 27/07 — zones de culture marine : le redressement/arrondi ne doit
        # jamais couper un parc (mêmes disques que le masque navigable).
        if len(self.farm_circles):
            fc = self.farm_circles
            sel = ((fc[:, 0] >= lat_s) & (fc[:, 0] <= lat_n)
                   & (fc[:, 1] >= lng_w) & (fc[:, 1] <= lng_e))
            pts.extend((float(a), float(b), float(r)) for a, b, r in fc[sel])
        return pts


_index: Optional[SeamarkIndex] = None


def get_seamarks() -> Optional[SeamarkIndex]:
    global _index
    if _index is None and SEAMARKS_PATH.exists():
        # 23/07/2026 (généralisation Atlantique) — le champ « distance au
        # large » est calé sur la grille de ZONE la plus ÉTENDUE (atl100,
        # graines = bordures en eau franche). Repli zone pilote puis mosaïque.
        grid = get_zone_grid("atl100") or get_zone_grid("morbihan") or get_grid()
        if grid is not None:
            _index = SeamarkIndex(grid)
    return _index
