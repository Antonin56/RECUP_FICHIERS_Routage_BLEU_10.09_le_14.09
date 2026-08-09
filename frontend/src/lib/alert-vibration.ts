// SignalMar — Vibration d'alerte (14/07/2026).
//
// L'AUDIO des alertes a été SUPPRIMÉ sur décision de l'armateur (système
// vocal jugé trop instable sur device — historique : PRD iter68→72).
// L'alerte repose désormais sur : popup/bannière visuelle + VIBRATION.
// Ce module reprend tel quel le canal vibration de l'ancien voice-player.

import { Platform, Vibration } from "react-native";
import * as Haptics from "expo-haptics";

let pendingHapticHandles: ReturnType<typeof setTimeout>[] = [];
let stopRepeatHandle: ReturnType<typeof setTimeout> | null = null;

/** Pattern vibration "alerte" — PUISSANCE MAX :
 *  • Android : pattern en mode REPEAT (loop infini) → on coupe à 8 s.
 *    Vibrations de 700 ms quasi-continues avec micro-pauses de 80 ms
 *    pour relancer le moteur à chaque cycle (sensation plus tapante).
 *  • Haptics Heavy empilés toutes les 120 ms (≈ 65 impacts sur 8 s) —
 *    saturation volontaire du moteur haptique pour booster l'intensité
 *    perçue, surtout sur iOS où c'est le seul levier disponible.
 *  • Cumul des deux sources Android (pattern + Haptics natifs) qui se
 *    superposent ⇒ moteur vibrant à régime max. */
export function vibrateAlert() {
  // Web preview : navigator.vibrate est bloqué avant interaction → ~50
  // erreurs console par session, sans aucun effet utile. On saute.
  if (Platform.OS === "web") return;
  const TOTAL_MS = 8000;

  // 1) Android — pattern court rejoué en boucle pour exploiter le pic de
  //    courant à chaque démarrage du moteur (plus fort qu'une vibration
  //    continue qui se stabilise à intensité moyenne).
  if (Platform.OS === "android") {
    try {
      Vibration.vibrate(
        [0, 700, 80, 700, 80, 700, 80, 700, 80],
        true, // REPEAT — on coupe explicitement après TOTAL_MS
      );
      stopRepeatHandle = setTimeout(() => {
        try { Vibration.cancel(); } catch { /* noop */ }
        stopRepeatHandle = null;
      }, TOTAL_MS);
    } catch { /* noop */ }
  }

  // 2) Cascade Haptics — toutes les 120 ms, en alternant les types pour
  //    maximiser l'intensité perçue (Warning > Heavy > Rigid sur iOS).
  Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
  const handles: ReturnType<typeof setTimeout>[] = [];
  for (let t = 80, i = 0; t <= TOTAL_MS; t += 120, i++) {
    const style = (i % 3 === 0)
      ? Haptics.ImpactFeedbackStyle.Heavy
      : (i % 3 === 1)
        ? Haptics.ImpactFeedbackStyle.Rigid
        : Haptics.ImpactFeedbackStyle.Heavy;
    handles.push(setTimeout(() => {
      Haptics.impactAsync(style).catch(() => {});
    }, t));
    // Toutes les 1 s, on injecte aussi un Warning (le plus fort).
    if (t % 1000 < 120) {
      handles.push(setTimeout(() => {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
      }, t + 30));
    }
  }
  pendingHapticHandles = handles;
}

/** Coupe immédiatement la vibration d'alerte en cours. */
export function stopAlertFeedback() {
  for (const h of pendingHapticHandles) clearTimeout(h);
  pendingHapticHandles = [];
  if (stopRepeatHandle) { clearTimeout(stopRepeatHandle); stopRepeatHandle = null; }
  if (Platform.OS === "android") {
    try { Vibration.cancel(); } catch { /* noop */ }
  }
}
