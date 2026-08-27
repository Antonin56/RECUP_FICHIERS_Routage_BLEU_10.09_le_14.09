// Modale de recherche d'un signalement par ID COURT (loupe, 12/07/2026).
// Découpé de map.tsx le 26/08/2026 : déplacement PUR, aucun changement.
import {
  ActivityIndicator, Modal, Pressable, Text, TextInput, TouchableOpacity, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  code: string;
  err: string | null;
  busy: boolean;
  onChangeCode: (v: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}

export function SearchByCodeModal({ visible, code, err, busy, onChangeCode, onSubmit, onClose }: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.searchBackdrop} onPress={onClose}>
        <Pressable style={styles.searchSheet} onPress={() => {}}>
          <View style={styles.searchTitleRow}>
            <Ionicons name="search" size={18} color={theme.primary} />
            <Text style={styles.searchTitle}>Rechercher un signalement</Text>
          </View>
          <Text style={styles.searchHint}>
            Entrez le code affiché sur un post partagé (ex. K7M2PQ4X).
          </Text>
          <TextInput
            style={styles.searchInput}
            value={code}
            onChangeText={onChangeCode}
            placeholder="CODE DU SIGNALEMENT"
            placeholderTextColor={theme.textDim}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={12}
            autoFocus
            returnKeyType="search"
            onSubmitEditing={onSubmit}
            testID="map-search-input"
          />
          {err ? <Text style={styles.searchErr}>{err}</Text> : null}
          <TouchableOpacity
            style={[styles.searchBtn, (busy || code.trim().length < 4) && { opacity: 0.5 }]}
            onPress={onSubmit}
            disabled={busy || code.trim().length < 4}
            testID="map-search-submit"
          >
            {busy ? (
              <ActivityIndicator color={theme.bg} />
            ) : (
              <>
                <Ionicons name="search" size={18} color={theme.bg} />
                <Text style={styles.searchBtnTxt}>Rechercher</Text>
              </>
            )}
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
