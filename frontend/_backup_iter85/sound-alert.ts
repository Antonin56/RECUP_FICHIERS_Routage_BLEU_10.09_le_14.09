// SignalMar — MODULE CENTRAL DES ALERTES SONORES & VIBREUR (12/07/2026).
//
// Remplace voice-alert-watcher.ts après l'audit complet du système d'alerte
// (8 bugs identifiés — voir PRD). Règles produit VALIDÉES par l'armateur :
//
//   • VIGIE      → détection 360°, TOUT LE TEMPS, rayon = zoneVigieM.
//   • NAVIGATION → détection UNIQUEMENT dans le cône, ET seulement si le
//     signalement reste dans le cône ≥ CONE_DWELL_MS (3 s) — anti
//     déclenchements intempestifs liés aux petites variations de cap.
//     Sans cap connu (bateau à l'arrêt en mode Nav manuel) : repli 360°
//     sur zoneNavM (sécurité avant tout).
//   • VIBREUR = canal incompressible : vibre pour TOUS les types non coupés,
//     même si la voix est désactivée ou si le type n'a pas de texte vocal.
//   • VOIX     = uniquement pour les types éligibles (cahier des charges) :
//     autorités, obstacles, mammifères marins, animaux blessés/morts,
//     pollutions locale & importante.
//   • UNE SEULE ALERTE PAR PRÉSENCE (13/07/2026, demande user — l'ancienne
//     règle « re-alerte toutes les 5 min tant qu'on reste dedans » faisait
//     BOUCLER l'alerte en stationnaire) : le watcher déclenche UNE annonce ;
//     les relances (0-3, réglées dans le compte) sont gérées par la bannière
//     (map.tsx). Ensuite SILENCE tant qu'on reste dans le périmètre.
//   • RÉ-ARMEMENT : sortie du périmètre (hystérésis ×1,2) pendant ≥ 10 s
//     → l'alerte se ré-arme (re-entrée = nouvelle alerte).
//   • COOLDOWN STRICT (15/07/2026) : même ré-armé, un signalement ne
//     re-déclenche JAMAIS moins de 5 min après son dernier déclenchement.
//   • BLUETOOTH (JBL…) : le MP3 TTS est PRÉCHARGÉ dès qu'un signalement
//     approche du périmètre (×1,3 + 300 m) → lecture instantanée, pas de
//     début de phrase coupé par le réveil A2DP.

import { useEffect } from "react";

import type { ReportItem } from "@/src/api/client";
import { buildAlertText, type VoiceSettings } from "@/src/lib/voice-alerts";
import { vibrateAlert } from "@/src/lib/alert-vibration";
import { playAlertHorn, isHornPlaying } from "@/src/lib/alert-sound";
import { TYPE_BY_ID, type ReportTypeId } from "@/src/lib/report-types";
import { logger } from "@/src/lib/logger";
import { storage } from "@/src/utils/storage";

// ── Constantes du contrat d'alerte ──────────────────────────────────────────
/** Navigation : temps de présence continue dans le cône avant alerte. */
export const CONE_DWELL_MS = 3_000;
/** Ré-armement : durée de sortie franche avant de ré-armer l'alerte. */
export const REARM_EXIT_MS = 10_000;
/** Hystérésis de sortie (évite armé/désarmé en boucle en limite de zone). */
export const EXIT_HYSTERESIS = 1.2;
/** COOLDOWN STRICT (15/07/2026, bug terrain : re-déclenchement < 1 min) —
 *  un MÊME signalement ne peut JAMAIS re-déclencher une alerte moins de
 *  5 min après son dernier déclenchement, même s'il a été ré-armé par une
 *  sortie franche (le ré-armement en Navigation pouvait être provoqué par
 *  une simple embardée de cap qui sortait le signalement du cône 10 s). */
export const REALERT_COOLDOWN_MS = 5 * 60_000;

// Mapping des anciens ids de type (docs pré-27/06) → catalogue v2, pour que
// d'éventuels signalements legacy en cache déclenchent quand même.
const LEGACY_TYPE_MAP: Record<string, string> = {
  authorities: "autorites",
  obstacle: "obstacle_nav",
  ofni: "obstacle_nav",
  fishing_act: "animal_marin",
  species: "animal_marin",
};

/** Distance grand-cercle (m) — Haversine. */
export function distanceM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Cap grand-cercle (° 0-360) de A vers B. */
function bearingDeg(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const p1 = toRad(lat1);
  const p2 = toRad(lat2);
  const dl = toRad(lng2 - lng1);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

/** Le point (report) est-il dans le cône Navigation ?
 *  Géométrie identique au polygone visuel : évasement triangulaire jusqu'à
 *  1 km, puis bande parallèle de demi-largeur 1 km × sin(halfAngle). */
export function isInCone(
  userLat: number, userLng: number, heading: number, halfAngleDeg: number,
  rLat: number, rLng: number, dM: number,
): boolean {
  const brg = bearingDeg(userLat, userLng, rLat, rLng);
  const diff = ((brg - heading + 540) % 360) - 180; // signé
  const absDiff = Math.abs(diff);
  if (absDiff >= 90) return false; // par le travers / derrière
  const halfRad = (halfAngleDeg * Math.PI) / 180;
  const diffRad = (diff * Math.PI) / 180;
  const flareKm = 1.0;
  const halfWidthKm = flareKm * Math.sin(halfRad);
  const dKm = dM / 1000;
  const alongKm = dKm * Math.cos(diffRad);
  if (alongKm < 0) return false;
  const perpKm = Math.abs(dKm * Math.sin(diffRad));
  const alongFlareEnd = flareKm * Math.cos(halfRad);
  if (alongKm <= alongFlareEnd) return absDiff <= halfAngleDeg;
  return perpKm <= halfWidthKm;
}

/** Texte de bannière quand le type n'a pas de message vocal dédié. */
function bannerFallback(type: string): string {
  const label = TYPE_BY_ID[type as ReportTypeId]?.label || "Signalement";
  return `${label} dans votre périmètre d'alerte.`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/** Élément de la file d'alertes séquentielle (hiérarchisée par distance). */
interface QueuedAlert {
  report: ReportItem;
  type: string;
  d: number;
  bannerText: string;
  vibrOn: boolean;
  soundOn: boolean;
}

export interface SoundAlertArgs {
  userLoc: { lat: number; lng: number } | null;
  userSpeedMs: number | null;
  reports: ReportItem[];
  voiceSettings: VoiceSettings;
  /** true = mode Navigation (cône + dwell 3 s), false = Vigie (360°). */
  navMode: boolean;
  /** Cap du bateau (° vrai) — requis pour le cône. */
  userHeading?: number | null;
  /** Demi-angle du cône Navigation (°). */
  coneHalfAngleDeg?: number | null;
  /** Callback UI : bannière « Stopper l'alerte » + répétitions. */
  onAlert?: (report: ReportItem, text: string) => void;
}

// ── ÉTAT DE DÉCLENCHEMENT UNIQUE AU NIVEAU DU MODULE (16/07/2026) ──────────
// BUG TERRAIN (logs 15/07 17:56 & 18:00 : le MÊME id joué 3× en <1 s ;
// re-alertes à 21 s / 66 s / 3 min malgré le cooldown iter77) : l'écran
// carte peut être (re)monté PLUSIEURS fois (navigations pendant les tests
// des boutons de confirmation) et chaque instance avait SA mémoire de
// cooldown et SA file (useRef) → doublons. Tout l'état vit désormais ICI,
// partagé par toutes les instances du hook : les vérifications (verrou de
// présence, cooldown 5 min, dédup de file) sont globales et idempotentes.
const alertedAt = new Map<string, number>();
const lastAlertAt = new Map<string, number>();
const coneSince = new Map<string, number>();
const outsideSince = new Map<string, number>();
const alertQueue: QueuedAlert[] = [];
let queueProcessing = false;
let currentOnAlert: SoundAlertArgs["onAlert"];

// Cooldown 5 min PERSISTÉ sur disque (16/07/2026) : le bug 3b8952da (2
// alertes à <3 min) venait AUSSI d'un redémarrage de l'app entre les deux
// (la mémoire de cooldown était perdue). Rechargé au montage, purgé à 30 min.
const COOLDOWN_STORE_KEY = "signmar.alert.lastAlertAt";
let cooldownLoadStarted = false;
async function loadCooldownStore(): Promise<void> {
  if (cooldownLoadStarted) return;
  cooldownLoadStarted = true;
  try {
    const saved = await storage.getItem<Record<string, number>>(COOLDOWN_STORE_KEY, {});
    const now = Date.now();
    for (const [id, ts] of Object.entries(saved || {})) {
      if (typeof ts === "number" && now - ts < 30 * 60_000 && !lastAlertAt.has(id)) {
        lastAlertAt.set(id, ts);
      }
    }
  } catch { /* best-effort */ }
}
function persistCooldownStore(): void {
  try {
    const now = Date.now();
    const obj: Record<string, number> = {};
    for (const [id, ts] of lastAlertAt) {
      if (now - ts < 30 * 60_000) obj[id] = ts;
    }
    void storage.setItem(COOLDOWN_STORE_KEY, obj);
  } catch { /* best-effort */ }
}

/** File d'alertes GLOBALE, jouée en séquence (une seule boucle, quel que
 *  soit le nombre d'instances du hook montées). */
async function processAlertQueue(): Promise<void> {
  if (queueProcessing) return;
  queueProcessing = true;
  try {
    while (alertQueue.length > 0) {
      // Toujours l'alerte la plus PROCHE en premier (la file est triée
      // à chaque enqueue — des candidats plus proches peuvent s'insérer).
      const item = alertQueue.shift()!;
      currentOnAlert?.(item.report, item.bannerText);
      // 14/07/2026 — corne de brume fournie par l'armateur : on joue le
      // fichier son TEL QUEL, rien d'autre (ni calcul, ni anticipation).
      if (item.soundOn) playAlertHorn();
      if (item.vibrOn) vibrateAlert();
      logger.event("report", "sound-alert jouée (file)", {
        id: item.report.id, type: item.type,
        distanceM: Math.round(item.d), reste: alertQueue.length,
      });
      // On laisse chaque alerte exister distinctement (bannière + corne +
      // vibration) avant d'afficher la suivante.
      await sleep(3_500);
      // 14/07/2026 (bug terrain vidéo user) : la corne dure ~6 s — elle ne
      // doit JAMAIS être interrompue ni rejouée avant sa FIN. On attend
      // donc la fin réelle du son avant l'alerte suivante (borne 12 s).
      const hornWaitT0 = Date.now();
      while (isHornPlaying() && Date.now() - hornWaitT0 < 12_000) {
        await sleep(250);
      }
      await sleep(800); // respiration entre deux alertes
    }
  } finally {
    queueProcessing = false;
  }
}

/**
 * useSoundAlertWatcher — le SEUL point de déclenchement des alertes de
 * proximité (son + vibreur + bannière). Tourne en Vigie ET en Navigation.
 */
export function useSoundAlertWatcher(args: SoundAlertArgs) {
  const {
    userLoc, userSpeedMs, reports, voiceSettings,
    navMode, userHeading, coneHalfAngleDeg, onAlert,
  } = args;

  // La dernière instance rendue fournit le callback bannière (celle qui est
  // visible à l'écran) + chargement du cooldown persisté au premier montage.
  useEffect(() => { void loadCooldownStore(); }, []);
  useEffect(() => { currentOnAlert = onAlert; }, [onAlert]);

  useEffect(() => {
    if (!userLoc || !reports || reports.length === 0) return;
    // Vibreur = minimum incompressible : le watcher tourne dès qu'AU MOINS
    // un canal est actif (le panel garantit qu'on ne peut pas tout couper).
    const alertsOn = voiceSettings.enabled !== false;
    const vibrOn = voiceSettings.vibrationEnabled !== false;
    if (!alertsOn && !vibrOn) return;

    const zoneVigieM = Math.max(1, voiceSettings.zoneVigieM || 1);
    const zoneNavM = Math.max(1, voiceSettings.zoneNavM || 1);
    const now = Date.now();
    const coneReady =
      navMode &&
      typeof userHeading === "number" &&
      typeof coneHalfAngleDeg === "number" &&
      (coneHalfAngleDeg ?? 0) > 0;

    const candidates: { id: string; d: number; report: ReportItem }[] = [];
    for (const r of reports) {
      if (typeof r.lat !== "number" || typeof r.lng !== "number") continue;
      const type = LEGACY_TYPE_MAP[r.type] ?? r.type;
      const st = r.status;
      if (st && st !== "active") {
        // Signalement clos → purge de tout état résiduel.
        alertedAt.delete(r.id);
        lastAlertAt.delete(r.id);
        coneSince.delete(r.id);
        outsideSince.delete(r.id);
        continue;
      }
      if (voiceSettings.mutedTypes?.includes(type)) continue;

      const d = distanceM(userLoc.lat, userLoc.lng, r.lat, r.lng);

      // ── Détection selon le mode ──
      let inside: boolean;
      if (!navMode) {
        // VIGIE : 360°, tout le temps.
        inside = d <= zoneVigieM;
        coneSince.delete(r.id);
      } else if (coneReady) {
        // NAVIGATION : cône + présence continue ≥ 3 s (anti-jitter de cap).
        const inCone = d <= zoneNavM && isInCone(
          userLoc.lat, userLoc.lng, userHeading as number,
          coneHalfAngleDeg as number, r.lat, r.lng, d,
        );
        if (inCone) {
          if (!coneSince.has(r.id)) coneSince.set(r.id, now);
          inside = now - (coneSince.get(r.id) ?? now) >= CONE_DWELL_MS;
        } else {
          coneSince.delete(r.id);
          inside = false;
        }
      } else {
        // Nav manuel sans cap connu → repli 360° sur zoneNavM (sécurité).
        inside = d <= zoneNavM;
      }

      // ── Ré-armement à la sortie franche du périmètre ──
      const clearlyOutside = navMode
        ? d > zoneNavM * EXIT_HYSTERESIS || (coneReady && !coneSince.has(r.id) && !inside && d > zoneVigieM * EXIT_HYSTERESIS)
        : d > zoneVigieM * EXIT_HYSTERESIS;
      if (clearlyOutside) {
        if (!outsideSince.has(r.id)) outsideSince.set(r.id, now);
        if (now - (outsideSince.get(r.id) ?? now) >= REARM_EXIT_MS) {
          alertedAt.delete(r.id); // ré-armé
        }
      } else {
        outsideSince.delete(r.id);
      }

      if (!inside) continue;
      // DÉJÀ ALERTÉ pendant cette présence → SILENCE tant qu'on reste dans
      // le périmètre (13/07/2026 : suppression du re-déclenchement 5 min qui
      // faisait boucler l'alerte en stationnaire). L'entrée est effacée par
      // le ré-armement (sortie franche ≥ 10 s) ou la clôture du signalement.
      if (alertedAt.has(r.id)) continue;
      // COOLDOWN STRICT (15/07/2026, bug terrain : re-déclenchement < 1 min
      // après ré-armement par embardée de cap en Navigation) : un même
      // signalement ne re-déclenche JAMAIS avant 5 min, quoi qu'il arrive.
      const lastAt = lastAlertAt.get(r.id);
      if (lastAt != null && now - lastAt < REALERT_COOLDOWN_MS) continue;
      candidates.push({ id: r.id, d, report: r });
    }

    if (candidates.length === 0) return;
    candidates.sort((a, b) => a.d - b.d);

    // ── ENQUEUE (13/07/2026) : TOUS les candidats entrent dans la file,
    // hiérarchisée par distance, puis sont joués en séquence. Le cooldown
    // démarre à l'enqueue (pas de double-entrée pendant l'attente).
    for (const c of candidates) {
      if (alertQueue.some((q) => q.report.id === c.id)) continue;
      alertedAt.set(c.id, now);
      lastAlertAt.set(c.id, now); // cooldown strict 5 min
      const cType = LEGACY_TYPE_MAP[c.report.type] ?? c.report.type;
      // BUG FIX (audit 12/07) : la santé de l'animal vit dans extras.health.
      const health = (c.report.extras as { health?: string } | undefined)?.health;
      const voiceText = buildAlertText(
        { type: cType, subtype: c.report.subtype ?? undefined, health },
        userSpeedMs,
      );
      alertQueue.push({
        report: c.report,
        type: cType,
        d: c.d,
        bannerText: voiceText ?? bannerFallback(cType),
        vibrOn,
        soundOn: alertsOn,
      });
    }
    alertQueue.sort((a, b) => a.d - b.d);
    persistCooldownStore();
    void processAlertQueue();
  }, [
    userLoc, userSpeedMs, reports, voiceSettings,
    navMode, userHeading, coneHalfAngleDeg, onAlert,
  ]);
}
