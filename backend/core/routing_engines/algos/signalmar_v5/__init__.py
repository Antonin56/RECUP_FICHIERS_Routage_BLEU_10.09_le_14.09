"""SignalMar — Algo « signalmar.v5 » (MOTEUR E, base Moteur D, 11/08/2026).

Consignes armateur du 11/08 (le Moteur D est FIGÉ à cette date) :

* « Il y a encore des ratées de balises » (rouge d'un couple très écarté du
  chenal de Vannes recoupée à 139 m dans 4 m d'eau) ;
* « Le moteur refuse l'arrivée au Crouesty alors que le balisage est clair.
  Il doit impérativement aller jusqu'à l'arrivée » ;
* « On ne DOIT JAMAIS faire d'exception de terrain : les règles doivent
  fonctionner dans toute l'Europe. »

v5 = v4 (Moteur D) + le mode ``SIDE_ABSOLUTE`` + la COMPLÉTION D'ARRIVÉE :

* **Couples rouge/verte — côté absolu.** Demi-disque interdit PLEIN (sans
  condition de fond) jusqu'à 0,8 × l'écartement du couple : « la route doit
  toujours passer ENTRE les bouées ». Couple = RÉCIPROQUE (chacune est
  l'opposée la plus proche de l'autre) — supprime les faux couples des
  chenaux en coude qui scellaient l'entrée du Crouesty.
* **Isolées confiantes — plein inconditionnel** (v4 exigeait encore un
  mauvais côté peu profond à 40-150 m).
* **Plafond de densité** : tous les rayons de côté/écart s'adaptent à la
  densité du balisage (0,6 × la latérale voisine pour les côtés, 0,35 ×
  pour l'écart, plancher 25 m) — dans un chenal de port balisé tous les
  50-100 m, des zones fixes de 60-200 m se recouvrent d'un bord à l'autre
  et rendent le chenal infranchissable. Règle d'échelle universelle.
* **Arrivée JAMAIS tronquée** : si la passe grossière n'atteint pas le point
  demandé (chenal étroit, découvrant au ZH), le dernier tronçon est
  recalculé en mode MARÉE (plancher −2,5 m) en suivant le balisage — les
  segments nécessitant de la hauteur d'eau sont marqués EN ROUGE
  (acceptation du risque), comme le mode « eau peu profonde ».
* **Aucune exception de terrain.**

Les Moteurs A, B, C et D restent STRICTEMENT inchangés (contextvars armés
uniquement le temps d'un calcul v5, caches séparés dans l'index).
"""
from __future__ import annotations

import logging
import math
from typing import Any

from core.routing_engines.algos.signalmar_v1 import core as _v1
from core.routing_engines.algos.signalmar_v4 import SignalmarV4
from core.seamarks import ISOLATED_SIDE_BATHY, SIDE_ABSOLUTE

logger = logging.getLogger("signalmar.routing.v5")

#: Écart d'arrivée au-delà duquel on tente la complétion du dernier tronçon.
_COMPLETE_MIN_M = 60.0
#: … et en-deçà duquel on considère l'arrivée atteinte après complétion.
_DONE_M = 30.0


class SignalmarV5(SignalmarV4):
    id = "signalmar.v5"
    version = "5.1.0"
    description = (
        "Moteur E (base Moteur D figé au 11.08.26) : CÔTÉ ABSOLU du balisage "
        "latéral (couples réciproques infranchissables du mauvais côté "
        "jusqu'à 0,8 × l'écartement, isolées confiantes pleines), rayons "
        "adaptatifs à la densité du balisage (chenaux de port), arrivée "
        "jamais tronquée (dernier tronçon complété en mode marée, EN ROUGE "
        "si hauteur d'eau requise). Aucune exception de terrain. Moteurs "
        "A/B/C/D inchangés."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        tok = SIDE_ABSOLUTE.set(True)
        try:
            res = super().compute_auto(
                start_lat, start_lng, end_lat, end_lng,
                draft_m, depth_margin_m, lateral_margin_m,
                tide_m=tide_m, params=params,
            )
            self._complete_truncated_end(
                res, (end_lat, end_lng),
                draft_m, depth_margin_m, lateral_margin_m, params,
            )
        finally:
            SIDE_ABSOLUTE.reset(tok)
        return res

    def compute_manual(self, *args: Any, **kwargs: Any) -> dict:
        tok = SIDE_ABSOLUTE.set(True)
        try:
            return super().compute_manual(*args, **kwargs)
        finally:
            SIDE_ABSOLUTE.reset(tok)

    # ── Arrivée JAMAIS tronquée (bug armateur 11/08 : Crouesty) ──────────
    def _complete_truncated_end(
        self, res: dict, req_end: tuple[float, float],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        params: dict[str, Any] | None,
    ) -> None:
        """Si l'arrivée a été « déplacée » (chenal étroit / découvrant que la
        passe grossière n'atteint pas au ZH), recalcule le DERNIER tronçon en
        mode MARÉE (plancher −2,5 m) — balisage mode E toujours armé — et le
        fusionne : segments nécessitant de la hauteur d'eau EN ROUGE.
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
                # Moteur D (v4) = v2 + audit, avec nos contextvars E armés.
                ext = super().compute_auto(
                    anchor[0], anchor[1], req_end[0], req_end[1],
                    draft_m, depth_margin_m, lateral_margin_m,
                    tide_m=6.0, params=params,
                )
                ext_w = list(ext.get("waypoints") or [])
            except _v1.RouteError:
                ext_w = []
            esnap = ext.get("end_snapped") if ext else None
            rest = float((esnap or {}).get("offset_m") or 0.0) if ext_w else \
                float(snap.get("offset_m") or 0.0)
            if len(ext_w) < 2:
                ext_w = [{"lat": anchor[0], "lng": anchor[1]}]
            # 11/08 (consigne armateur : « il y a un balisage clair, aucune
            # raison de refuser l'arrivée ») — si l'A* n'atteint TOUJOURS
            # pas le point demandé (MNT faux/découvrant dans un chenal
            # dragué), LE BALISAGE PRIME SUR LA DONNÉE DE FOND : le reste du
            # trajet SUIT LE CHENAL BALISÉ (waypoints décalés du bon côté de
            # chaque latérale), EN ROUGE + acceptation du risque.
            if rest > _DONE_M:
                tail = (float(ext_w[-1]["lat"]), float(ext_w[-1]["lng"]))
                chain = self._buoyed_channel_chain(tail, req_end)
                ext_w = ext_w + chain + [{"lat": req_end[0], "lng": req_end[1]}]
                rest = 0.0
            if len(ext_w) < 2:
                return
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
            if rest > _DONE_M:
                res["end_snapped"] = {
                    "requested": {"lat": req_end[0], "lng": req_end[1]},
                    "offset_m": round(rest),
                }
            else:
                res.pop("end_snapped", None)
            res["warnings"] = [
                w for w in (res.get("warnings") or [])
                if "arrivée déplacée" not in w
            ]
            res["warnings"].insert(0, (
                "⚠ FIN DE ROUTE EN ZONE PEU PROFONDE / DÉCOUVRANTE : le "
                "dernier tronçon suit le chenal balisé jusqu'au point "
                "demandé — les segments EN ROUGE exigent une hauteur de "
                "marée suffisante."))
        except Exception:  # noqa: BLE001
            logger.exception("v5: complétion d'arrivée échouée, résultat rendu tel quel")


    # ── Suivi du chenal balisé (le balisage PRIME sur la donnée de fond) ─
    @staticmethod
    def _buoyed_channel_chain(
        a: tuple[float, float], b: tuple[float, float],
    ) -> list[dict]:
        """Waypoints suivant le balisage latéral entre a et b : chaque
        latérale du corridor produit un point décalé de ~35 m du CÔTÉ
        NAVIGABLE (côté confiant si connu, sinon règle IALA avec la
        direction de progression a→b : verte à tribord en entrant → on
        passe à GAUCHE d'une verte). Trié le long de a→b. Universel."""
        from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
        from core.seamarks import get_seamarks
        sm = get_seamarks()
        if sm is None:
            return []
        mlng = m_per_deg_lng((a[0] + b[0]) / 2)
        de = (b[1] - a[1]) * mlng
        dn = (b[0] - a[0]) * M_PER_DEG_LAT
        seg = math.hypot(de, dn)
        if seg < 1e-6:
            return []
        de, dn = de / seg, dn / seg
        out: list[tuple[float, dict]] = []
        for m in sm.marks:
            if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
                continue
            ve = (m["lng"] - a[1]) * mlng
            vn = (m["lat"] - a[0]) * M_PER_DEG_LAT
            t = ve * de + vn * dn
            if not (25.0 <= t <= seg - 10.0):
                continue
            off = abs(ve * dn - vn * de)
            if off > 250.0:
                continue
            d_conf = sm.mark_dir_confident(m)
            if d_conf is not None:
                ce, cn = d_conf
                u = (cn, -ce) if m["category"] == "port" else (-cn, ce)
            else:
                # règle IALA, sens de progression = a→b (on FINIT une route
                # vers un port : sens conventionnel) : verte laissée à
                # tribord → passage à GAUCHE de la verte, à DROITE d'une rouge.
                u = (-dn, de) if m["category"] == "starboard" else (dn, -de)
            gap = max(0.35 * sm._nearest_lateral_m(m), 25.0) + 10.0
            out.append((t, off, {
                "lat": round(m["lat"] + u[1] * gap / M_PER_DEG_LAT, 6),
                "lng": round(m["lng"] + u[0] * gap / mlng, 6),
            }))
        out.sort(key=lambda x: x[0])
        # 11/08 soir (bug armateur « embardée à l'entrée du port ») — DEUX
        # balises quasi à la même abscisse le long de a→b (coude, quinconce
        # serré) produisaient deux points décalés de part et d'autre → dents
        # de scie de ±40 m. Dans une fenêtre de 50 m le long de l'axe, on ne
        # garde que la balise la PLUS PROCHE de l'axe (le point le plus
        # « dans le chenal ») — lissage géométrique universel.
        picked: list[tuple[float, float, dict]] = []
        for t, off, w in out:
            if picked and t - picked[-1][0] < 50.0:
                if off < picked[-1][1]:
                    picked[-1] = (t, off, w)
                continue
            picked.append((t, off, w))
        chain: list[dict] = []
        for _t, _off, w in picked[:20]:
            if chain and math.hypot(
                    (w["lat"] - chain[-1]["lat"]) * M_PER_DEG_LAT,
                    (w["lng"] - chain[-1]["lng"]) * mlng) < 20.0:
                continue
            chain.append(w)
        return chain


__all__ = ["SignalmarV5"]
