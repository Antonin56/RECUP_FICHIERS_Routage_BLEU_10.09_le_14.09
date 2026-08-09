// SignalMar — Confirmation « à la Waze » par passage à proximité
// (15/07/2026, GO armateur ; 16/07/2026 durci après retour terrain — aucun
// déclenchement observé alors que l'utilisateur est passé plusieurs fois à
// moins de 500 m d'un signalement).
//
// Quand le bateau EN ROUTE passe à ≤ 500 m d'un signalement actif puis le
// DÉPASSE (distance minimale atteinte puis ré-augmentation — c'est le signal
// « je suis passé à côté », jamais à l'approche), on pose UNE question :
// « Signalement toujours là ? » (Oui, vu ! / Non, pas vu.), avec fermeture
// auto 12 s et une VIBRATION COURTE pour solliciter le regard.
//
// Garde-fous (validés armateur) :
//   • jamais pendant une alerte active (pas de pollution d'affichage) ;
//   • jamais pour ses propres signalements ni ceux déjà confirmés par soi ;
//   • 1 question max par signalement / session — sauf si un GRAND ré-éloignement
//     (> 3 km) puis re-passage : on considère que c'est une NOUVELLE occasion
//     de vérifier (fix 16/07 : le user tournait autour d'un point) ;
//   • 1 popup à la fois + espacement ≥ 60 s entre deux questions ;
//   • bateau EN ROUTE uniquement (vitesse ≥ ~0,8 nd — abaissé le 16/07 pour
//     tolérer les GPS qui rapportent une vitesse instable/nulle en mouvement) ;
//   • aucune réponse = aucun effet (neutre).
//
// FIX 16/07 (bug terrain « aucun déclenchement ») :
//   • `st.asked` posé UNIQUEMENT quand la question est RÉELLEMENT affichée,
//     plus au moment du dépassement (avant, tout blocage tryAsk pour cause
//     de gap 60 s laissait le signalement marqué « vu » à vie) ;
//   • MIN_SPEED_MS abaissé (0.8 → 0.4 m/s ≈ 0.78 nd) car de nombreux GPS
//     rapportent une vitesse < 1 nd même en route (fallback dérivé activé) ;
//   • traçage complet via logger.event("report", …) : entrée en zone, mise
//     à jour de minD, dépassement, tryAsk, échec gap, filtres, etc. ;
//   • ré-armement de la zone quand on sort clairement (> 3× le rayon), pour
//     qu'un tour lointain puis re-passage puisse re-questionner.

import { useCallback, useEffect, useRef, useState } from "react";
import { Platform, Vibration } from "react-native";

import type { ReportItem } from "@/src/api/client";
import { distanceM } from "@/src/lib/sound-alert";
import { logger } from "@/src/lib/logger";

/** Seuil unique de passage (validé armateur — ajustable après analyse). */
export const PASSAGE_RADIUS_M = 500;
/** Vitesse minimale « en route » — abaissée à 0,4 m/s (≈ 0,78 nd) après
 *  le retour terrain 16/07 : plusieurs GPS Android rapportent une vitesse
 *  très instable (0 puis 3 m/s puis 0…) même en mouvement continu. */
const MIN_SPEED_MS = 0.4;
/** Ré-éloignement net qui matérialise le dépassement. */
const OVERTAKE_MARGIN_M = 100;
/** Espacement minimal entre deux questions. */
const MIN_GAP_MS = 60_000;
/** Distance de RÉ-ARMEMENT : au-delà (× cette valeur) du rayon, on remet
 *  la zone à zéro pour permettre une nouvelle question sur un re-passage. */
const REARM_FACTOR = 6; // 500 m × 6 = 3 km

interface ZoneState {
  inZone: boolean;
  minD: number;
  asked: boolean;
  farSince: number; // ts (ms) du 1er tick très loin (> REARM_FACTOR × rayon)
}

export interface ProximityQuestion {
  report: ReportItem;
}

export function useProximityConfirm(params: {
  userLoc: { lat: number; lng: number } | null;
  userSpeedMs: number | null;
  reports: ReportItem[];
  myUserId: string | null;
  /** true si une alerte (bannière/pastille) est affichée → on diffère. */
  alertVisible: boolean;
  enabled: boolean;
}) {
  const { userLoc, userSpeedMs, reports, myUserId, alertVisible, enabled } = params;
  const [question, setQuestion] = useState<ProximityQuestion | null>(null);
  const zonesRef = useRef<Map<string, ZoneState>>(new Map());
  const lastAskedAtRef = useRef(0);
  // Candidats « passage terminé » en attente (ex. alerte affichée au moment
  // du dépassement) — reproposés dès que l'écran est libre.
  const pendingRef = useRef<Map<string, ReportItem>>(new Map());
  const questionRef = useRef<ProximityQuestion | null>(null);
  questionRef.current = question;
  // Fallback vitesse : certains GPS (et le web) ne fournissent pas
  // coords.speed → on la dérive des positions successives.
  const lastPosRef = useRef<{ lat: number; lng: number; t: number } | null>(null);
  // Log unique de démarrage (1er montage effectif) — utile en post-mortem.
  const bootedRef = useRef(false);

  const tryAsk = useCallback(() => {
    if (questionRef.current || pendingRef.current.size === 0) return;
    const now = Date.now();
    const sinceLast = now - lastAskedAtRef.current;
    if (sinceLast < MIN_GAP_MS) {
      logger.event("report", "proximity tryAsk deferred (gap < 60s)", {
        pendingSize: pendingRef.current.size,
        sinceLastMs: sinceLast,
      });
      return;
    }
    // Le plus proche d'abord (si plusieurs passages simultanés).
    const first = pendingRef.current.values().next().value as ReportItem;
    pendingRef.current.delete(first.id);
    // ⚠ On marque asked ICI (au moment où la question est vraiment posée),
    // plus au moment du dépassement — fix 16/07 : sinon un blocage tryAsk
    // (gap 60 s, alerte visible…) laissait le signalement muet à vie.
    const st = zonesRef.current.get(first.id);
    if (st) st.asked = true;
    lastAskedAtRef.current = now;
    setQuestion({ report: first });
    logger.event("report", "proximity question ASKED", {
      id: first.id,
      type: first.type,
    });
    // Vibration COURTE de sollicitation (jamais le pattern d'alerte).
    if (Platform.OS !== "web") {
      try { Vibration.vibrate(200); } catch { /* noop */ }
    }
  }, []);

  useEffect(() => {
    if (!bootedRef.current && enabled && userLoc && myUserId) {
      bootedRef.current = true;
      logger.event("report", "proximity watcher booted", {
        myUserId, hasUserLoc: !!userLoc, reportsCount: reports.length,
      });
    }
    if (!enabled || !userLoc || !myUserId) return;
    let speed = userSpeedMs;
    const nowT = Date.now();
    const prev = lastPosRef.current;
    if (prev && (prev.lat !== userLoc.lat || prev.lng !== userLoc.lng)) {
      const dt = (nowT - prev.t) / 1000;
      // Toujours dériver la vitesse SI le GPS ne l'a pas fournie OU si la
      // valeur GPS est nulle mais on bouge réellement (fix 16/07).
      const gpsSpeedInvalid =
        speed == null || (speed === 0 && dt > 0.3);
      if (gpsSpeedInvalid && dt > 0.3) {
        const derived = distanceM(prev.lat, prev.lng, userLoc.lat, userLoc.lng) / dt;
        if (derived > (speed ?? 0)) speed = derived;
      }
      lastPosRef.current = { lat: userLoc.lat, lng: userLoc.lng, t: nowT };
    } else if (!prev) {
      lastPosRef.current = { lat: userLoc.lat, lng: userLoc.lng, t: nowT };
    }
    const moving = (speed ?? 0) >= MIN_SPEED_MS;
    for (const r of reports) {
      if (r.status && r.status !== "active") continue;
      if (r.author?.user_id === myUserId) continue; // jamais ses signalements
      if (r.confirmed_by_me) continue;              // déjà confirmé par moi
      const d = distanceM(userLoc.lat, userLoc.lng, r.lat, r.lng);
      let st = zonesRef.current.get(r.id);
      if (!st) {
        st = { inZone: false, minD: Infinity, asked: false, farSince: 0 };
        zonesRef.current.set(r.id, st);
      }
      // RÉ-ARMEMENT : si très loin depuis un moment ET déjà questionné,
      // on remet le compteur à zéro pour permettre une nouvelle question
      // à un re-passage franc (le user tourne au large puis revient).
      if (d > PASSAGE_RADIUS_M * REARM_FACTOR) {
        if (st.farSince === 0) st.farSince = nowT;
        else if (nowT - st.farSince > 30_000 && st.asked) {
          logger.event("report", "proximity zone REARMED (far > 30s)", {
            id: r.id, d: Math.round(d),
          });
          st.inZone = false; st.minD = Infinity; st.asked = false; st.farSince = 0;
        }
      } else {
        st.farSince = 0;
      }
      if (st.asked) continue; // 1 question max par signalement / passe
      if (!st.inZone) {
        // Entrée dans le rayon de passage, EN ROUTE uniquement.
        if (d <= PASSAGE_RADIUS_M) {
          if (moving) {
            st.inZone = true; st.minD = d;
            logger.event("report", "proximity zone ENTERED", {
              id: r.id, type: r.type, d: Math.round(d),
              speedMs: speed?.toFixed?.(2) ?? null,
            });
          } else {
            // À l'arrêt dans le rayon : on n'ouvre pas la zone, mais on
            // trace UNE fois pour comprendre les cas terrain.
            logger.event("report", "proximity in-radius but NOT moving", {
              id: r.id, d: Math.round(d),
              speedMs: speed?.toFixed?.(2) ?? null,
              userSpeedMs: userSpeedMs?.toFixed?.(2) ?? null,
            });
          }
        }
        continue;
      }
      const wasMin = st.minD;
      st.minD = Math.min(st.minD, d);
      // DÉPASSEMENT : distance min atteinte puis ré-éloignement net.
      const overtaken =
        d >= wasMin + OVERTAKE_MARGIN_M || d > PASSAGE_RADIUS_M + OVERTAKE_MARGIN_M;
      if (overtaken) {
        pendingRef.current.set(r.id, r);
        logger.event("report", "proximity OVERTAKEN → pending", {
          id: r.id, type: r.type, d: Math.round(d),
          minD: Math.round(wasMin),
          pendingSize: pendingRef.current.size,
          alertVisible,
        });
      }
    }
    if (!alertVisible) tryAsk();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userLoc, userSpeedMs, reports, myUserId, alertVisible, enabled]);

  // L'écran se libère (fin d'alerte) → on repropose un éventuel candidat.
  useEffect(() => {
    if (!alertVisible) tryAsk();
  }, [alertVisible, tryAsk]);

  const dismiss = useCallback(() => setQuestion(null), []);

  return { question, dismiss };
}
