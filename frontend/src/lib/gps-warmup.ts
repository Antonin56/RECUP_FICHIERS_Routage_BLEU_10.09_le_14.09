// SignalMar — PRÉCHAUFFAGE GPS au lancement de l'app (13/07/2026).
//
// Bug terrain : « au bout de quelques minutes, toujours pas de localisation ».
// Cause : la puce GPS n'était sollicitée qu'au montage de la carte, et le
// watcher n'était démarré qu'APRÈS un getCurrentPositionAsync bloquant
// (fix à froid = minutes possibles en mer).
// Correctif : dès le démarrage de l'app (root layout) :
//   1) dernière position connue de l'OS (instantanée) ;
//   2) watchPositionAsync haute précision IMMÉDIAT → met la puce GPS en
//      chauffe sans attendre le premier fix ;
//   3) fix rapide en parallèle (non bloquant).
// La carte consomme getWarmLocation() pour afficher la position sans délai.

import * as Location from "expo-location";

export interface WarmFix {
  lat: number;
  lng: number;
  speed: number | null;
  heading: number | null;
  ts: number;
}

let lastFix: WarmFix | null = null;
let started = false;
let sub: Location.LocationSubscription | null = null;

/** Dernière position connue par le warmup (instantané, peut être null). */
export function getWarmLocation(): WarmFix | null {
  return lastFix;
}

function toFix(p: Location.LocationObject): WarmFix {
  return {
    lat: p.coords.latitude,
    lng: p.coords.longitude,
    speed: typeof p.coords.speed === "number" && p.coords.speed >= 0 ? p.coords.speed : null,
    heading: typeof p.coords.heading === "number" && p.coords.heading >= 0 ? p.coords.heading : null,
    ts: p.timestamp ?? Date.now(),
  };
}

/** Démarre la chauffe GPS. Idempotent ; re-tentable si permission refusée
 *  puis accordée plus tard. À appeler dès le lancement de l'app. */
export async function startGpsWarmup(): Promise<void> {
  if (started) return;
  started = true;
  try {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (perm.status !== "granted") {
      started = false; // l'utilisateur pourra accorder plus tard → re-tenter
      return;
    }
    // 1) Dernière position connue de l'OS — ZÉRO attente.
    try {
      const known = await Location.getLastKnownPositionAsync();
      if (known && !lastFix) lastFix = toFix(known);
    } catch { /* pas de position en cache — ok */ }
    // 2) Watcher haute précision immédiat = la puce GPS chauffe dès maintenant.
    sub = await Location.watchPositionAsync(
      { accuracy: Location.Accuracy.High, distanceInterval: 0, timeInterval: 1000 },
      (p) => { lastFix = toFix(p); },
    );
    // 3) Fix rapide en parallèle (réseau/cellules) — non bloquant.
    Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })
      .then((p) => { if (!lastFix || p.timestamp >= lastFix.ts) lastFix = toFix(p); })
      .catch(() => { /* le watcher prendra le relais */ });
  } catch {
    started = false;
  }
}

/** Coupe le warmup (non utilisé en usage normal — la carte a son watcher). */
export function stopGpsWarmup(): void {
  try { sub?.remove(); } catch { /* noop */ }
  sub = null;
  started = false;
}
