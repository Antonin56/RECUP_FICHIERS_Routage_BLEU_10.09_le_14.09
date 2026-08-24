"""SignalMar — Algo « signalmar.v6 » (MOTEUR F, base Moteur E, 13/08/2026).

Consigne armateur du 13/08 : « Le Moteur E est le meilleur. Tu le copies pour
créer le Moteur F, et tu VERROUILLES le Moteur E. » Le Moteur E (signalmar.v5,
5.1.0) est donc FIGÉ à cette date — plus aucune modification de son code ni
de ses chemins gardés par ``SIDE_ABSOLUTE``.

v6 = v5 + les corrections du 13/08 (bugs armateur, route
R-20260813-144317-MX Arradon → La Trinité), gardées par le contextvar
``SIDE_ABSOLUTE_V6`` et par des surcharges LOCALES à cette classe — les
Moteurs A/B/C/D/E restent STRICTEMENT inchangés :

1. **RESPECT DU CÔTÉ garanti** (« Truie d'Arradon » recoupée à 165 m du
   mauvais côté MALGRÉ l'avertissement) : post-correction géométrique
   ``sidefix.enforce_mark_sides`` — chaque latérale fiable laissée du
   mauvais côté est réparée (re-calcul local pleine résolution, sinon point
   de passage du bon côté), puis les frôlements résiduels sont écartés
   (« passe à ~1 m de N°4 »). Indépendant de la maille, jamais bloquant.
2. **Complétion d'arrivée disciplinée** (balises du chenal de La Trinité
   non respectées) : si l'extension A* (marée +6 m) laisse une latérale
   fiable du mauvais côté ou frôle une balise, elle est REMPLACÉE par le
   suivi du chenal balisé (le balisage PRIME sur la donnée de fond).
3. **Arrivée réellement atteinte** : le reliquat est désormais MESURÉ
   géométriquement (l'extension pouvait s'arrêter à un nœud de grille à
   ~100 m du point demandé sans le signaler).
"""
from __future__ import annotations

import logging
import math
from typing import Any

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos.signalmar_v1 import core as _v1
from core.routing_engines.algos.signalmar_v2.standoff import _closest_on, _d_m
from core.routing_engines.algos.signalmar_v4 import SignalmarV4
from core.routing_engines.algos.signalmar_v5 import (
    SignalmarV5, _COMPLETE_MIN_M, _DONE_M,
)
from core.routing_engines.algos.signalmar_v6 import sidefix
from core.seamarks import SIDE_ABSOLUTE, SIDE_ABSOLUTE_V6, get_seamarks

logger = logging.getLogger("signalmar.routing.v6")

# 14/08/2026 (audit QA P0/FND-004) — au-delà de cette « profondeur » (fond
# à plus de 3,5 m AU-DESSUS du zéro hydro), ce n'est plus une zone
# découvrante mais la TERRE FERME : aucun tronçon de route n'a le droit d'y
# être tracé, quelle que soit la marée.
_LAND_LIMIT_M = -3.5


class SignalmarV6(SignalmarV5):
    id = "signalmar.v6"
    version = "6.1.0"
    description = (
        "Moteur F (base Moteur E figé au 13.08.26) : respect du CÔTÉ des "
        "balises GARANTI sur le tracé final (réparation géométrique + "
        "re-calcul local pleine résolution, indépendant de la maille), "
        "complétion d'arrivée disciplinée par le balisage (le chenal balisé "
        "prime sur la donnée de fond), arrivée réellement atteinte. "
        "Moteurs A/B/C/D/E inchangés."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        tok6 = SIDE_ABSOLUTE_V6.set(True)
        # SIDE_ABSOLUTE armé sur TOUTE la durée (post-passes incluses) :
        # rayons adaptatifs + caches v5 pour l'audit et les réparations.
        tok5 = SIDE_ABSOLUTE.set(True)
        try:
            res = super().compute_auto(
                start_lat, start_lng, end_lat, end_lng,
                draft_m, depth_margin_m, lateral_margin_m,
                tide_m=tide_m, params=params,
            )
            # Mêmes bornes/dérivées que le moteur (cf. v2.compute_auto).
            draft = float(min(max(draft_m, _v1.DRAFT_MIN), _v1.DRAFT_MAX))
            marg = float(min(max(depth_margin_m, _v1.DEPTH_MARGIN_MIN),
                             _v1.DEPTH_MARGIN_MAX))
            lat_m = float(min(max(lateral_margin_m, _v1.LATERAL_MIN),
                              _v1.LATERAL_MAX))
            tide = float(min(max(tide_m, -2.0), 6.0))
            try:
                res = sidefix.enforce_mark_sides(
                    res,
                    start=(start_lat, start_lng),
                    requested_end=(end_lat, end_lng),
                    draft_m=draft_m, depth_margin_m=depth_margin_m,
                    lateral_margin_m=lat_m, tide_m=tide,
                    min_depth=max(draft + marg - tide, -2.5),
                    relaxed_depth=max(draft + marg - 6.0, -2.5),
                    strict_depth=draft + marg + 2.0,
                    base_need=max(draft + marg, -2.5),
                    params=params,
                )
            except Exception:  # noqa: BLE001 — jamais bloquant
                logger.exception("v6: sidefix en échec, résultat rendu tel quel")
        finally:
            SIDE_ABSOLUTE.reset(tok5)
            SIDE_ABSOLUTE_V6.reset(tok6)
        return res

    def compute_manual(self, *args: Any, **kwargs: Any) -> dict:
        # Route MANUELLE : jamais déplacée (intention explicite) — audit v5.
        tok = SIDE_ABSOLUTE_V6.set(True)
        try:
            return super().compute_manual(*args, **kwargs)
        finally:
            SIDE_ABSOLUTE_V6.reset(tok)

    # ── Complétion d'arrivée v6 (surcharge de la v5, Moteur E figé) ──────
    @staticmethod
    def _ext_violates(ext_w: list[dict], req_end: tuple[float, float]) -> bool:
        """True si l'extension A* enfreint la discipline du chenal : latérale
        FIABLE laissée du mauvais côté (≤ 250 m — on est DANS le chenal
        d'arrivée, le balisage prime) ou balise nettement frôlée
        (< 0,6 × écart recommandé)."""
        sm = get_seamarks()
        if sm is None or len(ext_w) < 2:
            return False
        pts = [(float(w["lat"]), float(w["lng"])) for w in ext_w]
        la = [q[0] for q in pts]
        lo = [q[1] for q in pts]
        mlng = m_per_deg_lng((min(la) + max(la)) / 2)
        exempt = (pts[0], req_end)
        for m in sm.marks:
            if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
                continue
            if not (min(la) - 0.01 <= m["lat"] <= max(la) + 0.01
                    and min(lo) - 0.01 <= m["lng"] <= max(lo) + 0.01):
                continue
            if any(_d_m(q, m["lat"], m["lng"], mlng) < 200.0 for q in exempt):
                continue
            u = sidefix.required_side_u(sm, m)
            if u is None:
                continue
            d, _i, p = _closest_on(pts, m["lat"], m["lng"], mlng)
            if d <= 250.0 and sidefix._wrong_side(m, u, p, mlng):
                return True
        for (m_lat, m_lng2, r_std, _name) in sm.standoff_circles(
                min(la) - 0.005, max(la) + 0.005,
                min(lo) - 0.005, max(lo) + 0.005):
            if any(_d_m(q, m_lat, m_lng2, mlng) < 200.0 for q in exempt):
                continue
            d, _i, _p = _closest_on(pts, m_lat, m_lng2, mlng)
            if d < 0.6 * r_std:
                return True
        return False

    def _complete_truncated_end(
        self, res: dict, req_end: tuple[float, float],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        params: dict[str, Any] | None,
    ) -> None:
        """Version Moteur F de la complétion v5 : (1) extension A* REJETÉE si
        elle enfreint la discipline du chenal (→ suivi du balisage), (2)
        reliquat d'arrivée MESURÉ géométriquement (l'extension pouvait finir
        sur un nœud de grille à ~100 m du point demandé sans le signaler).
        Jamais bloquant : en cas d'échec, le résultat initial est rendu."""
        try:
            snap = res.get("end_snapped")
            wps = res.get("waypoints") or []
            if (not snap or len(wps) < 2
                    or not (_COMPLETE_MIN_M
                            <= float(snap.get("offset_m") or 0) <= 3000.0)):
                return
            anchor = (float(wps[-1]["lat"]), float(wps[-1]["lng"]))
            ext_w: list[dict] = []
            ext: dict = {}
            try:
                # Même moteur d'extension que la v5 : Moteur D (v4) en mode
                # MARÉE (plancher −2,5 m), contextvars E/F déjà armés.
                ext = SignalmarV4.compute_auto(
                    self,
                    anchor[0], anchor[1], req_end[0], req_end[1],
                    draft_m, depth_margin_m, lateral_margin_m,
                    tide_m=6.0, params=params,
                )
                ext_w = list(ext.get("waypoints") or [])
            except _v1.RouteError:
                ext_w = []
            # 13/08 (Moteur F) — LE BALISAGE PRIME : une extension qui laisse
            # une latérale fiable du mauvais côté ou frôle une balise (la
            # marée +6 m « ouvre » la vasière et l'A* coupe tout droit) est
            # remplacée par le suivi du chenal balisé.
            if len(ext_w) >= 2 and self._ext_violates(ext_w, req_end):
                ext_w = []
                ext = {}
            if len(ext_w) < 2:
                # 13/08 (Moteur F) — l'ANCRE elle-même peut être une arrivée
                # RELOGÉE en plein platier (nearest_reachable) : la route
                # principale y arrivait en frôlant N°4 à 0,7 m. On RECULE
                # l'ancre tant que le dernier tronçon enfreint la discipline
                # du chenal (≤ 5 crans), puis le suivi du balisage reprend
                # tout le trajet manquant.
                for _ in range(5):
                    if len(wps) < 3:
                        break
                    d_last = math.hypot(
                        (float(wps[-1]["lat"]) - req_end[0]) * M_PER_DEG_LAT,
                        (float(wps[-1]["lng"]) - req_end[1]) * m_per_deg_lng(req_end[0]))
                    d_prev = math.hypot(
                        (float(wps[-2]["lat"]) - req_end[0]) * M_PER_DEG_LAT,
                        (float(wps[-2]["lng"]) - req_end[1]) * m_per_deg_lng(req_end[0]))
                    overshoot = d_last > d_prev + 10.0  # on DÉPASSAIT l'arrivée
                    if not overshoot and not self._ext_violates(
                            [wps[-2], wps[-1]], req_end):
                        break
                    wps = wps[:-1]
                anchor = (float(wps[-1]["lat"]), float(wps[-1]["lng"]))
                ext_w = [{"lat": anchor[0], "lng": anchor[1]}]
            # 13/08 (Moteur F) — reliquat GÉOMÉTRIQUE (la v5 se fiait à
            # ``end_snapped`` de l'extension, absent quand l'A* s'arrête sur
            # un nœud de grille à ~100 m du point demandé).
            tail = (float(ext_w[-1]["lat"]), float(ext_w[-1]["lng"]))
            rest = math.hypot((tail[0] - req_end[0]) * M_PER_DEG_LAT,
                              (tail[1] - req_end[1]) * m_per_deg_lng(tail[0]))
            if rest > _DONE_M:
                chain = self._buoyed_channel_chain(tail, req_end)
                ext_w = ext_w + chain + [{"lat": req_end[0], "lng": req_end[1]}]
                rest = 0.0
            if len(ext_w) < 2:
                return
            # 14/08 (audit QA P0/FND-004) — JAMAIS DE TRONÇON SUR TERRE : le
            # point demandé peut être à terre (clic dans le port, quai…). Le
            # tronçon ajouté est sondé tous les ~25 m ; au premier
            # échantillon TERRE FERME (fond < −3,5 m au ZH ou hors donnée)
            # la route est TRONQUÉE au dernier point EN EAU et l'arrivée est
            # honnêtement signalée déplacée (fini le tracé qui grimpe à
            # −15 m sur le Crouesty avec un message rassurant).
            landed = False
            grid0 = _v1.get_grid()
            if grid0 is not None:
                kept = [ext_w[0]]
                for k in range(1, len(ext_w)):
                    a = kept[-1]
                    b = ext_w[k]
                    a_ll = (float(a["lat"]), float(a["lng"]))
                    b_ll = (float(b["lat"]), float(b["lng"]))
                    seg_m = math.hypot(
                        (b_ll[0] - a_ll[0]) * M_PER_DEG_LAT,
                        (b_ll[1] - a_ll[1]) * m_per_deg_lng(a_ll[0]))
                    n = max(2, int(seg_m / 25.0) + 1)
                    cut_t = None
                    for s in range(1, n + 1):
                        t = s / n
                        d = grid0.depth_at(
                            a_ll[0] + (b_ll[0] - a_ll[0]) * t,
                            a_ll[1] + (b_ll[1] - a_ll[1]) * t)
                        if d is None or d < _LAND_LIMIT_M:
                            cut_t = (s - 1) / n
                            break
                    if cut_t is None:
                        kept.append(b)
                        continue
                    if cut_t > 0.1:  # garde le dernier point encore EN EAU
                        kept.append({
                            "lat": round(a_ll[0] + (b_ll[0] - a_ll[0]) * cut_t, 6),
                            "lng": round(a_ll[1] + (b_ll[1] - a_ll[1]) * cut_t, 6),
                        })
                    landed = True
                    break
                if landed:
                    ext_w = kept
            n0 = len(wps) - 1
            merged = wps + [
                {"lat": float(w["lat"]), "lng": float(w["lng"])}
                for w in ext_w[1:]
            ]
            base_need = max(draft_m + depth_margin_m, -2.5)   # seuil au ZH
            comp = [i for i in _v1.shallow_legs(merged, base_need) if i >= n0]
            res["waypoints"] = merged
            if comp:
                res["compromised_legs"] = sorted(
                    set(res.get("compromised_legs") or []) | set(comp))
                res["risk"] = True
            # Balises du mauvais côté détectées sur l'extension : remontées.
            if ext.get("wrong_side_marks"):
                seen = {v.get("name") for v in (res.get("wrong_side_marks") or [])}
                res["wrong_side_marks"] = (res.get("wrong_side_marks") or []) + [
                    v for v in ext["wrong_side_marks"] if v.get("name") not in seen]
            # Distance + profil de profondeur recalculés sur le tracé complet.
            grid = _v1.get_grid()
            if grid is not None:
                fresh = _v1._result_for(grid, merged, base_need)
                for k in ("depth_profile", "min_depth_m", "distance_m"):
                    if k in fresh:
                        res[k] = fresh[k]
            res.pop("end_snapped", None)
            # 14/08 (Moteur F) — les avertissements de FRÔLEMENT du tracé
            # d'AVANT fusion/recul d'ancre deviennent obsolètes (le warning
            # « passe à ~1 m de N°4 » restait alors que le tronçon fautif
            # avait été remplacé) : purge + ré-audit du tracé fusionné.
            start_pt = (float(merged[0]["lat"]), float(merged[0]["lng"]))
            res["warnings"] = [
                w for w in (res.get("warnings") or [])
                if "arrivée déplacée" not in w
                and not w.startswith("⚠ La route passe à ~")
                and not w.startswith("Passage à ")
            ]
            res["warnings"].extend(
                _v1._mark_pass_audit(merged, (start_pt, req_end)))
            res["warnings"] = list(dict.fromkeys(res["warnings"]))
            # 13/08 (Moteur F) — avertissement « EN ROUGE » seulement s'il y
            # a réellement des tronçons compromis (le suivi du chenal balisé
            # trouve souvent la veine d'eau : pas de rouge, pas de peur).
            # 14/08 (audit QA P0) — arrivée à TERRE : ``end_snapped`` honnête
            # (offset mesuré) + avertissement franc, plus jamais de message
            # « suit le chenal balisé » sur un point injoignable en bateau.
            if landed:
                last = merged[-1]
                off_land = math.hypot(
                    (float(last["lat"]) - req_end[0]) * M_PER_DEG_LAT,
                    (float(last["lng"]) - req_end[1]) * m_per_deg_lng(req_end[0]))
                res["end_snapped"] = {
                    "offset_m": round(off_land, 1),
                    "reason": "arrivee_a_terre",
                }
                res["warnings"].insert(0, (
                    f"⚠ ARRIVÉE DEMANDÉE À TERRE / NON NAVIGABLE : la route "
                    f"s'arrête au dernier point en eau, à {off_land:.0f} m du "
                    f"point demandé. Déplacez l'arrivée sur l'eau pour aller "
                    f"plus loin."))
            elif comp:
                res["warnings"].insert(0, (
                    "⚠ FIN DE ROUTE EN ZONE PEU PROFONDE / DÉCOUVRANTE : le "
                    "dernier tronçon suit le chenal balisé jusqu'au point "
                    "demandé — les segments EN ROUGE exigent une hauteur de "
                    "marée suffisante."))
            else:
                res["warnings"].insert(0, (
                    "Le dernier tronçon suit le chenal balisé jusqu'au "
                    "point demandé."))
        except Exception:  # noqa: BLE001
            # 14/08 (audit QA FND-040) — une complétion en ÉCHEC n'est plus
            # silencieuse : le client sait que la route rendue est tronquée.
            res["completion_failed"] = True
            logger.exception("v6: complétion d'arrivée échouée, résultat rendu tel quel")


__all__ = ["SignalmarV6"]
