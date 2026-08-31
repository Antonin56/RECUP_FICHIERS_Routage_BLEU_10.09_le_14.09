"""SignalMar — API de routage marin (V2 phase N1, 20/07/2026).

POST /api/routes/compute {start, end, draft_m, depth_margin_m,
lateral_margin_m} → waypoints + profil de profondeur. Authentifié.
22/07/2026 : + POST /routes/manual (route manuelle → distance/profil),
CRUD /routes/saved (max 20 routes enregistrées par utilisateur)."""
from __future__ import annotations

import asyncio
import functools as _functools
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import server as srv
from core.auth import current_user
from core.bathy import get_grid
from core.routing import RouteError, compute_route, manual_route, nearest_navigable, shallow_legs
from core.routing_engines import (
    bump_usage as _engine_bump_usage,
    get_engine as _get_engine,
    get_engine_or_default as _get_engine_or_default,
    resolve_algo as _resolve_algo_db,
)
from core.routing_engines.algos import get_algo as _get_algo
from core.seamarks import MOORINGS_OPEN, SIDE_RULES_OPEN
from core.support_admin import is_signalmar_admin
from core.tides import _haversine_km, tide_crossings, tide_window
from routers.beta import is_beta_tester

logger = logging.getLogger("signalmar.routing")
router = APIRouter(prefix="/routes", tags=["routes"])

_PARIS = ZoneInfo("Europe/Paris")


def _resolve_algo(engine_doc: dict):
    """27/08/2026 (ordre armateur — MAINTENANCE CRITIQUE) : le Moteur F
    (``engine_f``) pointe EXCLUSIVEMENT vers la copie GELÉE
    ``core/nav/engine_f_frozen.py`` (algo ``signalmar.f_frozen``), quel que
    soit son binding en base. Le Moteur F est une référence IMMUABLE — toute
    évolution se fait sur le Moteur I (``core/nav/engine_i.py``)."""
    if (engine_doc or {}).get("id") == "engine_f":
        return _get_algo("signalmar.f_frozen")
    return _resolve_algo_db(engine_doc)


# ── 31/07/2026 — ID PUBLIC DE ROUTE (support armateur) ─────────────────────
# Chaque route calculée (auto ou manuelle) reçoit un identifiant lisible
# `R-YYYYMMDD-HHMMSS-XX` (timestamp UTC + suffixe alphanumérique aléatoire
# 2 caractères, évite les collisions si deux calculs partagent la même
# seconde) et est persistée dans la collection `computed_routes` (TTL 30 j,
# index créé au démarrage). L'armateur peut me communiquer cet ID pour que
# je consulte les paramètres exacts + le tracé à des fins de diagnostic
# via GET /api/routes/inspect/{id} (endpoint verrouillé sur son compte).
_ID_SUFFIX_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _new_route_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suf = "".join(secrets.choice(_ID_SUFFIX_ALPHABET) for _ in range(2))
    return f"R-{ts}-{suf}"


async def _persist_route(
    route_id: str, user: dict, kind: str, request_body: dict, result: dict,
    engine_doc: dict | None = None,
) -> None:
    """Stocke la route (params + tracé) pour consultation ultérieure par le
    support. Best-effort : jamais bloquant pour l'appelant.

    ``engine_doc`` (01/08/2026) : le doc du moteur utilisé — sert à tagger
    la route persistée (``engine_id``, ``engine_name``, ``algo_id``) et à
    incrémenter le compteur d'usage du moteur."""
    try:
        engine_id = (engine_doc or {}).get("id")
        engine_name = (engine_doc or {}).get("name")
        algo_id = (engine_doc or {}).get("algo")
        await srv.db.computed_routes.insert_one({
            "route_id": route_id,
            "user_id": user.get("user_id"),
            "user_phone": user.get("phone"),
            "kind": kind,  # "auto" | "manual"
            "engine_id": engine_id,
            "engine_name": engine_name,
            "algo_id": algo_id,
            "request": request_body,
            "result": result,
            "created_at": datetime.now(timezone.utc),
        })
        if engine_id:
            await _engine_bump_usage(srv.db, engine_id)
    except Exception as exc:  # noqa: BLE001 — best-effort logging
        logger.warning("route persist failed id=%s err=%s", route_id, exc)


# ── 29/07/2026 (décision armateur — calcul « façon Navionics ») ────────────
# ROUTAGE 100 % AU ZH : la marée temps réel n'entre PLUS dans le calcul des
# routes (Open-Meteo ≈ approximation ; en attente de l'abonnement SHOM pro).
# Tout le code marée (hauteur au départ, repli marée, fenêtres/validité,
# « passera à partir de… ») est CONSERVÉ mais NEUTRALISÉ par ce drapeau —
# remettre à True pour le réactiver tel quel.
TIDE_ROUTING_ENABLED = False


def _fmt_local(ts: float) -> str:
    """HH:MM heure locale, + « demain » / « le JJ/MM » si autre jour."""
    d = datetime.fromtimestamp(ts, _PARIS)
    now = datetime.now(_PARIS)
    s = d.strftime("%H:%M")
    delta = (d.date() - now.date()).days
    if delta == 0:
        return s
    if delta == 1:
        return f"{s} demain"
    return f"{s} le {d.strftime('%d/%m')}"

# 20/07/2026 (demande armateur) — BYPASS COMPTES DE TEST : quand le point de
# DÉPART est hors zone pilote ou à terre (testeur dans les terres), on le
# remplace par un point navigable au large d'ARRADON (centre du Golfe,
# profondeur 4.8 m ZH) pour pouvoir tester le routage. Jamais pour la
# destination, jamais pour les comptes normaux.
ARRADON_FALLBACK = {"lat": 47.610, "lng": -2.825, "name": "Arradon"}

# 23/07/2026 — mode AUTO : plancher de sécurité latéral. La marge réelle
# s'adapte au chenal via l'attraction milieu-de-chenal du moteur (cost_extra).
AUTO_LATERAL_M = 10.0

# 27/07/2026 (consigne armateur, vidéo) — MARÉE À H+30 MIN : quand on calcule
# une route, le bateau ne sera pas sur zone avant ~30 min → la hauteur d'eau
# utilisée est celle PRÉVUE 30 min après l'heure du calcul (marge de sécurité
# supplémentaire — évite les routes valables « à la minute près »).
TIDE_LEAD_S = 1800.0


class Point(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RouteIn(BaseModel):
    start: Point
    end: Point
    draft_m: float = Field(1.5, ge=0.2, le=4)
    depth_margin_m: float = Field(0.5, ge=0, le=3)
    # 23/07/2026 — MODE AUTO (défaut, demande armateur) : champ ABSENT/None →
    # le moteur applique le plancher de sécurité (10 m) et l'attraction vers
    # le MILIEU du chenal : la marge réelle S'ADAPTE à la largeur disponible
    # (large au large, réduite dans les passes étroites). Une valeur fournie
    # = mode MANUEL (réglage « Mon bateau »), relâchée par paliers si besoin.
    lateral_margin_m: float | None = Field(None, ge=10, le=500)
    # 22/07/2026 (GO armateur) — intégrer la hauteur de marée au départ.
    use_tide: bool = False
    # Heure de départ (epoch s UTC). None/absent = maintenant.
    departure_ts: float | None = Field(None, ge=0)
    # 01/08/2026 — Moteur de routage à utiliser. Si absent, on résout dans
    # cet ordre : preference utilisateur (``user.active_engine_id``) →
    # ``engine_a`` (built-in). Admin uniquement peut demander un moteur
    # différent de sa préférence utilisateur (via ce champ).
    engine_id: str | None = Field(None, min_length=1, max_length=48)
    # 25/07 (demande armateur — « route dangereuse ») : hauteur d'eau de
    # sécurité SUPPLÉMENTAIRE pour recalculer une route plus sûre (+2 m).
    safety_extra_m: float = Field(0, ge=0, le=5)


def _fallback_route(e: RouteError, body: "RouteIn") -> dict:
    """24/07/2026 (demande armateur) — ROUTE DE SECOURS « douteuse » : quand
    l'A* échoue mais qu'un tronçon partiel existe, on livre quand même une
    route = tronçon sûr + segment DIRECT jusqu'à la destination. Le front
    l'affiche avec le segment compromis EN ROUGE et exige l'acceptation du
    risque avant de pouvoir la suivre."""
    payload = e.payload or {}
    pw = payload.get("partial_waypoints")
    if not pw or len(pw) < 2:
        return {}
    wps = list(pw) + [{"lat": round(body.end.lat, 6), "lng": round(body.end.lng, 6)}]
    dist = 0.0
    for i in range(len(wps) - 1):
        dist += _haversine_km(
            wps[i]["lat"], wps[i]["lng"], wps[i + 1]["lat"], wps[i + 1]["lng"],
        ) * 1000.0
    return {
        "fallback_route": {
            "waypoints": wps,
            # Index du DERNIER waypoint sûr = début du tronçon compromis.
            "compromised_from": len(pw) - 1,
            "distance_m": round(dist, 0),
        }
    }


@router.post("/compute")
async def routes_compute(body: RouteIn, user: dict = Depends(current_user)):
    t0 = time.monotonic()
    # 01/08/2026 — Résolution du moteur de routage (multi-engine A/B/…).
    #  1. Si le body précise ``engine_id`` : on le prend (admin) OU on le
    #     tolère pour tout utilisateur si le moteur existe et est actif
    #     (nécessaire pour la fonction « recalculer avec un autre moteur »
    #     depuis la carte des routes enregistrées).
    #  2. Sinon : preference perso ``user.active_engine_id``.
    #  3. Sinon : moteur par défaut (``engine_a``).
    # Résultat : shadow des symboles locaux ``compute_route`` / ``manual_route``
    # avec les méthodes de l'algo lié — TOUTES les closures internes utilisent
    # ainsi le bon algo automatiquement, sans modifier chaque call site.
    requested_engine_id = body.engine_id or user.get("active_engine_id")
    # 14/08/2026 (audit QA FND-003) — un ``engine_id`` EXPLICITE inconnu ou
    # désactivé est REFUSÉ (404) : plus jamais de bascule silencieuse vers le
    # Moteur A. La préférence perso, elle, retombe sur le défaut (tolérant).
    if body.engine_id:
        engine_doc = await _get_engine(srv.db, body.engine_id)
        if not engine_doc or not engine_doc.get("active"):
            raise HTTPException(
                status_code=404,
                detail=f"Moteur « {body.engine_id} » introuvable ou désactivé.")
    else:
        engine_doc = await _get_engine_or_default(srv.db, requested_engine_id)
    _algo = _resolve_algo(engine_doc)
    # 02/08/2026 — les overrides de paramètres du MOTEUR sont transmis à
    # l'algo (v1 les ignore, v2+ les utilise : écart minimal aux balises…).
    compute_route = _functools.partial(  # type: ignore[assignment]  # noqa: F811
        _algo.compute_auto, params=(engine_doc.get("params") or {}),
    )
    # 25/07 — route « plus sûre » : la hauteur de sécurité supplémentaire est
    # simplement ajoutée à la marge de fond (min_depth += safety_extra_m
    # partout, y compris marée et fallbacks).
    if body.safety_extra_m:
        body = body.model_copy(
            update={"depth_margin_m": body.depth_margin_m + body.safety_extra_m},
        )
    start_lat, start_lng = body.start.lat, body.start.lng
    start_fallback: str | None = None

    # Bypass testeurs : départ hors couverture → Arradon d'office (évite un
    # aller-retour d'erreur) ; départ à terre/bloqué → retenté plus bas.
    grid = get_grid()
    is_tester = await is_beta_tester(user)
    if is_tester and grid is not None and not grid.covers(start_lat, start_lng):
        start_lat, start_lng = ARRADON_FALLBACK["lat"], ARRADON_FALLBACK["lng"]
        start_fallback = ARRADON_FALLBACK["name"]

    # 22/07/2026 — MARÉE À L'INSTANT T (26/07, décision armateur : la marée à
    # l'heure de PASSAGE par tronçon est reportée en V2). Hauteur d'eau
    # RELEVÉE AU MOMENT DU CALCUL (≈ / ZH, Open-Meteo) au port le plus proche
    # du départ. La fenêtre [départ, départ + durée estimée] n'est plus que
    # INFORMATIVE (mini affiché à l'utilisateur pour l'avertir que la marée
    # évolue). Échec réseau → marée basse.
    tide_m = 0.0
    tide_info: dict | None = None
    tide_warning: str | None = None
    tide_ref: tuple[float, float] | None = None  # port de référence marée
    dep = float(int(((body.departure_ts or time.time()) + TIDE_LEAD_S) // 600) * 600)
    if TIDE_ROUTING_ENABLED and body.use_tide:
        # 24/07/2026 (bug armateur « itinéraires différents au même moment »)
        # — DÉTERMINISME : l'heure de départ est ARRONDIE au pas de 10 min.
        # Avant, dep = time.time() à la seconde près → hauteur de marée
        # légèrement différente à chaque appel → cellules limites basculant
        # navigable/bloqué → tracé A* différent pour la MÊME demande. La
        # marée ne varie pas significativement en 10 min : deux demandes
        # identiques dans la même fenêtre donnent désormais la MÊME route.
        tide_ref = (start_lat, start_lng)
        dist_km = _haversine_km(start_lat, start_lng, body.end.lat, body.end.lng)
        window_h = min(12.0, max(1.0, dist_km * 1.3 / 8.0 + 0.5))
        tw = await tide_window(start_lat, start_lng, dep, window_h)
        if tw is None:
            tide_warning = (
                "Marée indisponible — route calculée à MARÉE BASSE (sécuritaire)."
            )
        else:
            # 26/07 (décision armateur) — hauteur AU MOMENT DU CALCUL, plus le
            # minimum de la fenêtre (trop conservateur : coupait la Vilaine
            # alors que la marée était remontée à l'heure de passage réelle).
            tide_m = max(-2.0, tw["height_start_m"])
            tide_info = {**tw, "departure_ts": dep}

    # 23/07/2026 (bug vidéo armateur, marge 260 m) — RELAXATION AUTOMATIQUE de
    # la marge latérale : une marge « confort » large ferme TOUS les chenaux
    # plus étroits que 2×marge (Golfe du Morbihan ≈ 500 m → aucune route).
    # Tirant d'eau + marge de fond restent STRICTS ; seule la marge latérale
    # est réduite par paliers (÷2, plancher 10 m) DEPUIS LA VALEUR CONFIGURÉE
    # et la route l'ANNONCE (warning + lateral_margin_used_m). Codes hors
    # marge (out_of_coverage…) → échec immédiat, pas de retry inutile.
    _RELAX_CODES = {"no_route", "start_blocked", "end_blocked"}
    auto_margin = body.lateral_margin_m is None
    req_margin = AUTO_LATERAL_M if auto_margin else float(body.lateral_margin_m)
    used_margin = req_margin

    async def _run(s_lat: float, s_lng: float, tide: float,
                   allow_last_resort: bool = True,
                   margin_box: list | None = None):
        nonlocal used_margin

        # 27/08/2026 (perf) — ``margin_box`` : suivi de marge LOCAL pour les
        # exécutions PARALLÈLES (cf. _run_zh_tide) ; sans box, comportement
        # historique (nonlocal used_margin).
        def _set_margin(v: float) -> None:
            nonlocal used_margin
            if margin_box is not None:
                margin_box[0] = v
            else:
                used_margin = v

        def _get_margin() -> float:
            return margin_box[0] if margin_box is not None else used_margin

        margins = [req_margin]
        while margins[-1] > 10.0:
            margins.append(max(10.0, margins[-1] / 2.0))
        first: RouteError | None = None

        async def _last_resort():
            """26/07 — « aucun autre passage ». 27/07 (vidéo 15h45) : ÉTAGÉ —
            étage 1 : zones de mouillage ouvertes SEULEMENT ; étage 2 : + les
            règles de CÔTÉ du balisage latéral levées (sens conventionnel
            parfois faux, ex. Vilaine). L'ÉCART MINIMAL aux balises n'est
            plus JAMAIS levé (route SUR la balise Holavre/n°6 en vidéo).
            Retourne le résultat annoté, ou None."""
            for stage in ("moorings", "side"):
                tok_m = MOORINGS_OPEN.set(True)
                tok_s = SIDE_RULES_OPEN.set(True) if stage == "side" else None
                try:
                    res = await asyncio.to_thread(
                        compute_route,
                        s_lat, s_lng,
                        body.end.lat, body.end.lng,
                        body.draft_m, body.depth_margin_m, margins[-1],
                        tide,
                    )
                except RouteError:
                    res = None
                finally:
                    if tok_s is not None:
                        SIDE_RULES_OPEN.reset(tok_s)
                    MOORINGS_OPEN.reset(tok_m)
                if res is None:
                    continue
                _set_margin(margins[-1])
                if stage == "moorings":
                    res.setdefault("warnings", []).insert(
                        0,
                        "⚠ Route « aucun autre passage » : zones de mouillage "
                        "traversées — vitesse très réduite, attention aux "
                        "corps-morts et aux bateaux au mouillage.",
                    )
                else:
                    res.setdefault("warnings", []).insert(
                        0,
                        "⚠ Route « aucun autre passage » : zones de mouillage "
                        "traversées et règles de CÔTÉ du balisage latéral levées "
                        "— vitesse très réduite, vérifiez le balisage À VUE "
                        "(bouées, corps-morts) sur tout le parcours.",
                    )
                res["through_moorings"] = True
                return res
            return None

        for m in margins:
            try:
                res = await asyncio.to_thread(
                    compute_route,
                    s_lat, s_lng,
                    body.end.lat, body.end.lng,
                    body.draft_m, body.depth_margin_m, m,
                    tide,
                )
                _set_margin(m)
                # 26/07 (bug Vilaine) — arrivée fortement déplacée (> 800 m) :
                # le blocage vient parfois du BALISAGE (sens conventionnel
                # faux) et non du fond. On tente aussi le dernier recours et
                # on le préfère s'il approche NETTEMENT plus la destination.
                off = float((res.get("end_snapped") or {}).get("offset_m") or 0.0)
                if off > 800.0 and allow_last_resort:
                    kept_margin = _get_margin()
                    res2 = await _last_resort()
                    off2 = float((res2.get("end_snapped") or {}).get("offset_m") or 0.0) if res2 else None
                    if res2 is not None and off2 is not None and off2 < off - 500.0:
                        return res2
                    _set_margin(kept_margin)
                return res
            except RouteError as e:
                first = first or e
                if e.code not in _RELAX_CODES:
                    raise
        # Tous les paliers ont échoué → 26/07 (demande armateur) : DERNIER
        # RECOURS « aucun autre passage » — on ré-essaie avec les zones de
        # mouillage OUVERTES. Le tirant d'eau + marge de fond restent
        # contrôlés partout ; la route est clairement annoncée.
        # 28/07 (découplage marée) : la tentative ZH SAUTE le dernier recours
        # quand un repli marée existe (inutile d'ouvrir les mouillages pour
        # rester à marée basse — la marée est essayée d'abord).
        if allow_last_resort and first is not None and first.code in _RELAX_CODES:
            res = await _last_resort()
            if res is not None:
                return res
        # On relève l'erreur de la marge DEMANDÉE (sémantique historique : le
        # fallback testeur réagit au start_blocked, le front affiche le
        # blocage du réglage utilisateur).
        raise first

    # ── 28/07/2026 (consigne support/armateur) — DÉCOUPLAGE MARÉE/ROUTAGE ──
    # La route est calculée AU PIRE CAS (ZH, marée basse) d'abord : le tracé
    # ne dépend plus de la hauteur d'eau du moment (déterministe, jamais de
    # raccourci sur un estran momentanément couvert). La marée ne sert plus
    # qu'à : (a) rouvrir un trajet IMPOSSIBLE à ZH (chenaux/ports découvrants
    # — route clairement annoncée « dépendante de la marée ») ; (b) prolonger
    # une arrivée TRONQUÉE de > 800 m. Marée NÉGATIVE (sous le ZH) : le pire
    # cas devient la hauteur réelle (plus stricte que ZH).
    async def _run_zh_tide(s_lat: float, s_lng: float) -> tuple[dict, float]:
        nonlocal used_margin
        zh_tide = min(0.0, tide_m)
        if tide_m <= 0.05:
            return await _run(s_lat, s_lng, zh_tide,
                              allow_last_resort=True), zh_tide
        # 27/08/2026 (perf « route < 10 s ») — ZH et MARÉE calculés EN
        # PARALLÈLE. Sémantique du 28/07 INCHANGÉE : le pire cas (ZH) reste
        # préféré ; le résultat marée n'est retenu que si le ZH échoue ou
        # arrive tronqué de > 800 m. Avant, l'échec ZH (exploration
        # exhaustive) et le calcul marée s'ADDITIONNAIENT (~6 s + ~7 s sur
        # Lorient → Golfe). Chaque exécution suit sa marge dans sa propre
        # ``margin_box`` (pas de course sur used_margin).
        zh_box = [used_margin]
        t_box = [used_margin]

        async def _task(tide: float, allow_lr: bool, box: list):
            try:
                return await _run(s_lat, s_lng, tide,
                                  allow_last_resort=allow_lr, margin_box=box)
            except RouteError as e:
                return e

        res_zh, res_t = await asyncio.gather(
            _task(zh_tide, False, zh_box), _task(tide_m, True, t_box))
        if isinstance(res_zh, RouteError):
            if isinstance(res_t, RouteError):
                raise res_t
            used_margin = t_box[0]
            return res_t, tide_m
        off = float((res_zh.get("end_snapped") or {}).get("offset_m") or 0.0)
        if tide_m > 0.2 and off > 800.0 and not isinstance(res_t, RouteError):
            off_t = float((res_t.get("end_snapped") or {}).get("offset_m") or 0.0)
            if off_t < off - 500.0:
                used_margin = t_box[0]
                return res_t, tide_m
        used_margin = zh_box[0]
        return res_zh, zh_tide

    # ── 29/07/2026 (décision armateur — façon Navionics) : EAU PEU PROFONDE.
    async def _run_shallow(s_lat: float, s_lng: float) -> dict | None:
        """Trace la route MALGRÉ l'eau peu profonde quand rien ne passe au
        ZH : seuil de fond relâché au maximum (plancher -2,5 m du moteur :
        jamais les hautes vasières ni la terre), zones de mouillage ouvertes,
        règles de côté levées, marge latérale mini. Roches/épaves/écarts aux
        balises restent bloquants. Les tronçons sous le besoin réel (tirant
        + marge, au ZH) sont renvoyés dans compromised_legs → tracé ROUGE
        « Eau peu profonde » + acceptation du risque côté app."""
        nonlocal used_margin
        tok_m = MOORINGS_OPEN.set(True)
        tok_s = SIDE_RULES_OPEN.set(True)
        try:
            res = await asyncio.to_thread(
                compute_route,
                s_lat, s_lng, body.end.lat, body.end.lng,
                body.draft_m, body.depth_margin_m, 10.0,
                6.0,  # relâche maximale du seuil (le plancher -2,5 m tient)
            )
        except RouteError:
            return None
        finally:
            SIDE_RULES_OPEN.reset(tok_s)
            MOORINGS_OPEN.reset(tok_m)
        used_margin = 10.0
        base_need = body.draft_m + body.depth_margin_m
        # Les avertissements « grâce à la marée » du moteur (tide_m=6 interne)
        # n'ont aucun sens ici : purgés.
        res["warnings"] = [
            w for w in res.get("warnings") or []
            if "grâce à la marée" not in w
        ]
        legs = await asyncio.to_thread(
            shallow_legs, res.get("waypoints") or [], base_need)
        if legs:
            res["compromised_legs"] = sorted(
                set(res.get("compromised_legs") or []) | set(legs))
            res.setdefault("warnings", []).insert(0, (
                "⚠ EAU PEU PROFONDE : aucun passage n'offre la hauteur d'eau "
                "requise à marée basse (ZH). Les tronçons en ROUGE passent "
                "sur des fonds insuffisants pour votre tirant d'eau + marge "
                "— ne les franchissez qu'avec une hauteur de marée "
                "suffisante, à vitesse réduite."
            ))
        else:
            res.setdefault("warnings", []).insert(0, (
                "⚠ Route « aucun autre passage » : balisage et zones de "
                "mouillage assouplis — vérifiez le balisage À VUE sur tout "
                "le parcours."
            ))
        res["risk"] = True
        res["shallow_route"] = True
        res["tide_m"] = 0.0
        res["threshold_m"] = round(base_need, 2)
        return res

    route_tide = min(0.0, tide_m)  # hauteur d'eau réellement UTILISÉE par le routage
    try:
        try:
            result, route_tide = await _run_zh_tide(start_lat, start_lng)
        except RouteError as e:
            # 2e/3e chance testeur : départ à terre (dans la couverture mais
            # non navigable) → l'EAU NAVIGABLE LA PLUS PROCHE (≤ 5 km, 23/07
            # extension de zone) ; si elle est elle-même bloquée (poche
            # isolée) ou introuvable → Arradon.
            if is_tester and e.code == "start_blocked" and start_fallback != ARRADON_FALLBACK["name"]:
                near = None
                if start_fallback is None:
                    # 28/07 (découplage marée) — l'eau la plus proche est
                    # cherchée au PIRE CAS (ZH), comme la route elle-même.
                    min_depth = max(0.05, body.draft_m + body.depth_margin_m - min(0.0, tide_m))
                    near = nearest_navigable(start_lat, start_lng, min_depth, 5000.0)
                if near is not None:
                    start_lat, start_lng = near
                    start_fallback = "l'eau navigable la plus proche"
                    try:
                        result, route_tide = await _run_zh_tide(start_lat, start_lng)
                    except RouteError as e2:
                        if e2.code != "start_blocked":
                            raise
                        start_lat, start_lng = ARRADON_FALLBACK["lat"], ARRADON_FALLBACK["lng"]
                        start_fallback = ARRADON_FALLBACK["name"]
                        result, route_tide = await _run_zh_tide(start_lat, start_lng)
                else:
                    start_lat, start_lng = ARRADON_FALLBACK["lat"], ARRADON_FALLBACK["lng"]
                    start_fallback = ARRADON_FALLBACK["name"]
                    result, route_tide = await _run_zh_tide(start_lat, start_lng)
            else:
                raise
    except RouteError as e:
        # ── 29/07/2026 (décision armateur, 1.a « Oui ») — quand rien ne passe
        # au ZH, on TRACE QUAND MÊME la route en mode « eau peu profonde »
        # (tronçons rouges + acceptation du risque). Le refus sec (422) ne
        # reste que si même ce mode échoue (terre, hors couverture, aucune
        # eau atteignable).
        shallow = None
        if e.code in _RELAX_CODES:
            shallow = await _run_shallow(start_lat, start_lng)
        if shallow is not None:
            result = shallow
            route_tide = 0.0
        else:
            # 22/07/2026 — le payload (blocked_at, partial_waypoints) part dans le
            # détail : le front AFFICHE le point de blocage sans effacer la route.
            # + LOG systématique des échecs (diagnostic à distance des « aucune
            # route » remontés par les testeurs).
            logger.info(
                "route FAILED user=%s code=%s start=(%.5f,%.5f) end=(%.5f,%.5f) "
                "draft=%.1f margin=%.1f lat_m=%.0f(%s) tide=%.2f",
                user.get("user_id"), e.code, start_lat, start_lng,
                body.end.lat, body.end.lng, body.draft_m, body.depth_margin_m,
                req_margin, "auto" if auto_margin else "manuel", tide_m,
            )
            # 23/07/2026 (demande armateur) — INDIQUER le réglage en cause et OÙ
            # le corriger : la marge latérale a déjà été réduite au minimum, donc
            # le refus vient du tirant d'eau + marge de fond (ou de la marée).
            msg = e.message
            if e.code in _RELAX_CODES:
                msg += (
                    f" Réglages en cause : tirant d'eau {body.draft_m:g} m"
                    f" + marge de fond {body.depth_margin_m:g} m"
                    " (la marge latérale a déjà été réduite au minimum) —"
                    " ajustez-les dans Réglages → Mon bateau,"
                    " ou intégrez la marée au départ."
                )
            extra_detail: dict = {}
            # 26/07 (GO armateur) — PROCHAINE MARÉE SUFFISANTE sur refus : calcul
            # HYPOTHÉTIQUE à la pleine mer des prochaines 24 h (dernier recours,
            # marge mini). S'il passe, on annonce l'heure à partir de laquelle la
            # hauteur d'eau requise sera atteinte.
            if tide_info is not None and tide_ref is not None and e.code in _RELAX_CODES:
                cross0 = await tide_crossings(tide_ref[0], tide_ref[1], dep, 99.0)
                if cross0 is not None and cross0["max_m"] > tide_m + 0.2:
                    tok = MOORINGS_OPEN.set(True)
                    tok_s = SIDE_RULES_OPEN.set(True)  # 27/07 : hypothèse « meilleur cas »
                    try:
                        res_h = await asyncio.to_thread(
                            compute_route,
                            start_lat, start_lng, body.end.lat, body.end.lng,
                            body.draft_m, body.depth_margin_m, 10.0,
                            cross0["max_m"],
                        )
                    except RouteError:
                        res_h = None
                    finally:
                        SIDE_RULES_OPEN.reset(tok_s)
                        MOORINGS_OPEN.reset(tok)
                    m_min_h = (res_h or {}).get("min_depth_m")
                    if res_h is not None and m_min_h is not None:
                        need_h = body.draft_m + body.depth_margin_m - float(m_min_h)
                        cross_h = await tide_crossings(tide_ref[0], tide_ref[1], dep, need_h)
                        ts_ok = None
                        if cross_h is not None:
                            ts_ok = dep if cross_h["now_ok"] else cross_h["next_ok_ts"]
                        if ts_ok is not None and not cross_h["now_ok"]:
                            off_h = float((res_h.get("end_snapped") or {}).get("offset_m") or 0.0)
                            approche = (
                                "" if off_h <= 200.0
                                else f" (arrivée à ~{off_h/1000:.1f} km de la destination, au plus près des fonds)"
                            )
                            msg += (
                                f" ✅ AVEC LA MARÉE, ce trajet devrait passer À PARTIR DE "
                                f"~{_fmt_local(ts_ok)} (hauteur ≥ +{max(0.0, need_h):.1f} m — "
                                f"{cross_h['port']}){approche} : recalculez la route à ce moment-là."
                            )
                            extra_detail["tide_retry"] = {
                                "next_ok_ts": ts_ok,
                                "required_m": round(max(0.0, need_h), 2),
                                "port": cross_h["port"],
                            }
            raise HTTPException(422, {"code": e.code, "message": msg, **extra_detail, **(e.payload or {}), **_fallback_route(e, body)})
    if used_margin < req_margin:
        result["lateral_margin_used_m"] = used_margin
        result["warnings"].insert(
            0,
            f"Passages étroits sur ce trajet : marge latérale réduite "
            f"{int(req_margin)} m → {int(used_margin)} m "
            f"(tirant d'eau et marge de fond inchangés — "
            f"réglable dans Réglages → Mon bateau).",
        )
    if start_fallback:
        result["warnings"].insert(
            0,
            f"Mode test : départ non navigable → remplacé par {start_fallback}.",
        )
    if tide_warning:
        result["warnings"].insert(0, tide_warning)
    if tide_info is not None:
        result["tide"] = tide_info
        if route_tide > 0.05:
            # 28/07 — route DÉPENDANTE de la marée (impossible à ZH) :
            # avertissement historique « moment du calcul » + actualisation.
            result["warnings"].append(
                f"Marée : hauteur PRÉVUE ~30 min après le calcul (+{route_tide:.1f} m à "
                f"{_fmt_local(dep)} — {tide_info['port']}). Elle évolue pendant le trajet (mini "
                f"~+{tide_info['height_min_m']:.1f} m sur {tide_info['window_h']:.0f} h) : "
                "vérifiez qu'elle reste suffisante à votre heure de passage, ou "
                "actualisez la route (tap sur le tracé → Actualiser) avant les "
                "passages sensibles."
            )
        else:
            # 28/07 (découplage marée/routage) — route calculée au PIRE CAS
            # (ZH) : les fonds du tracé suffisent SANS marée. L'info marée
            # reste affichée à titre indicatif.
            result["warnings"].append(
                f"Route calculée à MARÉE BASSE (zéro hydrographique) : fonds "
                f"suffisants quelle que soit la marée. Info marée : "
                f"+{tide_m:.1f} m prévus ~30 min après le calcul "
                f"({_fmt_local(dep)} — {tide_info['port']})."
            )
        # ── 26/07 (GO armateur) — PROCHAINE MARÉE SUFFISANTE ────────────────
        req_depth = body.draft_m + body.depth_margin_m
        m_min = result.get("min_depth_m")
        # a) La route livrée ne passe que GRÂCE à la marée → fenêtre de
        #    validité : jusqu'à quand la hauteur reste-t-elle suffisante ?
        if tide_ref is not None and m_min is not None and float(m_min) < req_depth:
            need = req_depth - float(m_min)
            cross = await tide_crossings(tide_ref[0], tide_ref[1], dep, need)
            if cross is not None and cross["now_ok"]:
                result["tide_window"] = {
                    "required_m": round(need, 2),
                    "ok_until_ts": cross["ok_until_ts"],
                    "port": cross["port"],
                }
        # b) Arrivée déplacée de > 800 m : jusqu'où irait la route à la
        #    PLEINE MER des prochaines 24 h ? Si elle va NETTEMENT plus loin,
        #    on annonce l'heure à partir de laquelle actualiser la route.
        off = float((result.get("end_snapped") or {}).get("offset_m") or 0.0)
        if tide_ref is not None and off > 800.0:
            cross0 = await tide_crossings(tide_ref[0], tide_ref[1], dep, 99.0)
            if cross0 is not None and cross0["max_m"] > route_tide + 0.2:
                # Réglages « dernier recours » (balisage latéral levé, marge
                # mini) : on mesure la limite DES FONDS, pas celle du balisage.
                tok = MOORINGS_OPEN.set(True)
                tok_s = SIDE_RULES_OPEN.set(True)
                try:
                    res_h = await asyncio.to_thread(
                        compute_route,
                        start_lat, start_lng, body.end.lat, body.end.lng,
                        body.draft_m, body.depth_margin_m, 10.0,
                        cross0["max_m"],
                    )
                except RouteError:
                    res_h = None
                finally:
                    SIDE_RULES_OPEN.reset(tok_s)
                    MOORINGS_OPEN.reset(tok)
                off_h = float((res_h.get("end_snapped") or {}).get("offset_m") or 0.0) if res_h else None
                m_min_h = (res_h or {}).get("min_depth_m")
                if res_h is not None and off_h is not None and off_h < off - 500.0 and m_min_h is not None:
                    need_h = req_depth - float(m_min_h)
                    cross_h = await tide_crossings(tide_ref[0], tide_ref[1], dep, need_h)
                    ts_ok = None
                    if cross_h is not None and not cross_h["now_ok"]:
                        ts_ok = cross_h["next_ok_ts"]
                    if ts_ok is not None:
                        result["tide_better"] = {
                            "ts": ts_ok,
                            "required_m": round(max(0.0, need_h), 2),
                            "offset_m": round(off_h),
                            "port": cross_h["port"],
                        }
                        result["warnings"].append(
                            f"Avec plus de marée, cette route ira PLUS LOIN "
                            f"(arrivée à ~{off_h/1000:.1f} km de la destination au "
                            f"lieu de ~{off/1000:.1f} km) : à partir de "
                            f"~{_fmt_local(ts_ok)} (hauteur ≥ +{max(0.0, need_h):.1f} m), "
                            "actualisez la route."
                        )
                elif res_h is None or (off_h is not None and off_h >= off - 500.0):
                    result["warnings"].append(
                        f"Même à pleine mer (+{cross0['max_m']:.1f} m), l'arrivée "
                        "resterait déplacée : fond insuffisant sur les cartes "
                        "au-delà de ce point."
                    )
    # ── 25/07 (demande armateur — vidéo « route dangereuse ») : MARGE FAIBLE.
    # Si la hauteur d'eau minimale rencontrée (fond carte + marée) est < 150%
    # du besoin (tirant + marge de fond), on le signale : le front propose
    # une route alternative plus sûre (safety_extra_m = 2 m) ou exige la
    # confirmation du risque avant le suivi.
    if not body.safety_extra_m and not result.get("shallow_route"):
        req = body.draft_m + body.depth_margin_m
        depths = [
            p.get("depth_m")
            for p in result.get("depth_profile", [])
            if p.get("depth_m") is not None
        ]
        if depths and req > 0:
            min_h = min(depths) + tide_m
            if min_h < 1.5 * req:
                result["low_margin"] = {
                    "min_height_m": round(min_h, 2),
                    "required_m": round(req, 2),
                    "alert_at_m": round(1.5 * req, 2),
                    "safe_extra_m": 2.0,
                }
    dt = time.monotonic() - t0
    logger.info(
        "route computed user=%s wp=%d dist=%.0fm fallback=%s in %.2fs",
        user.get("user_id"), len(result["waypoints"]), result["distance_m"],
        start_fallback, dt,
    )
    result["compute_s"] = round(dt, 2)
    # 31/07/2026 — ID PUBLIC + persistance 30 j (support armateur).
    result["route_id"] = _new_route_id()
    # 01/08/2026 — traçabilité multi-moteurs : chaque route sait quel moteur
    # + quelle version d'algo l'a produite (indispensable pour comparer
    # A vs B après une modif de B, et pour l'historique).
    result["engine"] = {
        "id": engine_doc.get("id"),
        "name": engine_doc.get("name"),
        "algo": engine_doc.get("algo"),
        "algo_version": getattr(_algo, "version", None),
    }
    await _persist_route(
        result["route_id"], user, "auto",
        body.model_dump(mode="json"), result,
        engine_doc=engine_doc,
    )
    return result


# ── 02/08/2026 (armateur : « erreur 429 quasi à chaque calcul près des côtes,
# et à chaque fois le départ de la route saute ») — CALCUL EN TÂCHE DE FOND ──
# Un calcul côtier dure 10-20 s (mesuré : 12,3 s Quiberon → Loire). Tenir une
# connexion HTTP aussi longtemps expose l'app aux 429 de l'ingress (limite de
# requêtes SIMULTANÉES par IP, tuiles comprises) : le calcul était perdu, et
# le point de départ avec.
# Désormais : POST …/compute/async rend la main tout de suite (job_id), l'app
# interroge un GET très court. Un 429 sur une interrogation est SANS
# CONSÉQUENCE : le calcul continue côté serveur et l'app le récupère au coup
# suivant. Le point de départ n'est donc plus jamais perdu.
#
# 31/08/2026 (armateur : « Calcul introuvable (expiré) » en production) —
# JOBS EN BASE, PLUS EN MÉMOIRE. L'ancien dictionnaire _JOBS vivait dans le
# process : avec PLUSIEURS instances backend derrière l'ingress, le POST
# créait le job sur une instance et le GET tombait sur une autre → 404
# « Calcul introuvable (expiré) » alors que le calcul tournait. Les jobs
# vivent désormais dans la collection MongoDB ``route_jobs`` (partagée par
# toutes les instances) avec un index TTL de 900 s : même durée de vie
# qu'avant (résultat relisible 15 min — audit QA FND-012), purge par Mongo.
_JOB_TASKS: set = set()
_JOB_TTL_S = 900
_jobs_index_ready = False


async def _jobs_col():
    """Collection ``route_jobs`` avec index TTL garanti (créé une fois par
    process, idempotent côté Mongo)."""
    global _jobs_index_ready
    col = srv.db.route_jobs
    if not _jobs_index_ready:
        try:
            await col.create_index("ts", expireAfterSeconds=_JOB_TTL_S)
            _jobs_index_ready = True
        except Exception:  # noqa: BLE001 — l'index existe déjà ou Mongo répond mal
            logger.exception("route_jobs: création de l'index TTL en échec")
    return col


async def _job_start(uid: str) -> str:
    job_id = uuid.uuid4().hex
    col = await _jobs_col()
    await col.insert_one({
        "_id": job_id, "status": "pending", "uid": uid,
        "ts": datetime.now(timezone.utc),
    })
    return job_id


def _job_run(job_id: str, uid: str, coro):
    """Exécute ``coro`` en tâche de fond et stocke son issue dans le job
    (en base : toutes les instances voient le résultat)."""
    async def _finish(doc: dict) -> None:
        doc["ts"] = datetime.now(timezone.utc)   # le TTL court depuis l'issue
        try:
            col = await _jobs_col()
            await col.update_one({"_id": job_id}, {"$set": doc})
        except Exception:  # noqa: BLE001
            logger.exception("route job %s : écriture du résultat en échec", job_id)

    async def _wrap() -> None:
        try:
            res = await coro
            await _finish({"status": "done", "result": res})
        except HTTPException as exc:
            await _finish({
                "status": "error",
                "status_code": exc.status_code, "detail": exc.detail,
            })
        except Exception as exc:  # noqa: BLE001
            logger.exception("route job %s failed", job_id)
            await _finish({
                "status": "error",
                "status_code": 500, "detail": str(exc) or "Calcul impossible.",
            })
        finally:
            _JOB_TASKS.discard(task)

    task = asyncio.create_task(_wrap())
    # Référence forte : sans cela le ramasse-miettes peut tuer la tâche.
    _JOB_TASKS.add(task)

@router.post("/compute/async")
async def routes_compute_async(body: RouteIn, user: dict = Depends(current_user)):
    # 14/08 (audit QA FND-003) — moteur explicite inconnu/désactivé refusé
    # AVANT la création du job (le 404 du calcul interne n'arrivait qu'au
    # poll, et l'ancien code basculait silencieusement sur le Moteur A).
    if body.engine_id:
        eng = await _get_engine(srv.db, body.engine_id)
        if not eng or not eng.get("active"):
            raise HTTPException(
                status_code=404,
                detail=f"Moteur « {body.engine_id} » introuvable ou désactivé.")
    uid = str(user.get("user_id") or user.get("id") or "")
    job_id = await _job_start(uid)
    _job_run(job_id, uid, routes_compute(body, user))
    return {"job_id": job_id, "status": "pending"}


@router.get("/job/{job_id}")
async def routes_job(job_id: str, user: dict = Depends(current_user)):
    uid = str(user.get("user_id") or user.get("id") or "")
    col = await _jobs_col()
    job = await col.find_one({"_id": job_id})
    if job is None or job.get("uid") != uid:
        raise HTTPException(status_code=404, detail="Calcul introuvable (expiré).")
    if job["status"] == "pending":
        return {"status": "pending"}
    if job["status"] == "done":
        # 14/08 (audit QA FND-012) — le résultat reste RELISIBLE pendant tout
        # le TTL (15 min) : un re-rendu client, un retry réseau ou un second
        # onglet ne détruisent plus la route (le GC périodique libère la
        # mémoire, plus le premier GET).
        return {"status": "done", "result": job["result"]}
    return {
        "status": "error",
        "status_code": job.get("status_code", 422),
        "detail": job.get("detail"),
    }



# ── 22/07/2026 — ROUTE MANUELLE : waypoints choisis par l'utilisateur ──────
class ManualRouteIn(BaseModel):
    waypoints: list[Point] = Field(..., min_length=2, max_length=300)
    draft_m: float = Field(1.5, ge=0.2, le=4)
    depth_margin_m: float = Field(0.5, ge=0, le=3)
    # 27/07 (vidéo armateur 15h45) — marée intégrée aussi aux routes
    # manuelles/modifiées : les tronçons rouges reflètent la hauteur d'eau
    # RÉELLE (prévue à H+30 min), plus seulement le fond carte au ZH.
    use_tide: bool = False
    departure_ts: Optional[float] = None
    # 01/08/2026 — moteur choisi (idem RouteIn).
    engine_id: Optional[str] = Field(None, min_length=1, max_length=48)


@router.post("/manual")
async def routes_manual(body: ManualRouteIn, user: dict = Depends(current_user)):
    # 01/08/2026 — Résolution du moteur (idem /compute : explicite → strict).
    requested_engine_id = body.engine_id or user.get("active_engine_id")
    if body.engine_id:
        engine_doc = await _get_engine(srv.db, body.engine_id)
        if not engine_doc or not engine_doc.get("active"):
            raise HTTPException(
                status_code=404,
                detail=f"Moteur « {body.engine_id} » introuvable ou désactivé.")
    else:
        engine_doc = await _get_engine_or_default(srv.db, requested_engine_id)
    _algo = _resolve_algo(engine_doc)
    # L'algo v1 attend lateral_margin_m ; côté manuel il est ignoré mais on
    # respecte la signature de l'interface (uniforme avec compute_auto).
    def _manual_call(wps, draft, margin, tide):
        return _algo.compute_manual(
            wps, draft, margin, 0.0, tide_m=tide,
            params=(engine_doc.get("params") or {}),
        )
    tide_m = 0.0
    tide_info: Optional[dict] = None
    tide_warning: Optional[str] = None
    if TIDE_ROUTING_ENABLED and body.use_tide and body.waypoints:
        dep = float(int(((body.departure_ts or time.time()) + TIDE_LEAD_S) // 600) * 600)
        ref = body.waypoints[0]
        tw = await tide_window(ref.lat, ref.lng, dep, 3.0)
        if tw is None:
            tide_warning = "Marée indisponible — tracé contrôlé à MARÉE BASSE (sécuritaire)."
        else:
            tide_m = max(-2.0, tw["height_start_m"])
            tide_info = {**tw, "departure_ts": dep}
    result = await asyncio.to_thread(
        _manual_call,
        [(p.lat, p.lng) for p in body.waypoints],
        body.draft_m, body.depth_margin_m,
        tide_m,
    )
    if tide_info is not None:
        result["tide"] = tide_info
        result["warnings"].append(
            f"Marée : hauteur PRÉVUE ~30 min après le calcul (+{tide_m:.1f} m à "
            f"{_fmt_local(tide_info['departure_ts'])} — {tide_info['port']}). "
            "Re-vérifiez la hauteur d'eau à votre heure de passage."
        )
    elif tide_warning:
        result["warnings"].append(tide_warning)
    # 26/07 (demande armateur) — RÈGLE DES 150 % aussi sur les routes
    # manuelles/modifiées : même mécanique d'alerte que la route auto.
    # 27/07 — min_height intègre désormais la marée (fond carte + marée).
    min_d = result.get("min_depth_m")
    if min_d is not None:
        req = body.draft_m + body.depth_margin_m
        min_h = float(min_d) + tide_m
        if req > 0 and min_h < 1.5 * req:
            result["low_margin"] = {
                "min_height_m": round(min_h, 2),
                "required_m": round(req, 2),
                "alert_at_m": round(1.5 * req, 2),
                "safe_extra_m": 2.0,
            }
    # 31/07/2026 — ID PUBLIC + persistance 30 j (support armateur).
    result["route_id"] = _new_route_id()
    # 01/08/2026 — traçabilité multi-moteurs (cf. compute).
    result["engine"] = {
        "id": engine_doc.get("id"),
        "name": engine_doc.get("name"),
        "algo": engine_doc.get("algo"),
        "algo_version": getattr(_algo, "version", None),
    }
    await _persist_route(
        result["route_id"], user, "manual",
        body.model_dump(mode="json"), result,
        engine_doc=engine_doc,
    )
    return result


# ── 22/07/2026 — ROUTES ENREGISTRÉES (max 20 / utilisateur, id unique
# pérenne → partage futur). Collection ``saved_routes``. ──────────────────
MAX_SAVED_ROUTES = 20


class SavedRouteIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    mode: str = Field("manual", pattern="^(auto|manual)$")
    waypoints: list[Point] = Field(..., min_length=2, max_length=300)
    distance_m: float = Field(0, ge=0)
    # 01/08/2026 — Traçabilité multi-moteurs : chaque route enregistrée
    # sait quel moteur l'a générée + les paramètres d'entrée (start/end/
    # draft/marges) pour permettre de la recalculer avec un autre moteur.
    engine_id: Optional[str] = Field(None, min_length=1, max_length=48)
    engine_name: Optional[str] = Field(None, max_length=80)
    algo_id: Optional[str] = Field(None, max_length=48)
    draft_m: Optional[float] = Field(None, ge=0.2, le=4)
    depth_margin_m: Optional[float] = Field(None, ge=0, le=3)
    lateral_margin_m: Optional[float] = Field(None, ge=10, le=500)
    source_route_id: Optional[str] = Field(None, max_length=64)
    # 02/08/2026 — DÉPART/ARRIVÉE DEMANDÉS (avant accrochage à la grille et
    # avant relogement éventuel de l'arrivée). Indispensables pour recalculer
    # la route à l'identique avec un autre moteur (test A/B) : les waypoints
    # sont des nœuds de grille, repartir d'eux ne reproduit pas le calcul.
    start: Optional[Point] = None
    end: Optional[Point] = None


# 02/08/2026 — le contrôle d'une route manuelle (ou l'ouverture d'une route
# enregistrée) dure aussi plusieurs secondes : même traitement en tâche de
# fond que /compute (cf. commentaire du bloc _JOBS).
@router.post("/manual/async")
async def routes_manual_async(body: ManualRouteIn, user: dict = Depends(current_user)):
    uid = str(user.get("user_id") or user.get("id") or "")
    job_id = await _job_start(uid)
    _job_run(job_id, uid, routes_manual(body, user))
    return {"job_id": job_id, "status": "pending"}



@router.post("/saved")
async def save_route(body: SavedRouteIn, user: dict = Depends(current_user)):
    uid = user.get("user_id")
    count = await srv.db.saved_routes.count_documents({"user_id": uid})
    if count >= MAX_SAVED_ROUTES:
        raise HTTPException(
            409,
            f"Limite de {MAX_SAVED_ROUTES} routes enregistrées atteinte — supprimez-en une d'abord.",
        )
    doc = {
        "id": uuid.uuid4().hex,
        "user_id": uid,
        "name": body.name.strip(),
        "mode": body.mode,
        "waypoints": [{"lat": p.lat, "lng": p.lng} for p in body.waypoints],
        "distance_m": round(body.distance_m, 1),
        # 01/08/2026 — traçabilité + recalcul futur.
        "engine_id": body.engine_id,
        "engine_name": body.engine_name,
        "algo_id": body.algo_id,
        "draft_m": body.draft_m,
        "depth_margin_m": body.depth_margin_m,
        "lateral_margin_m": body.lateral_margin_m,
        "source_route_id": body.source_route_id,
        # 02/08/2026 — points DEMANDÉS (recalcul A/B fidèle).
        "start": {"lat": body.start.lat, "lng": body.start.lng} if body.start else None,
        "end": {"lat": body.end.lat, "lng": body.end.lng} if body.end else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await srv.db.saved_routes.insert_one({**doc})
    logger.info("route saved user=%s id=%s name=%r wp=%d engine=%s",
                uid, doc["id"], doc["name"], len(doc["waypoints"]), body.engine_id)
    return doc


@router.get("/saved")
async def list_saved_routes(user: dict = Depends(current_user)):
    docs = await srv.db.saved_routes.find(
        {"user_id": user.get("user_id")}, {"_id": 0},
    ).sort("created_at", -1).to_list(MAX_SAVED_ROUTES)
    return {"routes": docs, "max": MAX_SAVED_ROUTES}


@router.delete("/saved/{route_id}")
async def delete_saved_route(route_id: str, user: dict = Depends(current_user)):
    res = await srv.db.saved_routes.delete_one(
        {"id": route_id, "user_id": user.get("user_id")},
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "Route introuvable.")
    return {"ok": True}


# ── 01/08/2026 — RECALCUL d'une route enregistrée avec un ou plusieurs
# moteurs. Permet à l'armateur de comparer côte à côte le tracé produit par
# les moteurs A, B, ou tout autre variant (routes de mer réelles → banc de
# test). Ne modifie JAMAIS la route enregistrée : renvoie N résultats,
# l'armateur décide ensuite s'il en sauvegarde un nouveau.
class RecomputeIn(BaseModel):
    engine_ids: list[str] = Field(..., min_length=1, max_length=6)


@router.post("/saved/{route_id}/recompute")
async def recompute_saved_route(
    route_id: str, body: RecomputeIn, user: dict = Depends(current_user),
):
    saved = await srv.db.saved_routes.find_one(
        {"id": route_id, "user_id": user.get("user_id")}, {"_id": 0},
    )
    if saved is None:
        raise HTTPException(404, "Route enregistrée introuvable.")

    wps = saved.get("waypoints") or []
    if len(wps) < 2:
        raise HTTPException(422, "Route enregistrée incomplète (2 waypoints minimum).")

    # Valeurs de repli : si la route a été enregistrée avant la traçabilité
    # multi-moteur, on utilise les défauts (comme pour un calcul UI standard).
    draft = float(saved.get("draft_m") or 1.5)
    margin = float(saved.get("depth_margin_m") or 0.5)
    # 02/08/2026 — marge latérale : ABSENTE dans la route enregistrée = mode
    # AUTO (le moteur adapte au chenal, plancher AUTO_LATERAL_M). L'ancien
    # repli à 150 m faisait échouer le recalcul des routes prises au ponton
    # (« Départ dans une zone non navigable ») alors qu'elles avaient été
    # calculées en marge AUTO.
    lateral_raw = saved.get("lateral_margin_m")
    lateral = float(lateral_raw) if lateral_raw is not None else AUTO_LATERAL_M
    mode = saved.get("mode") or "manual"

    results: dict[str, dict] = {}
    # 02/08/2026 — recalcul AUTO : on repart des points DEMANDÉS à l'origine
    # (enregistrés depuis le 02/08). À défaut (routes plus anciennes) on
    # utilise les extrémités du tracé, qui sont des nœuds de grille.
    saved_start = saved.get("start") or wps[0]
    saved_end = saved.get("end") or wps[-1]
    for engine_id in body.engine_ids:
        engine_id = (engine_id or "").strip()
        if not engine_id:
            continue
        engine_doc = await _get_engine_or_default(srv.db, engine_id)
        algo = _resolve_algo(engine_doc)
        e_params = engine_doc.get("params") or {}
        try:
            if mode == "auto":
                res = await asyncio.to_thread(
                    _functools.partial(algo.compute_auto, params=e_params),
                    float(saved_start["lat"]), float(saved_start["lng"]),
                    float(saved_end["lat"]), float(saved_end["lng"]),
                    draft, margin, lateral,
                    0.0,  # tide_m — désactivé (calcul ZH strict)
                )
            else:
                res = await asyncio.to_thread(
                    _functools.partial(algo.compute_manual, params=e_params),
                    [(float(p["lat"]), float(p["lng"])) for p in wps],
                    draft, margin, lateral,
                    0.0,
                )
        except RouteError as exc:
            results[engine_id] = {
                "engine": {
                    "id": engine_doc.get("id"),
                    "name": engine_doc.get("name"),
                    "algo": engine_doc.get("algo"),
                    "algo_version": getattr(algo, "version", None),
                },
                "error": str(exc),
            }
            continue

        # ID public + persistance (permet inspection support).
        res["route_id"] = _new_route_id()
        res["engine"] = {
            "id": engine_doc.get("id"),
            "name": engine_doc.get("name"),
            "algo": engine_doc.get("algo"),
            "algo_version": getattr(algo, "version", None),
        }
        await _persist_route(
            res["route_id"], user, f"recompute_{mode}",
            {"saved_route_id": route_id, "engine_id": engine_id,
             "draft_m": draft, "depth_margin_m": margin,
             "lateral_margin_m": lateral, "mode": mode},
            res, engine_doc=engine_doc,
        )
        results[engine_id] = res

    return {
        "saved_route_id": route_id,
        "source_engine_id": saved.get("engine_id"),
        "results": results,
    }


# 02/08/2026 — même recalcul, mais en TÂCHE DE FOND (jusqu'à 6 moteurs × 15 s
# sur une seule connexion HTTP = 429 quasi garanti). L'app suit l'avancement
# via GET /routes/job/{job_id}.
@router.post("/saved/{route_id}/recompute/async")
async def recompute_saved_route_async(
    route_id: str, body: RecomputeIn, user: dict = Depends(current_user),
):
    # 14/08 (audit QA FND-014) — l'existence de la route est vérifiée AVANT
    # de créer le job (plus de 200 + job_id pour un id inexistant).
    exists = await srv.db.saved_routes.find_one(
        {"id": route_id, "user_id": user.get("user_id")}, {"_id": 1})
    if exists is None:
        raise HTTPException(404, "Route enregistrée introuvable.")
    uid = str(user.get("user_id") or user.get("id") or "")
    job_id = await _job_start(uid)
    _job_run(job_id, uid, recompute_saved_route(route_id, body, user))
    return {"job_id": job_id, "status": "pending"}



# ── 31/07/2026 — INSPECTION support d'une route calculée (admin only) ─────
# L'armateur me communique un route_id ; je consulte les paramètres exacts,
# le tracé et les warnings via cet endpoint pour diagnostiquer un cas
# incohérent remonté depuis le terrain. Verrouillé sur le compte SignalMar
# admin (core.support_admin.is_signalmar_admin).
@router.get("/inspect/{route_id}")
async def inspect_route(route_id: str, user: dict = Depends(current_user)):
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Accès réservé au compte SignalMar admin.")
    rid = (route_id or "").strip()
    if not rid.startswith("R-"):
        raise HTTPException(422, "Format d'ID invalide (attendu R-YYYYMMDD-HHMMSS-XX).")
    doc = await srv.db.computed_routes.find_one({"route_id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Route introuvable (expirée > 30 j ou ID incorrect).")
    return doc


# ── 14/08/2026 — SIGNALEMENT « BALISAGE NON RESPECTÉ » (demande armateur) ──
# Bouton sur la RouteCard : envoie automatiquement l'ID de route + la balise
# concernée (saisie libre) + un instantané des avertissements/balises du
# mauvais côté déjà détectés. Collection ``mark_reports`` — consultée par le
# support (moi) pour corriger les moteurs sans allers-retours de captures.
class MarkReportIn(BaseModel):
    route_id: str = Field(min_length=4, max_length=40)
    mark_name: Optional[str] = Field(default=None, max_length=120)
    comment: Optional[str] = Field(default=None, max_length=500)


@router.post("/mark-report")
async def create_mark_report(body: MarkReportIn, user: dict = Depends(current_user)):
    rid = body.route_id.strip()
    doc = await srv.db.computed_routes.find_one(
        {"route_id": rid},
        {"_id": 0, "route_id": 1, "engine_id": 1, "engine_name": 1,
         "algo_id": 1, "request": 1,
         "result.wrong_side_marks": 1, "result.warnings": 1,
         "result.distance_m": 1, "result.min_depth_m": 1},
    )
    res = (doc or {}).get("result") or {}
    report_id = "BR-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") \
        + "-" + secrets.choice(_ID_SUFFIX_ALPHABET) \
        + secrets.choice(_ID_SUFFIX_ALPHABET)
    await srv.db.mark_reports.insert_one({
        "report_id": report_id,
        "user_id": user.get("user_id"),
        "user_phone": user.get("phone"),
        "route_id": rid,
        "route_found": doc is not None,
        "engine_id": (doc or {}).get("engine_id"),
        "engine_name": (doc or {}).get("engine_name"),
        "algo_id": (doc or {}).get("algo_id"),
        "mark_name": (body.mark_name or "").strip() or None,
        "comment": (body.comment or "").strip() or None,
        "auto_wrong_side_marks": res.get("wrong_side_marks") or [],
        "auto_warnings": [
            w for w in (res.get("warnings") or [])
            if "CÔTÉ" in w or "balise" in w or "balisage" in w
        ][:6],
        "request": (doc or {}).get("request"),
        "distance_m": res.get("distance_m"),
        "min_depth_m": res.get("min_depth_m"),
        "created_at": datetime.now(timezone.utc),
    })
    return {"ok": True, "report_id": report_id, "route_found": doc is not None}


@router.get("/mark-reports")
async def list_mark_reports(user: dict = Depends(current_user)):
    """Liste des signalements — les siens, ou TOUS pour le compte admin."""
    q = {} if is_signalmar_admin(user) else {"user_id": user.get("user_id")}
    docs = await srv.db.mark_reports.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(100)
    return {"reports": docs}
