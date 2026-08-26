// Menu appui long (N0, 20/07/2026) — « Signaler ici » / « Naviguer ici » /
// « Créer une route ».
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/lib/theme";
import { formatDM } from "@/src/lib/coords";
import { styles } from "@/src/screens/map/map-styles";

type Pt = { lat: number; lng: number };

interface Props {
  point: Pt | null;
  /** 26/07 — anti-fermeture fantôme : timestamp d'ouverture du menu. */
  openedAt: () => number;
  onClose: () => void;
  onReport: (pt: Pt) => void;
  onNavigate: (pt: Pt) => void;
  onCreateRoute: (pt: Pt) => void;
}

export function LongPressMenuModal(
  { point, openedAt, onClose, onReport, onNavigate, onCreateRoute }: Props,
) {
  return (
    <Modal visible={point != null} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable
        style={styles.unitPickerBackdrop}
        onPress={() => {
          // 26/07 — anti-fermeture fantôme : le relâché d'un appui long
          // maintenu ne doit pas fermer le menu qui vient de s'ouvrir.
          if (Date.now() - openedAt() < 700) return;
          onClose();
        }}
      >
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <View style={styles.unitPickerHeader}>
            <Ionicons name="location" size={18} color={theme.primary} />
            <Text style={styles.unitPickerTitle}>Position choisie</Text>
          </View>
          {point ? (
            <Text style={styles.longPressCoords}>
              {formatDM(point.lat, point.lng)}
            </Text>
          ) : null}
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={() => {
              if (point) onReport(point);
            }}
            testID="longpress-report"
          >
            <Ionicons name="alert-circle" size={20} color="#F4A261" />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Signaler ici</Text>
              <Text style={styles.unitPickerHint}>Créer un signalement à cette position</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={() => {
              if (point) onNavigate(point);
            }}
            testID="longpress-navigate"
          >
            <Ionicons name="navigate" size={20} color={theme.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Naviguer ici</Text>
              <Text style={styles.unitPickerHint}>Depuis la position du bateau — selon Mon bateau</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={() => {
              // 22/07 — choix du TYPE de route (auto / manuelle /
              // enregistrées) avant de continuer.
              if (point) onCreateRoute(point);
            }}
            testID="longpress-create-route"
          >
            <Ionicons name="git-branch" size={20} color="#2EC4B6" />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Créer une route</Text>
              <Text style={styles.unitPickerHint}>Automatique, manuelle ou enregistrée</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
