/**
 * SignalMar — TABLEAU DE BORD DE NAVIGATION (28/07/2026, refonte armateur).
 * Une SEULE ligne : cap actuel, vitesse RÉELLE (tap = change d'unité),
 * prochain waypoint, arrivée (distance + ETA). Le CAP À SUIVRE n'est plus
 * une icône ici : il est projeté SUR LA CARTE (ligne vert foncé clonée de
 * la projection de cap). Bouton « Stopper la navigation » en dessous.
 * En navigation, ce tableau REMPLACE les icônes du haut (plein écran).
 */
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/lib/theme";

export interface NavProgress {
  /** Index du dernier waypoint DÉPASSÉ (grisé sur la carte). */
  passedIdx: number;
  distToNextM: number;
  distToEndM: number;
  bearingToNextDeg: number;
}

function fmtDist(m: number, unit: "km" | "nm"): string {
  if (unit === "nm") {
    const nm = m / 1852;
    return nm >= 10 ? `${nm.toFixed(1)} NM` : `${nm.toFixed(2)} NM`;
  }
  return m >= 10_000 ? `${(m / 1000).toFixed(1)} km` : m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
}

function fmtDuration(s: number): string {
  if (!Number.isFinite(s) || s <= 0) return "—";
  const min = Math.round(s / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return `${h} h ${String(min % 60).padStart(2, "0")}`;
}

export function RouteNavPanel(props: {
  progress: NavProgress;
  headingDeg: number | null;
  speedMps: number | null;
  /** Vitesse de croisière (nd) — UNIQUEMENT pour l'ETA quand le bateau est
   *  à l'arrêt (elle n'est plus affichée : la vitesse montrée est RÉELLE). */
  cruiseKn: number;
  unit: "km" | "nm";
  /** 28/07 — unité de vitesse (partagée avec le compteur) : tap = bascule. */
  speedUnit: "kn" | "kmh";
  onToggleSpeedUnit: () => void;
  nextIsEnd: boolean;
  onStop: () => void;
}) {
  const { progress, headingDeg, speedMps, cruiseKn, unit, speedUnit, onToggleSpeedUnit, nextIsEnd, onStop } = props;
  // ETA : vitesse réelle si le bateau avance, sinon croisière (jamais ∞).
  const speedEff = speedMps != null && speedMps > 0.3 ? speedMps : cruiseKn * 0.514444;
  const tNext = progress.distToNextM / speedEff;
  const tEnd = progress.distToEndM / speedEff;
  const eta = new Date(Date.now() + tEnd * 1000);
  // Vitesse RÉELLE affichée (GPS) — 0 si à l'arrêt / signal faible.
  const kmh = speedMps != null && speedMps * 3.6 >= 1 ? speedMps * 3.6 : 0;
  const speedTxt = speedUnit === "kn" ? `${(kmh / 1.852).toFixed(1)} nd` : `${kmh.toFixed(1)} km/h`;

  return (
    <View style={styles.overlay} testID="route-nav-panel" pointerEvents="box-none">
      {/* ── UNE SEULE LIGNE (28/07, demande armateur) ── */}
      <View style={styles.row} pointerEvents="box-none">
        <View style={styles.chip}>
          <Text style={styles.chipLbl}>CAP</Text>
          <Text style={styles.chipValDim}>
            {headingDeg == null ? "—" : `${String(Math.round(headingDeg)).padStart(3, "0")}°`}
          </Text>
        </View>
        <TouchableOpacity
          style={styles.chip}
          onPress={onToggleSpeedUnit}
          activeOpacity={0.7}
          testID="route-nav-speed"
          accessibilityLabel={`Vitesse ${speedTxt}. Toucher pour changer d'unité.`}
        >
          <Text style={styles.chipLbl}>VITESSE</Text>
          <Text style={styles.chipVal}>{speedTxt}</Text>
        </TouchableOpacity>
        <View style={styles.chip}>
          <Text style={styles.chipLbl}>{nextIsEnd ? "DERNIER WP" : "PROCHAIN WP"}</Text>
          <Text style={styles.chipVal} testID="route-nav-next">
            {fmtDist(progress.distToNextM, unit)}
            <Text style={styles.chipSub}> {fmtDuration(tNext)}</Text>
          </Text>
        </View>
        <View style={styles.chip}>
          <Text style={styles.chipLbl}>ARRIVÉE</Text>
          <Text style={styles.chipVal} testID="route-nav-end">
            {fmtDist(progress.distToEndM, unit)}
            <Text style={styles.chipSub}> {eta.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</Text>
          </Text>
        </View>
      </View>
      {/* ── Stopper la navigation (remplace la croix rouge) ── */}
      <TouchableOpacity
        style={styles.stopBtn}
        onPress={onStop}
        activeOpacity={0.85}
        testID="route-nav-stop"
        accessibilityLabel="Stopper la navigation"
      >
        <Ionicons name="stop-circle-outline" size={15} color="#FFB4B6" />
        <Text style={styles.stopTxt}>Stopper la navigation</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { gap: 5, alignItems: "flex-start" },
  row: { flexDirection: "row", alignItems: "stretch", gap: 5, alignSelf: "stretch" },
  chip: {
    flex: 1,
    backgroundColor: "rgba(11,19,43,0.72)",
    borderRadius: 10, borderWidth: 1, borderColor: "rgba(46,196,182,0.28)",
    paddingHorizontal: 7, paddingVertical: 4, minHeight: 42, justifyContent: "center",
  },
  chipLbl: { color: "rgba(232,236,251,0.75)", fontSize: 8, fontWeight: "900", letterSpacing: 0.5 },
  chipVal: {
    color: theme.text, fontSize: 13.5, fontWeight: "900", fontVariant: ["tabular-nums"],
    textShadowColor: "rgba(0,0,0,0.6)", textShadowRadius: 3, textShadowOffset: { width: 0, height: 1 },
  },
  chipValDim: {
    color: "rgba(232,236,251,0.92)", fontSize: 13.5, fontWeight: "800", fontVariant: ["tabular-nums"],
    textShadowColor: "rgba(0,0,0,0.6)", textShadowRadius: 3, textShadowOffset: { width: 0, height: 1 },
  },
  chipSub: { color: "rgba(232,236,251,0.7)", fontSize: 10.5, fontWeight: "700" },
  stopBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(90,20,25,0.85)",
    borderColor: "rgba(229,56,59,0.55)", borderWidth: 1,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 7, minHeight: 34,
  },
  stopTxt: { color: "#FFB4B6", fontSize: 12, fontWeight: "900" },
});
