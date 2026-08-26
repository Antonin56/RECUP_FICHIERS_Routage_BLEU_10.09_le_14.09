// Popup bathymétrie SHOM (appui long sur la goutte d'eau) — réglage
// d'opacité de la surcouche (19/07/2026).
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  opacity: number;
  onChangeOpacity: (v: number) => void;
  onClose: () => void;
}

export function BathyOpacityModal({ visible, opacity, onChangeOpacity, onClose }: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <View style={styles.unitPickerHeader}>
            <Ionicons name="water" size={18} color="#48CAE4" />
            <Text style={styles.unitPickerTitle}>Bathymétrie SHOM — opacité</Text>
          </View>
          {/* 22/07/2026 (bug tablette : le curseur ne répondait pas dans la
              popup) → CHIPS d'opacité fiables, aperçu TEMPS RÉEL (chaque tap
              est poussé dans la WebView via bathymetryOpacity). */}
          <View style={styles.bathySliderHead}>
            <Text style={styles.bathySliderLabel}>Opacité</Text>
            <Text style={styles.bathySliderValue} testID="bathy-opacity-value">
              {Math.round(opacity * 100)} %
            </Text>
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
            {[0.3, 0.5, 0.7, 0.85, 1].map((v) => {
              const active = Math.abs(opacity - v) < 0.01;
              return (
                <TouchableOpacity
                  key={v}
                  style={[styles.chip, active && { backgroundColor: "#48CAE4", borderColor: "#48CAE4" }]}
                  onPress={() => {
                    onChangeOpacity(v);
                    Haptics.selectionAsync().catch(() => {});
                  }}
                  testID={`bathy-opacity-${Math.round(v * 100)}`}
                >
                  <Text style={[styles.chipText, active && { color: "#0B132B" }]}>
                    {Math.round(v * 100)} %
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
          <Text style={styles.unitPickerHint}>
            Profondeurs SHOM (open data) — indicatif, pas pour la navigation officielle.
          </Text>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
