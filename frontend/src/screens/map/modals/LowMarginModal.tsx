// Popup « Route à faible marge de sécurité » (règle 150 %) + recherche
// automatique d'une route plus sûre (27/07, vidéo 15h45).
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { ActivityIndicator, Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import type { ComputedRoute } from "@/src/api/client";
import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  lowMargin: ComputedRoute["low_margin"] | null;
  saferBusy: boolean;
  saferReady: boolean;
  saferFail: string | null;
  onCompareSafer: () => void;
  onKeep: () => void;
  onClose: () => void;
}

export function LowMarginModal(
  { visible, lowMargin, saferBusy, saferReady, saferFail, onCompareSafer, onKeep, onClose }: Props,
) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <Text style={styles.riskTitle}>⚠ Route à faible marge de sécurité</Text>
          {lowMargin ? (
            <Text style={styles.riskMsg}>
              Hauteur d&apos;eau minimale sur ce trajet :{" "}
              <Text style={{ fontWeight: "900", color: "#FF6B6B" }}>
                {lowMargin.min_height_m.toFixed(1).replace(".", ",")} m
              </Text>
              , pour un besoin de {lowMargin.required_m.toFixed(1).replace(".", ",")} m
              (tirant d&apos;eau + marge de fond).{"\n"}
              C&apos;est moins de 150 % de votre besoin
              ({lowMargin.alert_at_m.toFixed(1).replace(".", ",")} m) :
              une imprécision de carte ou de marée peut suffire à talonner.
            </Text>
          ) : null}
          {/* 27/07 (vidéo 15h45, « bon sens ») — la recherche d'une route
              plus sûre est AUTOMATIQUE : le bouton « Comparer » n'apparaît
              que si une alternative existe ; sinon message d'échec. */}
          {saferBusy ? (
            <View style={styles.lowMarginSafeBtn}>
              <ActivityIndicator size="small" color={theme.bg} />
              <Text style={styles.lowMarginSafeTxt}>Recherche d&apos;une route plus sûre…</Text>
            </View>
          ) : saferReady ? (
            <TouchableOpacity
              style={styles.lowMarginSafeBtn}
              onPress={onCompareSafer}
              testID="low-margin-safer"
            >
              <Ionicons name="shield-checkmark" size={18} color={theme.bg} />
              <Text style={styles.lowMarginSafeTxt}>
                Comparer avec la route plus sûre trouvée (+2 m)
              </Text>
            </TouchableOpacity>
          ) : null}
          {saferFail ? (
            <Text style={styles.saferFailTxt} testID="safer-fail-msg">
              ⚠ {saferFail}
            </Text>
          ) : null}
          <TouchableOpacity
            style={styles.riskAcceptBtn}
            onPress={onKeep}
            testID="low-margin-keep"
          >
            <Text style={styles.riskAcceptTxt}>{"Garder cette route — j'accepte le risque"}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.riskCancelBtn}
            onPress={onClose}
            testID="low-margin-later"
          >
            <Text style={styles.riskCancelTxt}>Décider plus tard</Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
