// 21/07 — menu du tracé (tap sur la route) : suivre / détails / actualiser /
// comparer / enregistrer / supprimer. 26/08 — bandeau « faible hauteur
// d'eau » quand le tap vient d'une ZONE ROUGE (RouteTapDanger).
// Découpé de map.tsx le 27/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import type { RouteTapDanger } from "@/src/components/MarineMap";
import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  danger: RouteTapDanger | null;
  /** true si la route est AUTO et son contexte connu (bouton Actualiser). */
  canRefresh: boolean;
  onFollow: () => void;
  onDetails: () => void;
  onRefresh: () => void;
  onCompare: () => void;
  onSave: () => void;
  onDelete: () => void;
  onClose: () => void;
}

export function RouteMenuModal(
  { visible, danger, canRefresh, onFollow, onDetails, onRefresh, onCompare, onSave, onDelete, onClose }: Props,
) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.unitPickerBackdrop} onPress={onClose}>
        <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
          <View style={styles.unitPickerHeader}>
            <Ionicons name="navigate" size={18} color="#E5383B" />
            <Text style={styles.unitPickerTitle}>Route sûre</Text>
          </View>
          {/* 26/08/2026 (demande armateur) — tap sur une ZONE ROUGE :
              bandeau « faible hauteur d'eau » AVANT les options. */}
          {danger ? (
            <View style={styles.routeDangerBanner} testID="route-menu-danger">
              <Ionicons name="warning" size={20} color="#FF1744" />
              <View style={{ flex: 1 }}>
                <Text style={styles.routeDangerTitle}>
                  {danger.reason === "low_margin"
                    ? "Passage étroit ici"
                    : "Hauteur d'eau insuffisante ici"}
                </Text>
                <Text style={styles.routeDangerText}>
                  {danger.reason === "low_margin"
                    ? "Marge latérale < 20 m sur ce tronçon — passage à vue recommandé."
                    : danger.min_depth_m != null
                      ? `Fond mini ~${danger.min_depth_m.toFixed(1).replace(".", ",")} m${
                          danger.threshold_m != null
                            ? ` pour un besoin de ${danger.threshold_m.toFixed(1).replace(".", ",")} m`
                            : ""}. Zone peu profonde ou découverte selon la marée.`
                      : "Zone peu profonde ou découverte selon la marée."}
                </Text>
              </View>
            </View>
          ) : null}
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={onFollow}
            testID="route-menu-follow"
          >
            <Ionicons name="play" size={20} color="#2EC4B6" />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Suivre la route</Text>
              <Text style={styles.unitPickerHint}>Cap à suivre, ETA — waypoints grisés au passage</Text>
            </View>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={onDetails}
            testID="route-menu-details"
          >
            <Ionicons name="information-circle" size={20} color={theme.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Voir les détails</Text>
              <Text style={styles.unitPickerHint}>Distance, profil de profondeur, alertes</Text>
            </View>
          </TouchableOpacity>
          {/* 26/07 (décision armateur) — recalcul avec la marée de MAINTENANT :
              l'utilisateur re-vérifie les hauteurs d'eau avant un passage. */}
          {canRefresh ? (
            <TouchableOpacity
              style={styles.longPressRow}
              onPress={onRefresh}
              testID="route-menu-refresh"
            >
              <Ionicons name="refresh" size={20} color="#48CAE4" />
              <View style={{ flex: 1 }}>
                <Text style={styles.longPressLabel}>Actualiser la route</Text>
                <Text style={styles.unitPickerHint}>Recalcule avec la hauteur de marée de maintenant</Text>
              </View>
            </TouchableOpacity>
          ) : null}
          {/* 02/08/2026 (demande armateur) — A/B TESTING : recalculer cette
              route avec un AUTRE moteur et comparer les deux tracés. */}
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={onCompare}
            testID="route-menu-compare"
          >
            <Ionicons name="git-compare" size={20} color="#FFB703" />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Recalculer avec un autre moteur</Text>
              <Text style={styles.unitPickerHint}>
                Compare les deux tracés sur la carte (écarts surlignés)
              </Text>
            </View>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={onSave}
            testID="route-menu-save"
          >
            <Ionicons name="bookmark" size={20} color="#2EC4B6" />
            <View style={{ flex: 1 }}>
              <Text style={styles.longPressLabel}>Enregistrer la route</Text>
              <Text style={styles.unitPickerHint}>Jusqu’à 20 routes — retrouvables via « Créer une route »</Text>
            </View>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.longPressRow}
            onPress={onDelete}
            testID="route-menu-delete"
          >
            <Ionicons name="trash" size={20} color="#E5383B" />
            <View style={{ flex: 1 }}>
              <Text style={[styles.longPressLabel, { color: "#E5383B" }]}>Supprimer la route</Text>
              <Text style={styles.unitPickerHint}>Efface le tracé de la carte</Text>
            </View>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
