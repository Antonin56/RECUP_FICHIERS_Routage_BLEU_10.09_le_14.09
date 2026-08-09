/**
 * SignalMar — Réglages « Navigation & routes » (20/07/2026, GO armateur).
 * Alerte d'ÉCART DE ROUTE : activable/désactivable, corridor DYNAMIQUE
 * (22/07 : largeur calculée par segment — 150 m eaux libres, resserrée près
 * des obstacles, plancher 40 m) ou MANUEL (seuil fixe 5-200 m). Son dédié
 * fourni par l'armateur (« Écart route ») + vibration.
 */
import { StyleSheet, Switch, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { MarineSlider } from "@/src/components/MarineSlider";
import {
  ROUTE_GUARD_THRESHOLD_MAX_M,
  ROUTE_GUARD_THRESHOLD_MIN_M,
  useRouteGuardSettings,
} from "@/src/lib/route-guard";
import { spacing, theme } from "@/src/lib/theme";

export function RouteGuardPanel() {
  const { on, setOn, thresholdM, setThresholdM, mode, setMode } = useRouteGuardSettings();

  return (
    <View style={{ gap: spacing.sm }}>
      <View style={styles.row}>
        <Ionicons name="git-branch" size={18} color={on ? theme.primary : theme.textMute} />
        <View style={{ flex: 1 }}>
          <Text style={styles.label}>Alerte d&apos;écart de route</Text>
          <Text style={styles.hint}>
            Son + vibration quand le bateau sort du corridor de la route active
            (rappel toutes les 30 s tant qu&apos;on est dehors).
          </Text>
        </View>
        <Switch
          value={on}
          onValueChange={setOn}
          trackColor={{ false: theme.bg3, true: "rgba(72,202,228,0.5)" }}
          thumbColor={on ? theme.primary : theme.textMute}
          testID="route-guard-toggle"
        />
      </View>

      {/* 22/07 — mode du corridor : DYNAMIQUE (défaut) ou MANUEL. */}
      <View style={[styles.modeRow, !on && { opacity: 0.4 }]}>
        {([
          ["dynamic", "Dynamique (recommandé)"],
          ["manual", "Manuel"],
        ] as const).map(([m, label]) => {
          const active = mode === m;
          return (
            <TouchableOpacity
              key={m}
              style={[styles.modeChip, active && styles.modeChipOn]}
              onPress={() => setMode(m)}
              disabled={!on}
              testID={`route-guard-mode-${m}`}
            >
              <Text style={[styles.modeTxt, active && styles.modeTxtOn]}>{label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
      {mode === "dynamic" ? (
        <Text style={[styles.hint, !on && { opacity: 0.4 }]}>
          Corridor calculé pour chaque tronçon de la route : 150 m de chaque
          côté en eaux libres, resserré automatiquement à l&apos;approche des
          obstacles (plancher 40 m — précision GPS + embardées de barre).
        </Text>
      ) : (
        <View style={[styles.thresholdBlock, !on && { opacity: 0.4 }]}>
          <View style={styles.thresholdHead}>
            <Text style={styles.label}>Seuil de déclenchement</Text>
            <Text style={styles.value} testID="route-guard-threshold-value">{thresholdM} m</Text>
          </View>
          <MarineSlider
            value={thresholdM}
            minimumValue={ROUTE_GUARD_THRESHOLD_MIN_M}
            maximumValue={ROUTE_GUARD_THRESHOLD_MAX_M}
            step={5}
            onValueChange={setThresholdM}
            disabled={!on}
            testID="route-guard-threshold-slider"
          />
          <View style={styles.bounds}>
            <Text style={styles.boundTxt}>{ROUTE_GUARD_THRESHOLD_MIN_M} m</Text>
            <Text style={styles.boundTxt}>{ROUTE_GUARD_THRESHOLD_MAX_M} m</Text>
          </View>
          <Text style={styles.hint}>
            Distance FIXE tolérée de chaque côté de la route avant l&apos;alerte.
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  label: { color: theme.text, fontSize: 14, fontWeight: "700" },
  hint: { color: theme.textDim, fontSize: 11, lineHeight: 15, marginTop: 2 },
  thresholdBlock: { marginTop: spacing.xs },
  thresholdHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  value: { color: theme.primary, fontSize: 15, fontWeight: "900" },
  bounds: { flexDirection: "row", justifyContent: "space-between", marginTop: -4 },
  boundTxt: { color: theme.textMute, fontSize: 10, fontWeight: "700" },
  modeRow: { flexDirection: "row", gap: 8 },
  modeChip: {
    flex: 1, height: 38, borderRadius: 10, alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg3, borderWidth: 1, borderColor: theme.border,
  },
  modeChipOn: { backgroundColor: "rgba(72,202,228,0.18)", borderColor: theme.primary },
  modeTxt: { color: theme.textDim, fontSize: 12, fontWeight: "800" },
  modeTxtOn: { color: theme.primary },
});
