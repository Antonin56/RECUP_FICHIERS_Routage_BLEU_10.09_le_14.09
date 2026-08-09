// SignalMar — Hook de calcul de l'état COULEUR du cône Navigation.
// 17/07/2026 (v2 cône coloré) — orchestré indépendamment du son (pour
// zéro couplage : le son ne doit ABSOLUMENT PAS régresser) mais réutilise
// les mêmes règles géométriques (isInCone, distanceM) que sound-alert.ts.
//
// États :
//   • green  → 0 signalement dans le cône
//   • orange → ≥ 1 signalement dans le cône, TOUS au-delà de alertDistNavM
//   • red    → ≥ 1 signalement dans la ZONE D'ALERTE (subset : d ≤ alertDistNavM
//              ET dans le cône)
//
// Politique de latence (choix user [b] du 16/07/2026) :
//   • Passage à un état PLUS CHAUD (green→orange, green/orange→red) : INSTANTANÉ
//     au tick GPS (réactivité maximale à la menace).
//   • Retour à un état PLUS FROID (red→orange/green, orange→green) : dwell 5 s
//     minimum sans candidat qualifiant (anti-clignotement sur GPS bruité).
//
// Pas de gestion d'événements audio ici — le rouge SEUL est corrélé au son
// (via alertDistNavM également), mais aucune commande audio n'émane de ce
// hook : sound-alert.ts reste 100 % maître de son domaine.

import { useEffect, useRef, useState } from "react";

import type { ReportItem } from "@/src/api/client";
import { distanceM, isInCone } from "@/src/lib/sound-alert";

export type ConeState = "green" | "orange" | "red";

// 5 s de latence avant retour à un état plus froid — cohérent avec le
// dwell audio (3 s) tout en évitant le clignotement chromatique.
const COOL_DOWN_MS = 5_000;

export function useConeState(params: {
  userLoc: { lat: number; lng: number } | null;
  userHeading: number | null;
  coneHalfAngleDeg: number | null;
  zoneNavM: number; // longueur du cône (m)
  alertDistanceNavM: number; // distance de déclenchement d'alerte (m)
  reports: ReportItem[];
  /** false en mode Vigie → l'état est toujours 'green' (le cône n'est
   *  d'ailleurs pas affiché). */
  navMode: boolean;
  /** false → hook au repos (renvoie 'green'). Utile pour couper en démo. */
  enabled: boolean;
}): ConeState {
  const {
    userLoc, userHeading, coneHalfAngleDeg,
    zoneNavM, alertDistanceNavM, reports, navMode, enabled,
  } = params;

  const [state, setState] = useState<ConeState>("green");
  // Timestamp du dernier tick où on était en état ≥ orange ou ≥ red.
  // Sert au cool-down 5 s : on ne redescend qu'après COOL_DOWN_MS écoulés.
  const lastOrangeRef = useRef(0);
  const lastRedRef = useRef(0);
  const stateRef = useRef<ConeState>("green");
  stateRef.current = state;

  useEffect(() => {
    if (!enabled || !navMode || !userLoc || userHeading == null ||
        coneHalfAngleDeg == null || !(coneHalfAngleDeg > 0)) {
      // Hors nav ou paramètres incomplets → toujours green (safe default).
      if (stateRef.current !== "green") setState("green");
      lastOrangeRef.current = 0;
      lastRedRef.current = 0;
      return;
    }
    const now = Date.now();
    const alertDist = Math.min(zoneNavM, Math.max(100, alertDistanceNavM));

    let hasInCone = false;
    let hasInAlert = false;
    for (const r of reports) {
      if (typeof r.lat !== "number" || typeof r.lng !== "number") continue;
      if (r.status && r.status !== "active") continue;
      const d = distanceM(userLoc.lat, userLoc.lng, r.lat, r.lng);
      // Optim : skip immédiat si hors du cône par distance seule.
      if (d > zoneNavM) continue;
      if (!isInCone(userLoc.lat, userLoc.lng, userHeading, coneHalfAngleDeg, r.lat, r.lng, d)) continue;
      hasInCone = true;
      if (d <= alertDist) { hasInAlert = true; break; } // rouge = état max
    }

    // ── Calcul de l'état cible avec logique de cool-down ─────────────
    // « Chaud instantané, froid retardé » — validation user 16/07/2026.
    if (hasInAlert) {
      lastRedRef.current = now;
      lastOrangeRef.current = now;
      if (stateRef.current !== "red") setState("red");
    } else if (hasInCone) {
      lastOrangeRef.current = now;
      // Si on était en rouge, on ne redescend en orange qu'après cool-down.
      const stillRed =
        stateRef.current === "red" &&
        (now - lastRedRef.current) < COOL_DOWN_MS;
      if (stillRed) {
        // rester en rouge — pas de changement d'état.
      } else if (stateRef.current !== "orange") setState("orange");
    } else {
      // Rien dans le cône. Cool-down avant de rebasculer au vert.
      const stillRed =
        stateRef.current === "red" &&
        (now - lastRedRef.current) < COOL_DOWN_MS;
      const stillOrange =
        stateRef.current === "orange" &&
        (now - lastOrangeRef.current) < COOL_DOWN_MS;
      if (stillRed) {
        // stay red
      } else if (stillOrange) {
        // stay orange
      } else if (stateRef.current !== "green") {
        setState("green");
      }
    }
  }, [userLoc, userHeading, coneHalfAngleDeg, zoneNavM, alertDistanceNavM, reports, navMode, enabled]);

  return state;
}
