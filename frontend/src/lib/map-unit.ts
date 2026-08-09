// SignalMar — Unité d'affichage des ÉCHELLES de la carte (km ou NM).
// 16/07/2026 (retour user) : bouton engrenage sur les échelles → choix
// KM / NM, persisté localement (AsyncStorage). Une bascule future vers le
// serveur (user.map_unit) est possible sans changer les appelants.

import { useEffect, useState, useCallback } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type MapUnit = "km" | "nm";
const KEY = "signalmar.map_unit.v1";
const DEFAULT: MapUnit = "km";

let memo: MapUnit | null = null;
const listeners = new Set<(u: MapUnit) => void>();

async function loadFromDisk(): Promise<MapUnit> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw === "nm" || raw === "km") return raw;
  } catch { /* noop */ }
  return DEFAULT;
}

export async function getMapUnit(): Promise<MapUnit> {
  if (memo) return memo;
  memo = await loadFromDisk();
  return memo;
}

export async function setMapUnit(u: MapUnit): Promise<void> {
  memo = u;
  try { await AsyncStorage.setItem(KEY, u); } catch { /* noop */ }
  listeners.forEach((l) => l(u));
}

export function useMapUnit(): { unit: MapUnit; setUnit: (u: MapUnit) => void } {
  const [unit, setUnitState] = useState<MapUnit>(memo ?? DEFAULT);
  useEffect(() => {
    let cancelled = false;
    if (!memo) {
      loadFromDisk().then((u) => { if (!cancelled) { memo = u; setUnitState(u); } });
    }
    const fn = (u: MapUnit) => setUnitState(u);
    listeners.add(fn);
    return () => { cancelled = true; listeners.delete(fn); };
  }, []);
  const setUnit = useCallback((u: MapUnit) => { void setMapUnit(u); }, []);
  return { unit, setUnit };
}

/** Conversion mètres → chaîne compacte respectant l'unité choisie.
 *  Arrondi visé « pour l'œil » : jamais de décimales gênantes (5 km, pas
 *  4,982 km). Retourne aussi la valeur numérique arrondie. */
export function formatDistance(meters: number, unit: MapUnit): string {
  if (unit === "nm") {
    const nm = meters / 1852;
    if (nm < 0.1) return `${Math.round(nm * 100) / 100} NM`;
    if (nm < 1) return `${(Math.round(nm * 10) / 10).toString().replace(".", ",")} NM`;
    if (nm < 10) return `${Math.round(nm * 10) / 10}`.replace(".", ",") + " NM";
    return `${Math.round(nm)} NM`;
  }
  // km
  if (meters < 100) return `${Math.round(meters)} m`;
  if (meters < 1000) return `${Math.round(meters / 10) * 10} m`;
  const km = meters / 1000;
  if (km < 10) return `${Math.round(km)}`.replace(".", ",") + " km";
  return `${Math.round(km)} km`;
}

/** Convertit une longueur "1 unité" (1 km ou 1 NM) en mètres pour tracer
 *  la barre d'échelle style Navionics (longueur physique connue à l'écran). */
export function oneUnitMeters(unit: MapUnit): number {
  return unit === "nm" ? 1852 : 1000;
}

/** Libellé affiché sur la barre style Navionics. */
export function oneUnitLabel(unit: MapUnit): string {
  return unit === "nm" ? "1 NM" : "1 km";
}
