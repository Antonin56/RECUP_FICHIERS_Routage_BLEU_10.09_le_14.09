// SignalMar — Réglages du bateau (N0, 20/07/2026 — préparation V2 routage).
// Tirant d'eau + marge de sécurité LATÉRALE (distance mini aux zones
// interdites, ≥ 50 m imposé). Persistés localement ; le moteur de route V2
// (POST /api/routes/compute) recevra ces valeurs dans la requête.
import { useCallback, useEffect, useState } from "react";

import { storage } from "@/src/utils/storage";

export const BOAT_DRAFT_DEFAULT_M = 1.5;
export const BOAT_DRAFT_MIN_M = 0.2;
export const BOAT_DRAFT_MAX_M = 4;
/** Marge de sécurité de PROFONDEUR (sous la quille, UKC) — demande armateur 20/07. */
export const BOAT_DEPTH_MARGIN_DEFAULT_M = 0.5;
export const BOAT_DEPTH_MARGIN_MIN_M = 0;
export const BOAT_DEPTH_MARGIN_MAX_M = 3;
/** Tirant d'AIR (hauteur max du bateau — passage sous les ponts). */
export const BOAT_AIR_DRAFT_DEFAULT_M = 3;
export const BOAT_AIR_DRAFT_MIN_M = 0.5;
export const BOAT_AIR_DRAFT_MAX_M = 35;
/** Marge de sécurité de HAUTEUR (sous les ponts/câbles). */
export const BOAT_HEIGHT_MARGIN_DEFAULT_M = 1;
export const BOAT_HEIGHT_MARGIN_MIN_M = 0;
export const BOAT_HEIGHT_MARGIN_MAX_M = 3;
export const BOAT_MARGIN_DEFAULT_M = 10;
/** Marge latérale minimale IMPOSÉE (22/07/2026 : 50 → 10 m, demande armateur
 *  — 50 m fermait des chenaux étroits pourtant sûrs). */
export const BOAT_MARGIN_MIN_M = 10;
export const BOAT_MARGIN_MAX_M = 500;

/** 23/07/2026 (demande armateur) — mode de marge latérale :
 *  "auto" (défaut) = le moteur adapte la marge à la largeur du chenal
 *  (plancher de sécurité 10 m, route attirée vers le milieu du chenal) ;
 *  "manual" = la valeur marginM est envoyée telle quelle au moteur. */
export type MarginMode = "auto" | "manual";
export const BOAT_MARGIN_MODE_DEFAULT: MarginMode = "auto";

// 22/07/2026 (GO armateur) — croisière : vitesse (nd) + consommation (L/h)
// pour estimer durée et carburant d'une route (0 L/h = non renseigné).
export const BOAT_CRUISE_DEFAULT_KN = 6;
export const BOAT_CRUISE_MIN_KN = 2;
export const BOAT_CRUISE_MAX_KN = 40;
export const BOAT_CONS_DEFAULT_LH = 0;
export const BOAT_CONS_MIN_LH = 0;
export const BOAT_CONS_MAX_LH = 100;

const KEY_DRAFT = "sm.boat.draft_m";
const KEY_DEPTH_MARGIN = "sm.boat.depth_margin_m";
const KEY_AIR_DRAFT = "sm.boat.air_draft_m";
const KEY_HEIGHT_MARGIN = "sm.boat.height_margin_m";
const KEY_MARGIN = "sm.boat.margin_m";
const KEY_MARGIN_MODE = "sm.boat.margin_mode";
const KEY_CRUISE = "sm.boat.cruise_kn";
const KEY_CONS = "sm.boat.cons_lh";

function clamp01(v: number, lo: number, hi: number, dflt: number, decimals: 0 | 1): number {
  if (!Number.isFinite(v)) return dflt;
  const f = decimals === 1 ? 10 : 1;
  return Math.min(hi, Math.max(lo, Math.round(v * f) / f));
}

export function clampDraft(v: number): number {
  return clamp01(v, BOAT_DRAFT_MIN_M, BOAT_DRAFT_MAX_M, BOAT_DRAFT_DEFAULT_M, 1);
}

export function clampDepthMargin(v: number): number {
  return clamp01(v, BOAT_DEPTH_MARGIN_MIN_M, BOAT_DEPTH_MARGIN_MAX_M, BOAT_DEPTH_MARGIN_DEFAULT_M, 1);
}

export function clampAirDraft(v: number): number {
  return clamp01(v, BOAT_AIR_DRAFT_MIN_M, BOAT_AIR_DRAFT_MAX_M, BOAT_AIR_DRAFT_DEFAULT_M, 1);
}

export function clampHeightMargin(v: number): number {
  return clamp01(v, BOAT_HEIGHT_MARGIN_MIN_M, BOAT_HEIGHT_MARGIN_MAX_M, BOAT_HEIGHT_MARGIN_DEFAULT_M, 1);
}

export function clampMargin(v: number): number {
  return clamp01(v, BOAT_MARGIN_MIN_M, BOAT_MARGIN_MAX_M, BOAT_MARGIN_DEFAULT_M, 0);
}

export function clampCruise(v: number): number {
  return clamp01(v, BOAT_CRUISE_MIN_KN, BOAT_CRUISE_MAX_KN, BOAT_CRUISE_DEFAULT_KN, 1);
}

export function clampCons(v: number): number {
  return clamp01(v, BOAT_CONS_MIN_LH, BOAT_CONS_MAX_LH, BOAT_CONS_DEFAULT_LH, 1);
}

export type BoatSettings = {
  draftM: number;
  depthMarginM: number;
  airDraftM: number;
  heightMarginM: number;
  marginM: number;
  /** Mode marge latérale : "auto" (adaptée au chenal) ou "manual". */
  marginMode: MarginMode;
  /** Vitesse de croisière (nd). */
  cruiseKn: number;
  /** Consommation en croisière (L/h) — 0 = non renseignée. */
  consLh: number;
};

function sanitizeMarginMode(v: unknown): MarginMode {
  return v === "manual" ? "manual" : BOAT_MARGIN_MODE_DEFAULT;
}

/** Lecture directe (hors React) — utilisée par le moteur de route V2. */
export async function getBoatSettings(): Promise<BoatSettings> {
  const [draft, depthMargin, airDraft, heightMargin, margin, marginMode, cruise, cons] = await Promise.all([
    storage.getItem<number>(KEY_DRAFT, BOAT_DRAFT_DEFAULT_M),
    storage.getItem<number>(KEY_DEPTH_MARGIN, BOAT_DEPTH_MARGIN_DEFAULT_M),
    storage.getItem<number>(KEY_AIR_DRAFT, BOAT_AIR_DRAFT_DEFAULT_M),
    storage.getItem<number>(KEY_HEIGHT_MARGIN, BOAT_HEIGHT_MARGIN_DEFAULT_M),
    storage.getItem<number>(KEY_MARGIN, BOAT_MARGIN_DEFAULT_M),
    storage.getItem<string>(KEY_MARGIN_MODE, BOAT_MARGIN_MODE_DEFAULT),
    storage.getItem<number>(KEY_CRUISE, BOAT_CRUISE_DEFAULT_KN),
    storage.getItem<number>(KEY_CONS, BOAT_CONS_DEFAULT_LH),
  ]);
  return {
    draftM: clampDraft(typeof draft === "number" ? draft : BOAT_DRAFT_DEFAULT_M),
    depthMarginM: clampDepthMargin(typeof depthMargin === "number" ? depthMargin : BOAT_DEPTH_MARGIN_DEFAULT_M),
    airDraftM: clampAirDraft(typeof airDraft === "number" ? airDraft : BOAT_AIR_DRAFT_DEFAULT_M),
    heightMarginM: clampHeightMargin(typeof heightMargin === "number" ? heightMargin : BOAT_HEIGHT_MARGIN_DEFAULT_M),
    marginM: clampMargin(typeof margin === "number" ? margin : BOAT_MARGIN_DEFAULT_M),
    marginMode: sanitizeMarginMode(marginMode),
    cruiseKn: clampCruise(typeof cruise === "number" ? cruise : BOAT_CRUISE_DEFAULT_KN),
    consLh: clampCons(typeof cons === "number" ? cons : BOAT_CONS_DEFAULT_LH),
  };
}

export function useBoatSettings() {
  const [loaded, setLoaded] = useState(false);
  const [draftM, setDraftState] = useState(BOAT_DRAFT_DEFAULT_M);
  const [depthMarginM, setDepthMarginState] = useState(BOAT_DEPTH_MARGIN_DEFAULT_M);
  const [airDraftM, setAirDraftState] = useState(BOAT_AIR_DRAFT_DEFAULT_M);
  const [heightMarginM, setHeightMarginState] = useState(BOAT_HEIGHT_MARGIN_DEFAULT_M);
  const [marginM, setMarginState] = useState(BOAT_MARGIN_DEFAULT_M);
  const [marginMode, setMarginModeState] = useState<MarginMode>(BOAT_MARGIN_MODE_DEFAULT);
  const [cruiseKn, setCruiseState] = useState(BOAT_CRUISE_DEFAULT_KN);
  const [consLh, setConsState] = useState(BOAT_CONS_DEFAULT_LH);

  useEffect(() => {
    (async () => {
      try {
        const v = await getBoatSettings();
        setDraftState(v.draftM);
        setDepthMarginState(v.depthMarginM);
        setAirDraftState(v.airDraftM);
        setHeightMarginState(v.heightMarginM);
        setMarginState(v.marginM);
        setMarginModeState(v.marginMode);
        setCruiseState(v.cruiseKn);
        setConsState(v.consLh);
      } catch { /* garde les défauts */ }
      finally { setLoaded(true); }
    })();
  }, []);

  const setDraftM = useCallback((v: number) => {
    const c = clampDraft(v);
    setDraftState(c);
    storage.setItem(KEY_DRAFT, c).catch(() => {});
  }, []);

  const setDepthMarginM = useCallback((v: number) => {
    const c = clampDepthMargin(v);
    setDepthMarginState(c);
    storage.setItem(KEY_DEPTH_MARGIN, c).catch(() => {});
  }, []);

  const setAirDraftM = useCallback((v: number) => {
    const c = clampAirDraft(v);
    setAirDraftState(c);
    storage.setItem(KEY_AIR_DRAFT, c).catch(() => {});
  }, []);

  const setHeightMarginM = useCallback((v: number) => {
    const c = clampHeightMargin(v);
    setHeightMarginState(c);
    storage.setItem(KEY_HEIGHT_MARGIN, c).catch(() => {});
  }, []);

  const setMarginM = useCallback((v: number) => {
    const c = clampMargin(v);
    setMarginState(c);
    storage.setItem(KEY_MARGIN, c).catch(() => {});
  }, []);

  const setMarginMode = useCallback((v: MarginMode) => {
    const c = sanitizeMarginMode(v);
    setMarginModeState(c);
    storage.setItem(KEY_MARGIN_MODE, c).catch(() => {});
  }, []);

  const setCruiseKn = useCallback((v: number) => {
    const c = clampCruise(v);
    setCruiseState(c);
    storage.setItem(KEY_CRUISE, c).catch(() => {});
  }, []);

  const setConsLh = useCallback((v: number) => {
    const c = clampCons(v);
    setConsState(c);
    storage.setItem(KEY_CONS, c).catch(() => {});
  }, []);

  return {
    loaded,
    draftM, setDraftM,
    depthMarginM, setDepthMarginM,
    airDraftM, setAirDraftM,
    heightMarginM, setHeightMarginM,
    marginM, setMarginM,
    marginMode, setMarginMode,
    cruiseKn, setCruiseKn,
    consLh, setConsLh,
  };
}
