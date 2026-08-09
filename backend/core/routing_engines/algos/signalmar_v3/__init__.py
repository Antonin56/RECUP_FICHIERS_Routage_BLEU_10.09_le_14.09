"""SignalMar — Algo « signalmar.v3 » (Moteur C, 03/08/2026).

Moteur bâti sur les CONSIGNES EXPLICITES de l'armateur du 03/08/2026,
codifiées dans ``config/navigation_rules.yaml`` (servi par
``GET /api/routing/rules``) :

1. **BALISAGE — priorité absolue.** Le calcul se fait TOUJOURS dans le sens
   conventionnel (mer → terre) : la géométrie d'une route est donc identique
   dans les deux sens de parcours. Rouges à bâbord, vertes à tribord, le sens
   conventionnel étant celui du calcul (plus aucune estimation par gradient —
   cause racine du passage du mauvais côté d'« Illur » par le Moteur B).
2. **PROFONDEUR.** Chemin le plus court DANS LA ZONE LA PLUS PROFONDE : un
   surcoût « manque de fond » est injecté dans l'A* (contextvar
   ``core.nav_rules.DEPTH_PRIORITY``, neutre pour les Moteurs A et B).
3. **MARGE LATÉRALE.** 50 m par défaut, réduite à 20 m si nécessaire pour
   respecter le balisage puis la profondeur. Sous 20 m inévitables, le tronçon
   est rendu ROUGE avec avertissement (marge MESURÉE en pleine résolution,
   cf. ``margins.py``).
4. **JAMAIS D'ÉCHEC.** Aucune route ne renvoie « Passage impossible » : à
   défaut de passage sain, le tracé est rendu avec ses tronçons rouges.

Les Moteurs A (``signalmar.v1``) et B (``signalmar.v2``) sont GELÉS : aucune
de ces règles ne les affecte.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np

from core.bathy import M_PER_DEG_LAT, get_grid, m_per_deg_lng
from core.nav_rules import DEPTH_PRIORITY, merge_params
from core.routing_engines.base import BaseAlgo
from core.routing_engines.algos.signalmar_v1 import core as v1
from core.routing_engines.algos.signalmar_v2.standoff import _Ctx, rebuild_result
from core.seamarks import MOORING_EXEMPT_M, MOORINGS_OPEN, SIDE_RULES_OPEN, get_seamarks

from .direction import canonical_order, grid_for, mid_mlng
from .margins import leg_clearances
from .side import audit_sides, enforce_sides

logger = logging.getLogger("signalmar.routing.v3")

Pt = tuple[float, float]

MSG_SHALLOW = (
    "⚠ EAU PEU PROFONDE : aucun passage n'offre la hauteur d'eau requise à "
    "marée basse (ZH). Les tronçons en ROUGE traversent une zone peu profonde "
    "ou découverte — ne les franchissez qu'avec une hauteur de marée "
    "suffisante, à vitesse réduite."
)
MSG_LOW_MARGIN = (
    "⚠ MARGE LATÉRALE < 20 m sur les tronçons en ROUGE : impossible de garder "
    "20 m de part et d'autre du tracé (chenal étroit / hauts-fonds) — passage "
    "à vue, à vitesse réduite."
)


class SignalmarV3(BaseAlgo):
    id = "signalmar.v3"
    version = "3.0.0"
    description = (
        "Moteur C : règles armateur du 03/08 appliquées strictement — sens "
        "conventionnel FORCÉ (mer → terre, géométrie identique dans les deux "
        "sens), rouges à bâbord / vertes à tribord, profondeur prioritaire sur "
        "la distance, marge latérale 50 m réductible à 20 m, et JAMAIS de "
        "« Passage impossible » (tronçons rouges à la place)."
    )

    # ── Interface BaseAlgo ────────────────────────────────────────────────
    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        p = merge_params(params)
        req_start: Pt = (start_lat, start_lng)
        req_end: Pt = (end_lat, end_lng)
        a, b, reversed_ = (
            canonical_order(req_start, req_end)
            if p.get("force_conventional_direction", True)
            else (req_start, req_end, False)
        )
        res = self._compute_conventional(a, b, draft_m, depth_margin_m, tide_m, p)
        res["engine_rules"] = {
            "conventional_direction": "mer_vers_terre",
            "computed_reversed": bool(reversed_),
            "sea_end": {"lat": round(a[0], 6), "lng": round(a[1], 6)},
            "land_end": {"lat": round(b[0], 6), "lng": round(b[1], 6)},
        }
        if reversed_:
            res = _reverse_result(res, draft_m, depth_margin_m, tide_m, p)
        return res

    def compute_manual(
        self,
        waypoints: list[tuple[float, float]],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        # Route MANUELLE : tracée par l'utilisateur → JAMAIS déplacée (les
        # règles de côté ne s'appliquent pas à une intention explicite). On
        # ajoute seulement l'audit de côté en avertissement.
        res = v1.manual_route(waypoints, draft_m, depth_margin_m, tide_m=tide_m)
        p = merge_params(params)
        pts = [(float(w["lat"]), float(w["lng"])) for w in (res.get("waypoints") or [])]
        if len(pts) >= 2:
            _annotate_sides(res, pts, mid_mlng(pts), p, fixed=[],
                            dir_grid=grid_for(pts[0], pts[-1]),
                            depth_gate=(get_grid(), draft_m + depth_margin_m + 2.0))
        return res

    def capabilities(self) -> dict[str, Any]:
        caps = super().capabilities()
        caps["params"] = merge_params(None)
        return caps

    # ── Cœur ──────────────────────────────────────────────────────────────
    def _compute_conventional(
        self, a: Pt, b: Pt, draft_m: float, depth_margin_m: float,
        tide_m: float, p: dict[str, Any],
    ) -> dict:
        """Calcul dans le sens conventionnel a→b (mer → terre)."""
        margins = [float(p["margin_default_m"]), float(p["margin_reduced_m"])]
        red_m = float(p["margin_red_m"])
        tok = DEPTH_PRIORITY.set(
            (float(p["depth_priority_weight"]), float(p["depth_reference_m"])),
        )
        try:
            best: Optional[tuple[dict, float, list[dict]]] = None
            for m in margins:
                try:
                    res = v1.compute_route(
                        a[0], a[1], b[0], b[1],
                        draft_m, depth_margin_m, m, tide_m=tide_m,
                    )
                except v1.RouteError as err:
                    if err.code == "out_of_coverage":
                        raise
                    continue
                res, remaining = self._apply_side_rules(
                    res, a, b, draft_m, depth_margin_m, tide_m, m, p)
                res["lateral_margin_used_m"] = round(m, 1)
                if best is None or not remaining:
                    best = (res, m, remaining)
                if not remaining:
                    break
            if best is None:
                res = self._shallow_fallback(a, b, draft_m, depth_margin_m, p)
            else:
                res = best[0]
        finally:
            DEPTH_PRIORITY.reset(tok)

        _annotate_margins(res, draft_m + depth_margin_m - min(0.0, tide_m), red_m)
        _annotate_shallow(res, draft_m + depth_margin_m)
        return res

    def _apply_side_rules(
        self, res: dict, a: Pt, b: Pt, draft_m: float, depth_margin_m: float,
        tide_m: float, lateral_m: float, p: dict[str, Any],
    ) -> tuple[dict, list[dict]]:
        """RÈGLE 1 : fait repasser le tracé du bon côté des latérales."""
        wps = res.get("waypoints") or []
        grid = get_grid()
        if grid is None or len(wps) < 2:
            return res, []
        pts = [(float(w["lat"]), float(w["lng"])) for w in wps]
        mlng = mid_mlng(pts)
        min_depth = max(draft_m + depth_margin_m - float(np.clip(tide_m, -2.0, 6.0)), -2.5)
        strict_depth = draft_m + depth_margin_m + 2.0
        clearance, gates = _control_arrays(pts, min_depth, mlng, (a, b))
        ctx = _Ctx(grid, min_depth, lateral_m, clearance, gates, strict_depth, mlng)
        dir_grid = grid_for(a, b)
        depth_gate = (grid, strict_depth)
        try:
            new_pts, fixed, remaining = enforce_sides(
                pts, mlng=mlng, ctx=ctx, params=p, exempt=(a, b),
                dir_grid=dir_grid, depth_gate=depth_gate)
        except Exception:  # noqa: BLE001 — jamais bloquant
            logger.exception("v3: enforce_sides a échoué, tracé conservé")
            return res, []
        # 03/08 — comparaison sur le CONTENU et non sur la longueur : un
        # pontage peut retirer 2 waypoints et en ajouter 3, donc conserver le
        # même nombre de points. La condition `len(...) != len(...)` sautait
        # alors la reconstruction : le tracé restait INCHANGÉ alors que la
        # balise était annoncée corrigée (cas « Illur » du 03/08).
        if new_pts != pts:
            out = rebuild_result(
                res, grid, new_pts, min_depth=min_depth,
                lateral_margin_m=lateral_m, exempt=(a, b), clearance=clearance,
            )
            # Filet de sécurité : jamais de régression du profil de fond. Si le
            # contournement dégrade le fond, on RESTAURE le tracé d'origine (et
            # ses violations, qui seront remontées en avertissement).
            old_min, new_min = res.get("min_depth_m"), out.get("min_depth_m")
            if new_min is not None and old_min is not None and new_min < old_min - 0.05:
                fixed = []
                remaining = audit_sides(
                    pts, mlng=mlng, params=p, exempt=(a, b), dir_grid=dir_grid,
                    depth_gate=depth_gate,
                )
            else:
                res = out
                pts = new_pts
        _annotate_sides(res, pts, mlng, p, fixed=fixed, remaining=remaining,
                        dir_grid=dir_grid, depth_gate=depth_gate)
        return res, remaining

    def _shallow_fallback(
        self, a: Pt, b: Pt, draft_m: float, depth_margin_m: float,
        p: dict[str, Any],
    ) -> dict:
        """RÈGLE 4 : JAMAIS d'échec. Aucun passage sain → on trace quand même
        (seuil de fond relâché au plancher moteur, mouillages et côtés
        assouplis, marge minimale), les tronçons insuffisants étant rendus en
        ROUGE côté app."""
        tok_m = MOORINGS_OPEN.set(True)
        tok_s = SIDE_RULES_OPEN.set(True)
        try:
            res = v1.compute_route(
                a[0], a[1], b[0], b[1],
                draft_m, depth_margin_m, float(p["margin_reduced_m"]), tide_m=6.0,
            )
        except v1.RouteError:
            res = _straight_line_result(a, b, draft_m + depth_margin_m)
        finally:
            SIDE_RULES_OPEN.reset(tok_s)
            MOORINGS_OPEN.reset(tok_m)
        res["warnings"] = [
            w for w in (res.get("warnings") or []) if "grâce à la marée" not in w
        ]
        res["lateral_margin_used_m"] = round(float(p["margin_reduced_m"]), 1)
        res["tide_m"] = 0.0
        res["risk"] = True
        res["shallow_route"] = True
        return res


# ── Annotations du résultat ───────────────────────────────────────────────
def _control_arrays(pts: list[Pt], min_depth: float, mlng: float,
                    exempt: tuple[Pt, Pt]):
    """Mêmes tableaux de contrôle que la passe 3 du moteur historique."""
    sm = get_seamarks()
    if sm is None:
        return None, None
    la = [q[0] for q in pts]
    lo = [q[1] for q in pts]
    clearance = None
    cl = sm.clearance_points(min(la) - 0.01, max(la) + 0.01,
                            min(lo) - 0.01, max(lo) + 0.01, min_depth)
    if cl:
        clearance = np.asarray(cl, dtype=np.float64)
    gates = None
    ga = [
        g for g in sm.gates(min(la) - 0.01, max(la) + 0.01,
                            min(lo) - 0.01, max(lo) + 0.01)
        if not any(
            math.hypot((g[0] - q[0]) * M_PER_DEG_LAT, (g[1] - q[1]) * mlng)
            < MOORING_EXEMPT_M for q in exempt
        )
    ]
    if ga:
        gates = np.asarray(ga, dtype=np.float64)
    return clearance, gates


def _mark_leg(res: dict, legs: list[int], reason: str) -> None:
    """Ajoute des tronçons au tracé ROUGE + mémorise leur MOTIF (l'app affiche
    le motif au tap sur le tronçon)."""
    if not legs:
        return
    res["compromised_legs"] = sorted(
        set(res.get("compromised_legs") or []) | set(legs))
    reasons = dict(res.get("leg_reasons") or {})
    for i in legs:
        reasons.setdefault(str(i), reason)
    res["leg_reasons"] = reasons
    res["risk"] = True


def _annotate_margins(res: dict, min_depth: float, red_m: float) -> None:
    """RÈGLE 3 : marge latérale MESURÉE par tronçon + tronçons rouges."""
    wps = res.get("waypoints") or []
    if len(wps) < 2:
        return
    try:
        cl = leg_clearances(wps, min_depth)
    except Exception:  # noqa: BLE001
        logger.exception("v3: mesure de marge latérale échouée")
        return
    if not cl:
        return
    res["leg_margin_m"] = [round(c, 1) for c in cl]
    low = [i for i, c in enumerate(cl) if c <= red_m]
    if low:
        _mark_leg(res, low, "low_margin")
        res["low_margin_legs"] = low
        res.setdefault("warnings", []).insert(0, MSG_LOW_MARGIN)


def _annotate_shallow(res: dict, base_need: float) -> None:
    """RÈGLE 4 : tronçons dont le fond est insuffisant → ROUGE (jamais un
    refus). ``base_need`` = tirant d'eau + marge, au ZH."""
    wps = res.get("waypoints") or []
    if len(wps) < 2:
        return
    try:
        legs = v1.shallow_legs(wps, base_need)
    except Exception:  # noqa: BLE001
        logger.exception("v3: détection des tronçons peu profonds échouée")
        return
    if legs:
        _mark_leg(res, legs, "shallow")
        res["shallow_legs_v3"] = legs
        if MSG_SHALLOW not in (res.get("warnings") or []):
            res.setdefault("warnings", []).insert(0, MSG_SHALLOW)
        res["shallow_route"] = True
    res["threshold_m"] = round(base_need, 2)


def _annotate_sides(res: dict, pts: list[Pt], mlng: float, p: dict[str, Any],
                    *, fixed: list[str], remaining: Optional[list[dict]] = None,
                    dir_grid=None, depth_gate=None) -> None:
    """RÈGLE 1 : trace ce qui a été corrigé et ce qui reste non conforme."""
    if remaining is None:
        remaining = audit_sides(
            pts, mlng=mlng, params=p, dir_grid=dir_grid, depth_gate=depth_gate,
        )
    if fixed:
        res["side_fixed"] = fixed
    if remaining:
        res["wrong_side_marks"] = [
            {"name": v["name"], "kind": v.get("kind"),
             "category": v.get("category"), "dist_m": v["dist_m"],
             "side_required": v["side_required"]}
            for v in remaining[:6]
        ]
        for v in remaining[:3]:
            what = ("cardinale" if v.get("kind") == "cardinal"
                    else "rouge" if v.get("category") == "port" else "verte")
            res.setdefault("warnings", []).insert(0, (
                f"⚠ MAUVAIS CÔTÉ DE BALISE : « {v['name']} » ({what}) doit "
                f"être laissée {v['side_required']} — passage à "
                f"~{v['dist_m']:.0f} m, aucun itinéraire conforme trouvé, "
                "franchissez À VUE."
            ))
    # 03/08 (cardinale sud « Drenec ») — départ ou arrivée SITUÉ DANS le
    # secteur dangereux d'une cardinale : aucun itinéraire ne peut respecter
    # la règle, il faut d'abord en sortir. On n'invente pas de détour, mais on
    # le DIT clairement.
    inside = audit_sides(pts, mlng=mlng, params=p, dir_grid=dir_grid,
                         depth_gate=depth_gate)
    kept = {(round(v["lat"], 6), round(v["lng"], 6)) for v in (remaining or [])}
    exempted = [v for v in inside
                if v.get("kind") == "cardinal"
                and (round(v["lat"], 6), round(v["lng"], 6)) not in kept]
    if exempted:
        res["endpoint_cardinals"] = [
            {"name": v["name"], "dist_m": v["dist_m"],
             "side_required": v["side_required"]}
            for v in exempted[:4]
        ]
        for v in exempted[:2]:
            res.setdefault("warnings", []).insert(0, (
                f"⚠ CARDINALE « {v['name']} » : votre départ ou votre arrivée "
                f"se trouve du côté DANGEREUX (elle doit être laissée "
                f"{v['side_required']}) — sortez du secteur à vue avant de "
                "suivre la route."
            ))


def _reverse_result(res: dict, draft_m: float, depth_margin_m: float,
                    tide_m: float, p: dict[str, Any]) -> dict:
    """Retourne le tracé (l'utilisateur a demandé terre → mer). La GÉOMÉTRIE
    est identique — seuls l'ordre des points et les index de tronçons
    changent, ce qui garantit la RÈGLE 1 (« même route dans les deux sens »)."""
    wps = list(res.get("waypoints") or [])
    if len(wps) < 2:
        return res
    n_legs = len(wps) - 1
    rev = list(reversed(wps))
    grid = get_grid()
    min_depth = max(draft_m + depth_margin_m - float(np.clip(tide_m, -2.0, 6.0)), -2.5)
    fresh = v1._result_for(grid, rev, min_depth)
    out = dict(res)
    out["waypoints"] = fresh["waypoints"]
    out["distance_m"] = fresh["distance_m"]
    out["depth_profile"] = fresh["depth_profile"]
    for key in ("compromised_legs", "low_margin_legs", "shallow_legs_v3"):
        if res.get(key):
            out[key] = sorted(n_legs - 1 - i for i in res[key] if 0 <= i < n_legs)
    if res.get("leg_reasons"):
        out["leg_reasons"] = {
            str(n_legs - 1 - int(k)): v for k, v in res["leg_reasons"].items()
            if 0 <= int(k) < n_legs
        }
    for key in ("corridor_m", "leg_margin_m"):
        if isinstance(res.get(key), list):
            out[key] = list(reversed(res[key]))
    # L'arrivée éventuellement DÉPLACÉE par le moteur est, après retournement,
    # le DÉPART du trajet demandé : on renomme le champ ET on réécrit
    # l'avertissement, sinon l'app annonce « arrivée déplacée » alors que c'est
    # le DÉPART qui a bougé (constaté le 03/08 sur un départ à terre à Vannes).
    if res.get("end_snapped"):
        out.pop("end_snapped", None)
        out["start_snapped"] = res["end_snapped"]
        off = res["end_snapped"].get("offset_m")
        out["warnings"] = [
            w for w in (out.get("warnings") or []) if "arrivée déplacée" not in w
        ]
        out["warnings"].insert(0, (
            "Départ non navigable à cette hauteur d'eau (estran / zone "
            "découvrante) — départ déplacé vers l'eau navigable la plus proche"
            + (f", à ~{round(off)} m." if off else ".")
        ))
    return out


def _straight_line_result(a: Pt, b: Pt, base_need: float) -> dict:
    """Dernier filet de la RÈGLE 4 : même sans aucun passage calculable, on
    rend une ligne droite densifiée (tous les tronçons en rouge)."""
    grid = get_grid()
    mlng = m_per_deg_lng((a[0] + b[0]) / 2)
    seg_m = math.hypot((b[0] - a[0]) * M_PER_DEG_LAT, (b[1] - a[1]) * mlng)
    n = max(2, min(400, int(seg_m / 200.0)))
    wps = [
        {"lat": round(a[0] + (b[0] - a[0]) * k / n, 6),
         "lng": round(a[1] + (b[1] - a[1]) * k / n, 6)}
        for k in range(n + 1)
    ]
    res = v1._result_for(grid, wps, base_need)
    res["mode"] = "auto"
    res["warnings"] = [
        "⚠ AUCUN ITINÉRAIRE CALCULABLE : tracé DIRECT affiché à titre "
        "indicatif — la totalité du parcours est à vérifier À VUE."
    ]
    res["compromised_legs"] = list(range(len(wps) - 1))
    res["leg_reasons"] = {str(i): "shallow" for i in range(len(wps) - 1)}
    return res


__all__ = ["SignalmarV3"]
