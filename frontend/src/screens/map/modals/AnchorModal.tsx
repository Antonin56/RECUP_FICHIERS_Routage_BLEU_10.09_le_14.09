// 23/07/2026 — ALARME DE MOUILLAGE (bouton ancre) : pose/levée + rayon de
// garde (aussi réglable dans Réglages → Alarme de mouillage).
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { GestureHandlerRootView } from "react-native-gesture-handler";

import { AnchorPanel } from "@/src/components/AnchorPanel";
import type { AnchorPos } from "@/src/lib/anchor";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  anchor: AnchorPos | null;
  anchorDriftM: number | null;
  radiusM: number;
  onChangeRadius: (m: number) => void;
  canDrop: boolean;
  onDrop: () => void;
  onLift: () => void;
  onClose: () => void;
}

export function AnchorModal(
  { visible, anchor, anchorDriftM, radiusM, onChangeRadius, canDrop, onDrop, onLift, onClose }: Props,
) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      {/* 23/07 (bug armateur « curseur mort dans la popup ») — les Modal
          Android vivent dans une AUTRE fenêtre native : sans
          GestureHandlerRootView local, le MarineSlider (Gesture.Pan) ne
          reçoit AUCUN geste. + backdrop en FRÈRE absolu (plus de Pressable
          ANCÊTRE qui capture le glissement du doigt). */}
      <GestureHandlerRootView style={{ flex: 1 }}>
        <View style={styles.unitPickerBackdrop}>
          <Pressable
            style={styles.modalBackdropFill}
            onPress={onClose}
            testID="anchor-modal-backdrop"
          />
          <View style={styles.unitPickerSheet}>
            <View style={styles.unitPickerHeader}>
              <MaterialCommunityIcons name="anchor" size={18} color="#2EC4B6" />
              <Text style={styles.unitPickerTitle}>Alarme de mouillage</Text>
            </View>
            {anchor ? (
              <View style={styles.anchorStatusRow}>
                <Ionicons name="time" size={16} color="#2EC4B6" />
                <Text style={styles.anchorStatusTxt}>
                  À l&apos;ancre depuis{" "}
                  {new Date(anchor.since).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                  {anchorDriftM != null ? ` · dérive actuelle ${Math.round(anchorDriftM)} m` : ""}
                </Text>
              </View>
            ) : null}
            <AnchorPanel radiusM={radiusM} onChangeRadius={onChangeRadius} />
            {anchor ? (
              <TouchableOpacity
                style={[styles.anchorActionBtn, { backgroundColor: "#E5383B" }]}
                onPress={onLift}
                testID="anchor-lift"
              >
                <MaterialCommunityIcons name="anchor" size={18} color="#fff" />
                <Text style={[styles.anchorActionTxt, { color: "#fff" }]}>Lever l&apos;ancre</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={[styles.anchorActionBtn, { backgroundColor: "#2EC4B6" }, !canDrop && { opacity: 0.5 }]}
                onPress={onDrop}
                disabled={!canDrop}
                testID="anchor-drop"
              >
                <MaterialCommunityIcons name="anchor" size={18} color="#04121F" />
                <Text style={styles.anchorActionTxt}>Mouiller ici (position du bateau)</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}
