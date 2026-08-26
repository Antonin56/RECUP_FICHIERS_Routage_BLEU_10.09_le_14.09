// Popup unité d'échelle km/NM (tap sur une règle) — 16/07/2026.
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  mapUnit: "km" | "nm";
  onPick: (unit: "km" | "nm") => void;
  onClose: () => void;
}

export function UnitPickerModal({ visible, mapUnit, onPick, onClose }: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <View style={styles.unitPickerHeader}>
            <Ionicons name="settings-outline" size={18} color={theme.primary} />
            <Text style={styles.unitPickerTitle}>Unité des échelles</Text>
          </View>
          <TouchableOpacity
            style={[styles.unitPickerRow, mapUnit === "km" && styles.unitPickerRowActive]}
            onPress={() => onPick("km")}
            testID="unit-picker-km"
          >
            <Ionicons
              name={mapUnit === "km" ? "radio-button-on" : "radio-button-off"}
              size={20}
              color={mapUnit === "km" ? theme.primary : theme.textDim}
            />
            <View style={{ flex: 1 }}>
              <Text style={styles.unitPickerLabel}>Kilomètres</Text>
              <Text style={styles.unitPickerHint}>Distances routières / usage général</Text>
            </View>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.unitPickerRow, mapUnit === "nm" && styles.unitPickerRowActive]}
            onPress={() => onPick("nm")}
            testID="unit-picker-nm"
          >
            <Ionicons
              name={mapUnit === "nm" ? "radio-button-on" : "radio-button-off"}
              size={20}
              color={mapUnit === "nm" ? theme.primary : theme.textDim}
            />
            <View style={{ flex: 1 }}>
              <Text style={styles.unitPickerLabel}>Milles nautiques (NM)</Text>
              <Text style={styles.unitPickerHint}>1 NM = 1 852 m — usage marin</Text>
            </View>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
