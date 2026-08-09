/**
 * SignalMar — ALARME DE MOUILLAGE (22/07/2026, GO armateur).
 *
 * Le bateau est à l'ancre : on mémorise la position de mouillage et un RAYON
 * DE GARDE (défaut 15 m, borné 5-100 m, réglable dans les Réglages). Si le
 * bateau dérive au-delà du rayon → alarme (son dédié + vibration + bannière).
 * L'ancre est PERSISTÉE localement : elle survit à un redémarrage de l'app
 * (mouillage de nuit).
 */
import { useCallback, useEffect, useState } from "react";

import { storage } from "@/src/utils/storage";

export const ANCHOR_RADIUS_DEFAULT_M = 15;
export const ANCHOR_RADIUS_MIN_M = 5;
export const ANCHOR_RADIUS_MAX_M = 100;

const KEY_RADIUS = "sm.anchor.radius_m";
const KEY_POS = "sm.anchor.pos";

export interface AnchorPos {
  lat: number;
  lng: number;
  /** Epoch ms du mouillage (affichage « à l'ancre depuis »). */
  since: number;
}

export function clampAnchorRadius(v: number): number {
  if (!Number.isFinite(v)) return ANCHOR_RADIUS_DEFAULT_M;
  return Math.round(Math.min(ANCHOR_RADIUS_MAX_M, Math.max(ANCHOR_RADIUS_MIN_M, v)));
}

export async function getAnchorRadiusM(): Promise<number> {
  const v = await storage.getItem<number>(KEY_RADIUS, ANCHOR_RADIUS_DEFAULT_M);
  return clampAnchorRadius(typeof v === "number" ? v : ANCHOR_RADIUS_DEFAULT_M);
}

export async function getAnchorPos(): Promise<AnchorPos | null> {
  const v = await storage.getItem<AnchorPos | null>(KEY_POS, null);
  if (v && typeof v.lat === "number" && typeof v.lng === "number") return v;
  return null;
}

export async function setAnchorPos(pos: AnchorPos | null): Promise<void> {
  await storage.setItem(KEY_POS, pos);
}

/** Réglage du rayon de garde (page Réglages). */
export function useAnchorRadius() {
  const [loaded, setLoaded] = useState(false);
  const [radiusM, setRadiusState] = useState(ANCHOR_RADIUS_DEFAULT_M);

  useEffect(() => {
    (async () => {
      try {
        setRadiusState(await getAnchorRadiusM());
      } catch { /* défaut */ }
      finally { setLoaded(true); }
    })();
  }, []);

  const setRadiusM = useCallback((v: number) => {
    const c = clampAnchorRadius(v);
    setRadiusState(c);
    storage.setItem(KEY_RADIUS, c).catch(() => {});
  }, []);

  return { loaded, radiusM, setRadiusM };
}
