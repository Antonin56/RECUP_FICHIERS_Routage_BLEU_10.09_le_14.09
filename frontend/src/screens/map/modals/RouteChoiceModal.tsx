// 22/07 — « Créer une route » : CHOIX auto / manuelle / enregistrées.
// (26/07 — « Mes routes enregistrées » déplacé dans le PROFIL.)
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

type Pt = { lat: number; lng: number };

interface Props {
  point: Pt | null;
  onAuto: (pt: Pt) => void;
  onManual: (pt: Pt) => void;
  onClose: () => void;
}

export function RouteChoiceModal({ point, onAuto, onManual, onClose }: Props) {
  return (
    <Modal visible={point != null} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <View style={styles.unitPickerHeader}>
            <Ionicons name="git-branch" size={18} color="#2EC4B6" />
            <Text style={styles.unitPickerTitle}>Créer une route</Text>
          </View>
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={() => {
              if (point) onAuto(point);
            }}
            testID="route-choice-auto"
          >
            <Ionicons name="flash" size={20} color={theme.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Route automatique</Text>
              <Text style={styles.unitPickerHint}>Calculée selon les fonds SHOM, le balisage et Mon bateau</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={() => {
              if (point) onManual(point);
            }}
            testID="route-choice-manual"
          >
            <Ionicons name="create" size={20} color="#2EC4B6" />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Route manuelle</Text>
              <Text style={styles.unitPickerHint}>Ce point = départ, puis appui long pour chaque étape</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
