// Popup « Zone de veille » (bouton cloche+engrenage) — réglages rapides
// uniquement : zones Vigie/Nav + types de notification + accès à la page
// complète des paramètres.
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, ScrollView, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AlertSettingsPanel } from "@/src/components/AlertSettingsPanel";
import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  bottomInset: number;
  onClose: () => void;
  onOpenFullSettings: () => void;
}

export function AlertSettingsModal({ visible, bottomInset, onClose, onOpenFullSettings }: Props) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.alertSheetBackdrop} onPress={onClose}>
        <Pressable style={styles.alertSheet} onPress={() => {}}>
          <View style={styles.alertSheetHandle} />
          <View style={styles.alertSheetHeader}>
            <Ionicons name="notifications" size={18} color="#F4A261" />
            <Text style={styles.alertSheetTitle}>Zone de veille</Text>
            <TouchableOpacity
              onPress={onClose}
              style={styles.alertSheetClose}
              testID="alert-settings-close"
            >
              <Ionicons name="close" size={22} color={theme.textMute} />
            </TouchableOpacity>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: bottomInset + 16 }}>
            <AlertSettingsPanel variant="quick" onOpenFullSettings={onOpenFullSettings} />
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
