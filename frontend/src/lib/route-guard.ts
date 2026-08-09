// SignalMar — Alerte « écart de route » (20/07/2026, GO armateur).
// Option activable + seuil réglable 5-200 m de chaque côté de la route.
import { useCallback, useEffect, useState } from "react";

import type { RouteWaypoint } from "@/src/api/client";
import { storage } from "@/src/utils/storage";

export const ROUTE_GUARD_DEFAULT_ON = true;
export const ROUTE_GUARD_THRESHOLD_DEFAULT_M = 50;
export const ROUTE_GUARD_THRESHOLD_MIN_M = 5;
export const ROUTE_GUARD_THRESHOLD_MAX_M = 200;
/** Ré-alerte tant qu'on reste hors du corridor. */
export const ROUTE_GUARD_REPEAT_MS = 30_000;
/** Hystérésis : retour « dans le corridor » à 80 % du seuil. */
export const ROUTE_GUARD_HYSTERESIS = 0.8;

const KEY_ON = "sm.route.guard_on";
const KEY_THRESHOLD = "sm.route.guard_threshold_m";
// 22/07/2026 (GO armateur) — corridor DYNAMIQUE par défaut : largeur par
// segment calculée par le moteur de route (150 m eaux libres → resserré
// près des obstacles, plancher 40 m). "manual" = seuil fixe de l'utilisateur.
const KEY_MODE = "sm.route.guard_mode";
export type RouteGuardMode = "dynamic" | "manual";
export const ROUTE_GUARD_DEFAULT_MODE: RouteGuardMode = "dynamic";
/** Défaut eaux libres si la route n'a pas de corridor calculé. */
export const ROUTE_GUARD_DYNAMIC_FALLBACK_M = 150;

export function clampGuardThreshold(v: number): number {
  if (!Number.isFinite(v)) return ROUTE_GUARD_THRESHOLD_DEFAULT_M;
  return Math.min(ROUTE_GUARD_THRESHOLD_MAX_M, Math.max(ROUTE_GUARD_THRESHOLD_MIN_M, Math.round(v)));
}

export async function getRouteGuardSettings(): Promise<{ on: boolean; thresholdM: number; mode: RouteGuardMode }> {
  const on = await storage.getItem<boolean>(KEY_ON, ROUTE_GUARD_DEFAULT_ON);
  const th = await storage.getItem<number>(KEY_THRESHOLD, ROUTE_GUARD_THRESHOLD_DEFAULT_M);
  const mode = await storage.getItem<RouteGuardMode>(KEY_MODE, ROUTE_GUARD_DEFAULT_MODE);
  return {
    on: on !== false,
    thresholdM: clampGuardThreshold(typeof th === "number" ? th : ROUTE_GUARD_THRESHOLD_DEFAULT_M),
    mode: mode === "manual" ? "manual" : "dynamic",
  };
}

export function useRouteGuardSettings() {
  const [loaded, setLoaded] = useState(false);
  const [on, setOnState] = useState(ROUTE_GUARD_DEFAULT_ON);
  const [thresholdM, setThresholdState] = useState(ROUTE_GUARD_THRESHOLD_DEFAULT_M);
  const [mode, setModeState] = useState<RouteGuardMode>(ROUTE_GUARD_DEFAULT_MODE);

  useEffect(() => {
    (async () => {
      try {
        const s = await getRouteGuardSettings();
        setOnState(s.on);
        setThresholdState(s.thresholdM);
        setModeState(s.mode);
      } catch { /* défauts */ }
      finally { setLoaded(true); }
    })();
  }, []);

  const setOn = useCallback((v: boolean) => {
    setOnState(v);
    storage.setItem(KEY_ON, v).catch(() => {});
  }, []);

  const setThresholdM = useCallback((v: number) => {
    const c = clampGuardThreshold(v);
    setThresholdState(c);
    storage.setItem(KEY_THRESHOLD, c).catch(() => {});
  }, []);

  const setMode = useCallback((v: RouteGuardMode) => {
    setModeState(v);
    storage.setItem(KEY_MODE, v).catch(() => {});
  }, []);

  return { loaded, on, setOn, thresholdM, setThresholdM, mode, setMode };
}

// ── Distance bateau → route (m) ────────────────────────────────────────────
const M_PER_DEG_LAT = 110_574;

/** 22/07 — position COMPLÈTE du bateau par rapport à la route : écart
 *  latéral, segment le plus proche, distance parcourue (projetée) et
 *  longueur totale. Sert au corridor dynamique ET au suivi de route. */
export interface RoutePosition {
  distM: number;
  segIdx: number;
  alongM: number;
  totalM: number;
  /** 23/07 — projection du bateau SUR la route (tronçon grisé du suivi). */
  projLat: number;
  projLng: number;
}

export function routePosition(
  pos: { lat: number; lng: number },
  waypoints: RouteWaypoint[],
): RoutePosition | null {
  if (waypoints.length < 2) return null;
  const mLng = 111_320 * Math.cos((pos.lat * Math.PI) / 180);
  const px = pos.lng * mLng;
  const py = pos.lat * M_PER_DEG_LAT;
  let best = Infinity;
  let bestIdx = 0;
  let bestAlong = 0;
  let bestQx = waypoints[0].lng * mLng;
  let bestQy = waypoints[0].lat * M_PER_DEG_LAT;
  let cum = 0;
  let ax = waypoints[0].lng * mLng;
  let ay = waypoints[0].lat * M_PER_DEG_LAT;
  for (let i = 1; i < waypoints.length; i++) {
    const bx = waypoints[i].lng * mLng;
    const by = waypoints[i].lat * M_PER_DEG_LAT;
    const dx = bx - ax;
    const dy = by - ay;
    const len = Math.hypot(dx, dy);
    const len2 = len * len;
    const t = len2 <= 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
    const qx = ax + t * dx;
    const qy = ay + t * dy;
    const d = Math.hypot(px - qx, py - qy);
    if (d < best) {
      best = d;
      bestIdx = i - 1;
      bestAlong = cum + t * len;
      bestQx = qx;
      bestQy = qy;
    }
    cum += len;
    ax = bx;
    ay = by;
  }
  return {
    distM: best,
    segIdx: bestIdx,
    alongM: bestAlong,
    totalM: cum,
    projLat: bestQy / M_PER_DEG_LAT,
    projLng: bestQx / mLng,
  };
}

// ── 23/07/2026 — SUIVI DE ROUTE : progression complète pour le panneau
// RouteNavPanel (cap/distance/temps vers le prochain waypoint + arrivée)
// et pour le grisage du tronçon parcouru sur la carte. ────────────────────
export interface RouteNavState {
  /** Index du dernier waypoint DÉPASSÉ (grisé sur la carte). */
  passedIdx: number;
  distToNextM: number;
  distToEndM: number;
  bearingToNextDeg: number;
  /** Écart latéral bateau ↔ route (m). */
  offRouteM: number;
  /** Projection du bateau sur la route (extrémité du tronçon grisé). */
  projLat: number;
  projLng: number;
}

export function routeNavProgress(
  pos: { lat: number; lng: number },
  waypoints: RouteWaypoint[],
): RouteNavState | null {
  const rp = routePosition(pos, waypoints);
  if (!rp) return null;
  const mLng = 111_320 * Math.cos((pos.lat * Math.PI) / 180);
  const nextIdx = Math.min(rp.segIdx + 1, waypoints.length - 1);
  const next = waypoints[nextIdx];
  const dx = (next.lng - pos.lng) * mLng;
  const dy = (next.lat - pos.lat) * M_PER_DEG_LAT;
  const distToNextM = Math.hypot(dx, dy);
  let rem = 0;
  for (let i = nextIdx; i < waypoints.length - 1; i++) {
    rem += Math.hypot(
      (waypoints[i + 1].lng - waypoints[i].lng) * mLng,
      (waypoints[i + 1].lat - waypoints[i].lat) * M_PER_DEG_LAT,
    );
  }
  return {
    passedIdx: rp.segIdx,
    distToNextM,
    distToEndM: distToNextM + rem,
    bearingToNextDeg: (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360,
    offRouteM: rp.distM,
    projLat: rp.projLat,
    projLng: rp.projLng,
  };
}

/** Demi-largeur du corridor au segment donné (mode dynamique). */
export function dynamicCorridorAt(segIdx: number, corridor?: number[] | null): number {
  if (!corridor || corridor.length === 0) return ROUTE_GUARD_DYNAMIC_FALLBACK_M;
  return corridor[Math.min(Math.max(segIdx, 0), corridor.length - 1)];
}

/** Distance minimale (m) d'un point à la polyligne de la route
 *  (projection équirectangulaire locale — largement suffisant < 100 km). */
export function distanceToRouteM(
  pos: { lat: number; lng: number },
  waypoints: RouteWaypoint[],
): number {
  if (waypoints.length === 0) return Infinity;
  const mLng = 111_320 * Math.cos((pos.lat * Math.PI) / 180);
  const px = pos.lng * mLng;
  const py = pos.lat * M_PER_DEG_LAT;
  let best = Infinity;
  let ax = waypoints[0].lng * mLng;
  let ay = waypoints[0].lat * M_PER_DEG_LAT;
  for (let i = 1; i < waypoints.length; i++) {
    const bx = waypoints[i].lng * mLng;
    const by = waypoints[i].lat * M_PER_DEG_LAT;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 <= 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
    const qx = ax + t * dx;
    const qy = ay + t * dy;
    const d = Math.hypot(px - qx, py - qy);
    if (d < best) best = d;
    ax = bx;
    ay = by;
  }
  return best;
}
