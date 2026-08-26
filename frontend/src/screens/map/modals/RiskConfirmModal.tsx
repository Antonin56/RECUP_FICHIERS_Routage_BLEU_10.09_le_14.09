// 24/07 — acceptation du risque avant de suivre une route douteuse.
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity } from "react-native";

import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  onAccept: () => void;
  onClose: () => void;
}

export function RiskConfirmModal({ visible, onAccept, onClose }: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <Text style={styles.riskTitle}>⚠ Route avec passage compromis</Text>
          <Text style={styles.riskMsg}>
            Le ou les tronçons EN ROUGE ne sont pas vérifiés : fond
            insuffisant, obstacle ou terre possibles. En suivant cette
            route, vous acceptez ce risque et naviguez sous votre seule
            responsabilité.
          </Text>
          <TouchableOpacity
            style={styles.riskAcceptBtn}
            onPress={onAccept}
            testID="risk-accept"
          >
            <Text style={styles.riskAcceptTxt}>{"J'accepte le risque — suivre la route"}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.riskCancelBtn}
            onPress={onClose}
            testID="risk-cancel"
          >
            <Text style={styles.riskCancelTxt}>Annuler</Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
