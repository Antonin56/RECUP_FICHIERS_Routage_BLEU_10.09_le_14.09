/**
 * SignalMar — Réglages « Alarme de mouillage » (22/07/2026, GO armateur).
 * Rayon de garde 5-100 m (défaut 15 m). L'ancre se pose depuis la carte
 * (bouton ancre) à la position du bateau ; si le bateau dérive au-delà du
 * rayon → son dédié + vibration + bannière.
 */
import { StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { MarineSlider } from "@/src/components/MarineSlider";
import {
  ANCHOR_RADIUS_MAX_M,
  ANCHOR_RADIUS_MIN_M,
  useAnchorRadius,
} from "@/src/lib/anchor";
import { spacing, theme } from "@/src/lib/theme";

export function AnchorPanel(props: {
  /** Mode CONTRÔLÉ (popup de la carte) : valeur + remontée au parent.
   *  Sans props → mode autonome (page Réglages), persistance interne. */
  radiusM?: number;
  onChangeRadius?: (v: number) => void;
} = {}) {
  const internal = useAnchorRadius();
  const radiusM = props.radiusM ?? internal.radiusM;
  const setRadiusM = (v: number) => {
    internal.setRadiusM(v); // persiste TOUJOURS (source de vérité storage)
    props.onChangeRadius?.(v);
  };

  return (
    <View style={{ gap: spacing.sm }}>
      <View style={styles.row}>
        <Ionicons name="lock-closed" size={18} color={theme.primary} />
        <Text style={styles.hint}>
          À l&apos;ancre, touchez le bouton ANCRE de la carte : la position est
          mémorisée et surveillée. Si le bateau dérive au-delà du rayon de
          garde → alarme sonore dédiée + vibration. L&apos;app doit rester
          ouverte pendant la surveillance.
        </Text>
      </View>
      <View style={styles.head}>
        <Text style={styles.label}>Rayon de garde</Text>
        <Text style={styles.value} testID="anchor-radius-value">{radiusM} m</Text>
      </View>
      <MarineSlider
        value={radiusM}
        minimumValue={ANCHOR_RADIUS_MIN_M}
        maximumValue={ANCHOR_RADIUS_MAX_M}
        step={5}
        onValueChange={setRadiusM}
        testID="anchor-radius-slider"
      />
      <View style={styles.bounds}>
        <Text style={styles.boundTxt}>{ANCHOR_RADIUS_MIN_M} m</Text>
        <Text style={styles.boundTxt}>{ANCHOR_RADIUS_MAX_M} m</Text>
      </View>
      <Text style={styles.hint}>
        Comptez la longueur de mouillage filée + la longueur du bateau + une
        marge GPS (~10 m).
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  label: { color: theme.text, fontSize: 14, fontWeight: "700" },
  hint: { color: theme.textDim, fontSize: 11, lineHeight: 15, flex: 1 },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  value: { color: theme.primary, fontSize: 15, fontWeight: "900" },
  bounds: { flexDirection: "row", justifyContent: "space-between", marginTop: -4 },
  boundTxt: { color: theme.textMute, fontSize: 10, fontWeight: "700" },
});
