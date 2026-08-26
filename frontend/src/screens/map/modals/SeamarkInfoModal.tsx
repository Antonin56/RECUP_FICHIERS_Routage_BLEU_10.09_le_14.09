// 22/07 — fiche BALISE (tap sur un seamark de la carte).
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import type { Seamark } from "@/src/api/client";
import { formatDM } from "@/src/lib/coords";
import {
  SEAMARK_CAT_LABEL, SEAMARK_KIND_LABEL, WATER_LEVEL_LABEL,
} from "@/src/screens/map/map-constants";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  seamark: Seamark | null;
  onClose: () => void;
}

export function SeamarkInfoModal({ seamark, onClose }: Props) {
  return (
    <Modal visible={seamark != null} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          {seamark ? (
            <>
              <View style={styles.unitPickerHeader}>
                <Ionicons name="location" size={18} color="#F4A261" />
                <Text style={styles.unitPickerTitle}>
                  {SEAMARK_KIND_LABEL[seamark.kind] || "Balise"}
                  {seamark.name ? ` — ${seamark.name}` : ""}
                </Text>
              </View>
              {seamark.category && SEAMARK_CAT_LABEL[seamark.category] ? (
                <Text style={styles.longPressLabel}>{SEAMARK_CAT_LABEL[seamark.category]}</Text>
              ) : null}
              {seamark.water_level && WATER_LEVEL_LABEL[seamark.water_level] ? (
                <Text style={styles.longPressLabel}>{WATER_LEVEL_LABEL[seamark.water_level]}</Text>
              ) : null}
              {seamark.kind === "rock" || seamark.kind === "wreck" || seamark.kind === "obstruction" ? (
                <Text style={[styles.unitPickerHint, { color: "#E5383B", fontWeight: "800" }]}>
                  ⚠ Danger — {typeof seamark.depth_m === "number"
                    ? `profondeur ${seamark.depth_m.toFixed(1)} m`
                    : "profondeur inconnue"}. La route automatique l{"'"}évite.
                </Text>
              ) : null}
              {seamark.colour ? (
                <Text style={styles.unitPickerHint}>Couleur : {seamark.colour.replace(/;/g, " / ")}</Text>
              ) : null}
              {seamark.light ? (
                <Text style={styles.unitPickerHint}>Feu : {seamark.light}</Text>
              ) : null}
              <Text style={styles.longPressCoords}>{formatDM(seamark.lat, seamark.lng)}</Text>
              <Text style={styles.unitPickerHint}>
                Source : OpenSeaMap (contributif) — vérifiez avec les documents officiels.
              </Text>
            </>
          ) : null}
        </Pressable>
      </Pressable>
    </Modal>
  );
}
