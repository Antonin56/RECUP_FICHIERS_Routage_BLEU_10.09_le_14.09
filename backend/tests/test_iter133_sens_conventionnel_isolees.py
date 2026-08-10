"""SignalMar — Itér. 133 (10/08/2026) : SENS CONVENTIONNEL des latérales
ISOLÉES — MOTEUR D uniquement (consigne armateur, priorité absolue).

« Les moteurs de routage n'ont jamais réussi à passer du bon côté des bouées
latérales lorsqu'il n'y a qu'une seule bouée (une rouge ou une verte). Le
Moteur B est PROTÉGÉ et FIGÉ, il sert de base de travail : ne toucher qu'au
Moteur D. »

Correctif (algo signalmar.v4, lié au moteur ``engine_d``) : le côté de
passage d'une latérale est INVARIANT au sens de parcours (« verte à tribord
en entrant » = « verte à bâbord en sortant » = le même côté absolu). Pour
une latérale SANS couple, ce côté est déterminé par l'ASYMÉTRIE
BATHYMÉTRIQUE (l'eau profonde = le chenal, le côté peu profond = le danger
signalé), hiérarchie complète :

    1. couple rouge/verte (vecteur rouge→verte, infaillible) ;
    2. override manuel (data/bathy/side_overrides.json, validé terrain) ;
    3. asymétrie bathymétrique nette (SeamarkIndex.navigable_side) ;
    4. repli : gradient « distance au large » — comportement B historique.

Le mode est porté par le contextvar ``ISOLATED_SIDE_BATHY``, armé UNIQUEMENT
pendant un calcul v4 (caches séparés) : les Moteurs A, B et C sont
STRICTEMENT inchangés — verrouillé ci-dessous.

Cas de référence : latérale VERTE « Illur » (Golfe du Morbihan), ISOLÉE —
haut-fond (1-2 m) au SUD de la bouée, chenal (11-13 m) au NORD. La route
doit passer au NORD dans LES DEUX sens de parcours.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from core.seamarks import ISOLATED_SIDE_BATHY, get_seamarks  # noqa: E402

ILLUR = (47.5827118, -2.7951316)   # verte isolée, danger au sud
MLNG = 111_320.0 * math.cos(math.radians(ILLUR[0]))


@pytest.fixture(scope="module")
def sm():
    idx = get_seamarks()
    assert idx is not None, "index seamarks indisponible"
    return idx


def _mark_at(sm, lat, lng):
    return min(
        (m for m in sm.marks if m.get("kind") == "lateral"),
        key=lambda m: (m["lat"] - lat) ** 2 + (m["lng"] - lng) ** 2,
    )


# ── 1. Signal bathymétrique : côté navigable des isolées ─────────────────
def test_illur_est_isolee_et_son_cote_navigable_est_le_nord(sm):
    m = _mark_at(sm, *ILLUR)
    assert m.get("name") == "Illur" and m["category"] == "starboard"
    assert sm._pair_of(m) is None, "Illur doit être ISOLÉE (pas de couple)"
    w = sm.navigable_side(m)
    assert w is not None, "l'asymétrie bathy d'Illur est nette : signal attendu"
    # Danger (1-2 m) au sud → passage au NORD (composante nord dominante).
    assert w[1] > 0.7, f"côté navigable attendu au NORD, obtenu {w}"


def test_direction_conventionnelle_confiante_chiralite_verte(sm):
    """Verte : la route passe à BÂBORD de D → D = w tourné de −90°.
    Le côté de passage reconstruit depuis D doit redonner w."""
    m = _mark_at(sm, *ILLUR)
    w = sm.navigable_side(m)
    d = sm.mark_dir_confident(m)
    assert d is not None
    de, dn = d
    # bâbord(D) = (−Dn, De) — pour une verte (starboard).
    assert math.hypot(-dn - w[0], de - w[1]) < 1e-9


def test_isolee_ambigue_reste_sans_signal(sm):
    """« NE Teignouse » : eau profonde des deux côtés (passage validé
    Teignouse) → PAS de signal bathy (le repli historique s'applique, et
    l'écart standard de 60 m suffit). Aucune fausse assurance."""
    m = next(m for m in sm.marks
             if m.get("name") == "NE Teignouse" and m.get("kind") == "lateral")
    assert sm._pair_of(m) is None
    assert sm.navigable_side(m) is None


def test_couple_prioritaire_sur_la_bathy(sm):
    """Une latérale APPAIRÉE garde sa direction de couple (signal 1) : la
    direction confiante existe et vient de _pair_dir, pas de la bathy."""
    paired = next(m for m in sm.marks
                  if m.get("kind") == "lateral"
                  and m.get("category") in ("port", "starboard")
                  and 47.5 < m["lat"] < 47.7 and -3.0 < m["lng"] < -2.7
                  and sm._pair_of(m) is not None)
    assert sm._pair_dir(paired) is not None
    assert sm.mark_dir_confident(paired) == sm._pair_dir(paired)


def test_navigable_side_refuse_les_non_laterales(sm):
    card = next(m for m in sm.marks if m.get("kind") == "cardinal")
    assert sm.navigable_side(card) is None


# ── 2. ISOLATION : les moteurs gelés (A/B/C) ne voient RIEN du mode D ────
def test_hors_mode_d_mark_dir_reste_le_gradient_historique(sm):
    """Moteurs A/B/C (mode par défaut) : la direction d'Illur (isolée) vient
    du GRADIENT « distance au large », PAS de la bathymétrie — et le cache
    du mode D est distinct. C'est le verrou « Moteur B protégé et figé »."""
    m = _mark_at(sm, *ILLUR)
    assert ISOLATED_SIDE_BATHY.get() is False
    d_frozen = sm._mark_dir(m)
    grad = sm.conventional_dir(m["lat"], m["lng"])
    assert d_frozen == grad, "hors mode D, la chaîne historique doit s'appliquer"
    tok = ISOLATED_SIDE_BATHY.set(True)
    try:
        d_v4 = sm._mark_dir(m)
    finally:
        ISOLATED_SIDE_BATHY.reset(tok)
    assert d_v4 == sm.mark_dir_confident(m) != d_frozen
    # Et le cache du mode D n'a pas pollué la valeur des moteurs gelés.
    assert sm._mark_dir(m) == d_frozen


def test_algo_v4_enregistre_et_moteurs_geles_intacts():
    from core.routing_engines.algos import ALGO_REGISTRY
    assert "signalmar.v4" in ALGO_REGISTRY
    # Les clés historiques restent liées à leurs classes d'origine.
    assert type(ALGO_REGISTRY["signalmar.v2"]).__name__ == "SignalmarV2"
    assert type(ALGO_REGISTRY["signalmar.v4"]).__name__ == "SignalmarV4"


# ── 2 bis. « Aucun autre passage » / eau peu profonde : les côtés FIABLES
# ne sont JAMAIS levés sous le mode D (bug armateur du 10/08 : No1 laissée
# du mauvais côté à 9,8 m dans la Vilaine — SIDE_RULES_OPEN levait TOUT) ──
def test_mode_d_ne_leve_jamais_un_cote_fiable(sm):
    import numpy as np
    from core.bathy import get_grid
    from core.seamarks import SIDE_RULES_OPEN

    grid = get_grid()
    step_lat = 20.0 / 110_574.0
    step_lng = 20.0 / MLNG
    lats = np.array([ILLUR[0] + k * step_lat for k in range(15, -16, -1)])
    lngs = np.array([ILLUR[1] + k * step_lng for k in range(-15, 16)])
    la2, lo2 = np.meshgrid(lats, lngs, indexing="ij")
    depth = grid.sample(la2, lo2)

    def blocked_south() -> bool:
        blk = sm.rasterize_blocked(lats, lngs, MLNG, 110_574.0, min_depth=2.0,
                                   strict_depth=4.0, depth=depth)
        # Cellule ~100 m au SUD d'Illur : mauvais côté, dans ~4 m d'eau (la
        # « langue » profonde entre la bouée et le haut-fond signalé).
        r = int(np.argmin(np.abs(lats - (ILLUR[0] - 100.0 / 110_574.0))))
        c = int(np.argmin(np.abs(lngs - ILLUR[1])))
        return bool(blk[r, c])

    tok = SIDE_RULES_OPEN.set(True)
    try:
        lifted = blocked_south()      # moteurs gelés : côté levé (historique)
        tok2 = ISOLATED_SIDE_BATHY.set(True)
        try:
            kept = blocked_south()    # Moteur D : côté fiable MAINTENU
        finally:
            ISOLATED_SIDE_BATHY.reset(tok2)
    finally:
        SIDE_RULES_OPEN.reset(tok)
    assert lifted is False, "moteurs gelés : SIDE_RULES_OPEN doit lever le côté"
    assert kept is True, "Moteur D : le côté fiable ne doit JAMAIS être levé"


# ── 3. Moteur D : la route passe du bon côté, dans LES DEUX sens ─────────
@pytest.fixture(scope="module")
def routes_illur():
    from core.routing_engines.algos.signalmar_v4 import SignalmarV4
    eng = SignalmarV4()
    # Port-Navalo → Ilur E (traverse le chenal d'Illur) et retour.
    aller = eng.compute_auto(47.5455, -2.9185, 47.5870, -2.7820, 1.5, 0.5, 50.0)
    retour = eng.compute_auto(47.5870, -2.7820, 47.5455, -2.9185, 1.5, 0.5, 50.0)
    return aller, retour


def _closest(pts, lat, lng):
    from core.routing_engines.algos.signalmar_v2.standoff import _closest_on
    return _closest_on(pts, lat, lng, MLNG)


def test_moteur_d_passe_au_nord_d_illur_dans_les_deux_sens(routes_illur):
    for res in routes_illur:
        pts = [(w["lat"], w["lng"]) for w in res["waypoints"]]
        d, _, p = _closest(pts, *ILLUR)
        if d > 600.0:
            pytest.skip("le tracé n'emprunte plus le chenal d'Illur")
        assert p[0] > ILLUR[0], "la route doit passer au NORD d'Illur"
        names = [v.get("name") for v in (res.get("wrong_side_marks") or [])]
        assert "Illur" not in names
