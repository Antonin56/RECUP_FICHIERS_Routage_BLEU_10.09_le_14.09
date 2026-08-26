// 22/07 — nom de la route à ENREGISTRER (max 20 / compte).
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { ActivityIndicator, Modal, Pressable, Text, TextInput, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  name: string;
  saving: boolean;
  onChangeName: (v: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}

export function SaveRouteNameModal(
  { visible, name, saving, onChangeName, onSubmit, onClose }: Props,
) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.searchBackdrop} onPress={onClose}>
        <Pressable style={styles.searchSheet} onPress={() => {}}>
          <View style={styles.searchTitleRow}>
            <Ionicons name="bookmark" size={18} color="#2EC4B6" />
            <Text style={styles.searchTitle}>Enregistrer la route</Text>
          </View>
          <Text style={styles.searchHint}>
            Donnez un nom à cette route (20 routes max par compte). Le partage à vos contacts arrivera plus tard.
          </Text>
          <TextInput
            style={styles.searchInput}
            value={name}
            onChangeText={onChangeName}
            placeholder="Ex. Arradon → Houat"
            placeholderTextColor={theme.textDim}
            maxLength={40}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={onSubmit}
            testID="route-save-name-input"
          />
          <TouchableOpacity
            style={[styles.searchBtn, (saving || !name.trim()) && { opacity: 0.5 }]}
            onPress={onSubmit}
            disabled={saving || !name.trim()}
            testID="route-save-submit"
          >
            {saving ? (
              <ActivityIndicator color={theme.bg} />
            ) : (
              <>
                <Ionicons name="bookmark" size={18} color={theme.bg} />
                <Text style={styles.searchBtnTxt}>Enregistrer</Text>
              </>
            )}
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onClose}
            style={{ alignSelf: "center", padding: 8 }}
            testID="route-save-later"
          >
            <Text style={{ color: theme.textMute, fontSize: 12, fontWeight: "700" }}>
              Plus tard — touchez le tracé pour l’enregistrer
            </Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
