/**
 * SignalMar — Barre de COMPARAISON A/B de deux moteurs (02/08/2026).
 *
 * Affichée au-dessus de la RouteCard quand l'armateur a recalculé la route
 * avec un autre moteur : légende des deux tracés (couleur + nom + ID du
 * moteur), distances, fond mini, écart maximal, nombre de zones divergentes.
 * Deux actions : adopter la variante (elle devient la route active) ou fermer
 * la comparaison (la route de référence reste affichée).
 */
import * as Clipboard from "expo-clipboard";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { showToast } from "@/src/components/Toast";
import { radii, spacing, theme } from "@/src/lib/theme";

export const BASE_COLOR = "#e034de";
export const VARIANT_COLOR = "#FFB703";

function fmtKm(m: number, unit: "km" | "nm"): string {
  return unit === "nm" ? `${(m / 1852).toFixed(1)} NM` : `${(m / 1000).toFixed(1)} km`;
}

function fmtDelta(m: number, unit: "km" | "nm"): string {
  const sign = m > 0 ? "+" : m < 0 ? "−" : "±";
  const abs = Math.abs(m);
  if (abs < 1000) return `${sign}${Math.round(abs)} m`;
  return `${sign}${fmtKm(abs, unit)}`;
}

export function RouteCompareBar(props: {
  unit: "km" | "nm";
  base: { name: string; id: string; distanceM: number; minDepthM: number | null };
  variant: { name: string; id: string; distanceM: number; minDepthM: number | null };
  maxDevM: number;
  zones: number;
  identical: boolean;
  /** 27/08/2026 (demande armateur) — coordonnées EXACTES du départ et de
   *  l'arrivée comparés (communes aux deux tracés). Tap = copier. */
  start?: { lat: number; lng: number } | null;
  end?: { lat: number; lng: number } | null;
  /** Recentre la carte sur la zone de plus grand écart. */
  onFocusDiff?: () => void;
  onKeepVariant: () => void;
  onClose: () => void;
}) {
  const { unit, base, variant, maxDevM, zones, identical, start, end, onFocusDiff, onKeepVariant, onClose } = props;
  const dDist = variant.distanceM - base.distanceM;
  return (
    <View style={styles.card} testID="route-compare-bar">
      <View style={styles.head}>
        <Ionicons name="git-compare" size={16} color="#48CAE4" />
        <Text style={styles.title}>Comparaison de moteurs</Text>
        <TouchableOpacity onPress={onClose} hitSlop={10} testID="route-compare-close">
          <Ionicons name="close" size={18} color={theme.textMute} />
        </TouchableOpacity>
      </View>

      <View style={styles.row}>
        <View style={[styles.dot, { backgroundColor: BASE_COLOR }]} />
        <Text style={styles.name} numberOfLines={1}>{base.name}</Text>
        <Text style={styles.id} numberOfLines={1}>{base.id}</Text>
        <Text style={styles.val}>
          {fmtKm(base.distanceM, unit)}
          {base.minDepthM != null ? ` · ${base.minDepthM.toFixed(1)} m` : ""}
        </Text>
      </View>
      <View style={styles.row}>
        <View style={[styles.dot, styles.dotDash, { borderColor: VARIANT_COLOR }]} />
        <Text style={styles.name} numberOfLines={1}>{variant.name}</Text>
        <Text style={styles.id} numberOfLines={1}>{variant.id}</Text>
        <Text style={[styles.val, { color: VARIANT_COLOR }]}>
          {fmtKm(variant.distanceM, unit)}
          {variant.minDepthM != null ? ` · ${variant.minDepthM.toFixed(1)} m` : ""}
        </Text>
      </View>

      {/* 27/08/2026 (demande armateur) — coordonnées exactes du trajet
          comparé (mêmes départ/arrivée pour les deux moteurs). */}
      {start && end ? (
        <View style={styles.coordCol} testID="compare-coords">
          {([
            ["Départ", start, "flag-outline", "#80ED99"],
            ["Arrivée", end, "location-outline", "#E5383B"],
          ] as const).map(([label, p, icon, color]) => (
            <TouchableOpacity
              key={label}
              style={styles.coordChip}
              onPress={async () => {
                await Clipboard.setStringAsync(`${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}`);
                showToast("success", `${label} copié : ${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}`);
              }}
              activeOpacity={0.7}
              hitSlop={6}
              testID={`compare-coord-${label === "Départ" ? "start" : "end"}`}
            >
              <Ionicons name={icon} size={12} color={color} />
              <Text style={[styles.coordLabel, { color }]}>{label}</Text>
              <Text style={styles.coordText} numberOfLines={1}>
                {p.lat.toFixed(6)}, {p.lng.toFixed(6)}
              </Text>
              <Ionicons name="copy-outline" size={11} color={theme.textDim} />
            </TouchableOpacity>
          ))}
        </View>
      ) : null}

      <Text style={styles.summary}>
        {identical
          ? "Tracés identiques : ce moteur produit exactement la même route."
          : `${zones} zone${zones > 1 ? "s" : ""} de divergence · écart maxi ${Math.round(maxDevM)} m · distance ${fmtDelta(dDist, unit)}`}
      </Text>

      {!identical && onFocusDiff ? (
        <TouchableOpacity
          style={styles.zoomBtn}
          onPress={onFocusDiff}
          activeOpacity={0.85}
          testID="route-compare-focus"
        >
          <Ionicons name="search" size={14} color="#48CAE4" />
          <Text style={styles.zoomTxt}>Zoomer sur le plus grand écart</Text>
        </TouchableOpacity>
      ) : null}

      <View style={styles.btnRow}>
        <TouchableOpacity
          style={[styles.btn, styles.btnGhost]}
          onPress={onClose}
          activeOpacity={0.85}
          testID="route-compare-dismiss"
        >
          <Text style={styles.btnGhostTxt}>Garder la route actuelle</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.btn, styles.btnKeep, identical && styles.btnOff]}
          onPress={onKeepVariant}
          activeOpacity={0.85}
          disabled={identical}
          testID="route-compare-keep"
        >
          <Ionicons name="checkmark" size={15} color="#04121F" />
          <Text style={styles.btnKeepTxt}>Adopter la variante</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "rgba(11,19,43,0.94)",
    borderRadius: radii.md, borderWidth: 1, borderColor: "rgba(72,202,228,0.35)",
    padding: spacing.sm, gap: 6, marginBottom: 8,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 7 },
  title: { flex: 1, color: theme.text, fontSize: 13, fontWeight: "800" },
  row: { flexDirection: "row", alignItems: "center", gap: 7 },
  dot: { width: 11, height: 4, borderRadius: 2 },
  dotDash: { backgroundColor: "transparent", borderWidth: 2, height: 0 },
  name: { color: theme.text, fontSize: 12, fontWeight: "700", maxWidth: "34%" },
  id: {
    flex: 1, color: theme.textDim, fontSize: 10,
    fontVariant: ["tabular-nums"],
  },
  val: { color: theme.text, fontSize: 11.5, fontWeight: "800" },
  // 27/08 — coordonnées exactes départ/arrivée (tap = copier).
  coordCol: { gap: 4 },
  coordChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    alignSelf: "stretch", paddingVertical: 4, paddingHorizontal: 8,
    backgroundColor: "rgba(255,255,255,0.04)",
    borderWidth: 1, borderColor: theme.border, borderRadius: radii.sm,
  },
  coordLabel: { fontSize: 10.5, fontWeight: "900", width: 46 },
  coordText: {
    flex: 1, color: theme.textDim, fontSize: 11, fontWeight: "700",
    fontVariant: ["tabular-nums"], letterSpacing: 0.3,
  },
  summary: { color: theme.textDim, fontSize: 11, lineHeight: 15 },
  zoomBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 40, borderRadius: radii.md,
    borderWidth: 1, borderColor: "rgba(72,202,228,0.32)",
    backgroundColor: "rgba(72,202,228,0.08)",
  },
  zoomTxt: { color: "#48CAE4", fontSize: 12, fontWeight: "700" },
  btnRow: { flexDirection: "row", gap: 8, marginTop: 2 },
  btn: {
    flex: 1, minHeight: 44, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
  },
  btnGhost: { borderWidth: 1, borderColor: "rgba(255,255,255,0.18)" },
  btnGhostTxt: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  btnKeep: { backgroundColor: VARIANT_COLOR },
  btnOff: { opacity: 0.45 },
  btnKeepTxt: { color: "#04121F", fontSize: 12.5, fontWeight: "900" },
});
