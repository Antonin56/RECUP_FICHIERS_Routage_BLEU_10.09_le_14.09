// SignalMar — SON D'ALERTE (14/07/2026, décision armateur).
//
// L'alerte joue UN fichier son TEL QUEL quand un signalement déclencheur
// entre dans le périmètre — aucun calcul, aucune anticipation, aucun
// préchauffage. Joué UNE SEULE FOIS par alerte, rejoué uniquement selon les
// répétitions configurées (bannière map.tsx).
//
// ⚠️ CODE DE DÉCLENCHEMENT FIGÉ (exigence armateur 14/07) : les points
// d'entrée playAlertHorn / stopAlertHorn / isHornPlaying gardent EXACTEMENT
// la même signature et les mêmes règles (jamais d'interruption, jamais de
// rejeu avant la fin). Seul le CHOIX du fichier est configurable (Réglages).
//
// Sons disponibles (choix user persisté dans voiceSettings.alertSound) :
//   • "horn"  — corne de brume (boat_horn_1_time.mp3, ~6 s) — DÉFAUT
//   • "sonar" — ping sonar (sonar-ping_loud.mp3)

import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from "expo-audio";

import { getVoiceSettings } from "@/src/lib/voice-settings";

export type AlertSoundId = "horn" | "sonar";

/** Catalogue affiché dans les Réglages (« Son d'alerte »). */
export const ALERT_SOUNDS: { id: AlertSoundId; label: string }[] = [
  { id: "horn", label: "Corne de brume" },
  { id: "sonar", label: "Ping sonar" },
];

// Assets embarqués dans le bundle (aucun réseau nécessaire).
const SOUND_ASSETS: Record<AlertSoundId, number> = {
  horn: require("../../assets/sounds/boat_horn_1_time.mp3"),
  sonar: require("../../assets/sounds/sonar-ping_loud.mp3"),
};

const players: Partial<Record<AlertSoundId, AudioPlayer>> = {};
let audioModeReady: Promise<void> | null = null;
// 16/07/2026 (bug terrain « plus aucun son ») : si le flag `playing` d'un
// player reste bloqué à true (état natif corrompu après stop/lectures en
// rafale), TOUTES les lectures suivantes étaient ignorées à vie par la règle
// de non-interruption. On borne donc la confiance dans `playing` : au-delà
// de 15 s après le dernier départ de lecture (fichiers ≤ ~6 s), il est
// considéré OBSOLÈTE et on rejoue.
let lastPlayStartAt = 0;
const PLAYING_STALE_MS = 15_000;

/** Session audio configurée UNE SEULE FOIS, et JAMAIS pendant une lecture
 *  (sur Android, reconfigurer la session en cours de lecture peut couper le
 *  son). On l'attend systématiquement AVANT de jouer. */
function ensureAudioMode(): Promise<void> {
  if (!audioModeReady) {
    audioModeReady = setAudioModeAsync({
      playsInSilentMode: true,
      interruptionMode: "duckOthers",
    }).catch(() => {});
  }
  return audioModeReady;
}

/** Un son d'alerte est-il en cours de lecture ? (utilisé par la file
 *  d'alertes pour NE JAMAIS enchaîner avant la fin du son.) */
export function isHornPlaying(): boolean {
  for (const p of Object.values(players)) {
    try { if (p?.playing) return true; } catch { /* noop */ }
  }
  return false;
}

function playSound(id: AlertSoundId) {
  const existing = players[id];
  if (!existing) {
    const p = createAudioPlayer(SOUND_ASSETS[id]);
    p.volume = 1;
    players[id] = p;
    p.play();
    return;
  }
  // Lecture terminée (ou stoppée) : on repart du début du fichier.
  void existing.seekTo(0);
  existing.play();
}

/** Joue le son d'alerte CHOISI par l'utilisateur, UNE FOIS, intégralement.
 *  RÈGLE ABSOLUE (14/07/2026) : le son ne doit JAMAIS être interrompu ni
 *  redémarré tant qu'il n'a pas été joué en entier → si une lecture est en
 *  cours, la demande est simplement IGNORÉE. */
export function playAlertHorn() {
  void ensureAudioMode()
    .then(() => getVoiceSettings())
    .then((s) => {
      try {
        const sincePlay = Date.now() - lastPlayStartAt;
        if (isHornPlaying() && sincePlay < PLAYING_STALE_MS) return; // en cours → ne pas interrompre
        lastPlayStartAt = Date.now();
        playSound(s.alertSound === "sonar" ? "sonar" : "horn");
      } catch { /* noop — le son ne doit jamais faire crasher l'alerte */ }
    })
    .catch(() => { /* noop */ });
}

/** Pré-écoute d'un son depuis les Réglages (bouton « Écouter »).
 *  Contrairement à l'alerte, la pré-écoute PEUT couper une lecture en cours
 *  (l'utilisateur compare les sons). */
export function previewAlertSound(id: AlertSoundId) {
  void ensureAudioMode().then(() => {
    try {
      stopAlertHorn();
      lastPlayStartAt = Date.now();
      playSound(id);
    } catch { /* noop */ }
  });
}

// ── N2 (20/07/2026) — SON D'ÉCART DE ROUTE ────────────────────────────────
// DIFFÉRENT des sons d'alerte de signalement (règle armateur).
// 22/07/2026 — fichier FOURNI par l'armateur (« Ecart route.mp3 »).
const ROUTE_DEVIATION_ASSET: number | null = require("../../assets/sounds/route_deviation.mp3");
let deviationPlayer: ReturnType<typeof createAudioPlayer> | null = null;

export function playRouteDeviationSound() {
  if (ROUTE_DEVIATION_ASSET == null) return; // fichier pas encore fourni
  void ensureAudioMode().then(() => {
    try {
      if (!deviationPlayer) {
        deviationPlayer = createAudioPlayer(ROUTE_DEVIATION_ASSET);
        deviationPlayer.volume = 1;
      } else {
        void deviationPlayer.seekTo(0);
      }
      deviationPlayer.play();
    } catch {
      // 29/07/2026 (retour mer « l'alarme d'écart ne sonne pas ») — player
      // natif corrompu (kill arrière-plan, session audio perdue) : on le
      // RECRÉE et on rejoue au lieu d'échouer en silence pour toujours.
      try {
        deviationPlayer = createAudioPlayer(ROUTE_DEVIATION_ASSET);
        deviationPlayer.volume = 1;
        deviationPlayer.play();
      } catch { /* noop */ }
    }
  });
}

/** 29/07/2026 (« Oui, tout s'arrête ») — coupe NET le son d'écart de route
 *  (appelé par stopFollow : plus aucun son après l'arrêt de la navigation). */
export function stopRouteDeviationSound() {
  try {
    if (deviationPlayer) { deviationPlayer.pause(); void deviationPlayer.seekTo(0); }
  } catch { /* noop */ }
}

/** Coupe immédiatement le son d'alerte (bouton « Stopper l'alerte »,
 *  démontage d'écran). */
export function stopAlertHorn() {  for (const p of Object.values(players)) {
    try {
      if (p) { p.pause(); void p.seekTo(0); }
    } catch { /* noop */ }
  }
}

// ── 22/07/2026 (GO armateur) — SON D'ALARME DE MOUILLAGE ──────────────────
// Bitonale insistante (700/520 Hz) DISTINCTE de la corne, du sonar et de
// l'écart de route. Générée localement (anchor_alarm.wav) en attendant un
// éventuel fichier fourni par l'armateur.
const ANCHOR_ALARM_ASSET: number = require("../../assets/sounds/anchor_alarm.wav");
let anchorPlayer: ReturnType<typeof createAudioPlayer> | null = null;

export function playAnchorAlarmSound() {
  void ensureAudioMode().then(() => {
    try {
      if (!anchorPlayer) {
        anchorPlayer = createAudioPlayer(ANCHOR_ALARM_ASSET);
        anchorPlayer.volume = 1;
      } else {
        void anchorPlayer.seekTo(0);
      }
      anchorPlayer.play();
    } catch { /* noop */ }
  });
}

export function stopAnchorAlarmSound() {
  try {
    if (anchorPlayer) { anchorPlayer.pause(); void anchorPlayer.seekTo(0); }
  } catch { /* noop */ }
}
