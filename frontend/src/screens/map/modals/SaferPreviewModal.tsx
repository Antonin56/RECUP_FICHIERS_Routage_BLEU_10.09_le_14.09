// 26/07 — APERÇU COMPARATIF : route actuelle vs route plus sûre (+2 m).
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import type { ComputedRoute } from "@/src/api/client";
import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  route: ComputedRoute | null;
  safer: ComputedRoute | null;
  cruiseKn: number;
  onAdopt: () => void;
  onKeepCurrent: () => void;
  onClose: () => void;
}

export function SaferPreviewModal(
  { route, safer, cruiseKn, onAdopt, onKeepCurrent, onClose }: Props,
) {
  return (
    <Modal visible={safer != null} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <Text style={styles.riskTitle}>Comparer les deux routes</Text>
          {route && safer ? (() => {
            const fD = (m: number) => `${(m / 1000).toFixed(1).replace(".", ",")} km`;
            const fT = (m: number) => {
              const min = Math.round((m / 1852 / Math.max(cruiseKn, 0.1)) * 60);
              return min < 60 ? `${min} min` : `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`;
            };
            const fB = (v?: number | null) => (v == null ? "—" : `${v.toFixed(1).replace(".", ",")} m`);
            return (
              <View style={styles.cmpTable}>
                <View style={styles.cmpRow}>
                  <Text style={styles.cmpLbl} />
                  <Text style={styles.cmpHead}>Actuelle</Text>
                  <Text style={[styles.cmpHead, { color: "#2EC4B6" }]}>Plus sûre (+2 m)</Text>
                </View>
                <View style={styles.cmpRow}>
                  <Text style={styles.cmpLbl}>Distance</Text>
                  <Text style={styles.cmpVal}>{fD(route.distance_m)}</Text>
                  <Text style={[styles.cmpVal, { color: "#2EC4B6" }]}>{fD(safer.distance_m)}</Text>
                </View>
                <View style={styles.cmpRow}>
                  <Text style={styles.cmpLbl}>Durée ({cruiseKn.toFixed(0)} nd)</Text>
                  <Text style={styles.cmpVal}>{fT(route.distance_m)}</Text>
                  <Text style={[styles.cmpVal, { color: "#2EC4B6" }]}>{fT(safer.distance_m)}</Text>
                </View>
                <View style={styles.cmpRow}>
                  <Text style={styles.cmpLbl}>Fond min (carte)</Text>
                  <Text style={[styles.cmpVal, { color: "#FF6B6B" }]}>{fB(route.min_depth_m)}</Text>
                  <Text style={[styles.cmpVal, { color: "#2EC4B6" }]}>{fB(safer.min_depth_m)}</Text>
                </View>
              </View>
            );
          })() : null}
          <TouchableOpacity
            style={styles.lowMarginSafeBtn}
            onPress={onAdopt}
            testID="safer-adopt"
          >
            <Ionicons name="shield-checkmark" size={18} color={theme.bg} />
            <Text style={styles.lowMarginSafeTxt}>Adopter la route plus sûre</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.riskAcceptBtn}
            onPress={onKeepCurrent}
            testID="safer-keep-current"
          >
            <Text style={styles.riskAcceptTxt}>{"Garder l'actuelle — j'accepte le risque"}</Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
