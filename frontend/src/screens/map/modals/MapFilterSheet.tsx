// PHASE 4 — Bottom-sheet des FILTRES de la carte (types + faux signalements).
// Découpé de map.tsx le 26/08/2026 : déplacement PUR, aucun changement.
import {
  Modal, Pressable, ScrollView, Switch, Text, TouchableOpacity, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme, spacing } from "@/src/lib/theme";
import { REPORT_TYPES, type ReportTypeId } from "@/src/lib/report-types";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  selectedTypes: Set<ReportTypeId>;
  setSelectedTypes: (s: Set<ReportTypeId>) => void;
  toggleType: (id: ReportTypeId) => void;
  hideFakes: boolean;
  setHideFakes: (v: boolean) => void;
  onApply: () => void;
  onClose: () => void;
}

export function MapFilterSheet({
  visible, selectedTypes, setSelectedTypes, toggleType,
  hideFakes, setHideFakes, onApply, onClose,
}: Props) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.sheetBackdrop} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation?.()}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Affichage de la carte</Text>
            <TouchableOpacity onPress={onClose} testID="map-filter-close">
              <Ionicons name="close" size={22} color={theme.text} />
            </TouchableOpacity>
          </View>

          <View style={styles.sheetSectionRow}>
            <Text style={styles.sheetSection}>Types de signalements</Text>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <TouchableOpacity
                onPress={() => setSelectedTypes(new Set())}
                testID="map-filter-select-all"
              >
                <Text style={styles.sheetLink}>Tout afficher</Text>
              </TouchableOpacity>
              <Text style={styles.sheetLinkSep}>·</Text>
              <TouchableOpacity
                onPress={() => setSelectedTypes(new Set(REPORT_TYPES.map((t) => t.id)))}
                testID="map-filter-invert"
              >
                <Text style={styles.sheetLink}>Inverser</Text>
              </TouchableOpacity>
            </View>
          </View>

          <ScrollView style={{ maxHeight: 340 }} contentContainerStyle={{ paddingBottom: spacing.sm }}>
            {/* When the Set is empty we treat it as "all selected" for display purposes. */}
            {REPORT_TYPES.map((t) => {
              const isAll = selectedTypes.size === 0;
              const on = isAll || selectedTypes.has(t.id);
              return (
                <TouchableOpacity
                  key={t.id}
                  style={[styles.sheetRow, on && styles.sheetRowOn]}
                  onPress={() => {
                    // First explicit toggle when in "all" mode: keep ALL EXCEPT this one
                    // (= unselect t). This matches the natural mental model.
                    if (isAll) {
                      const next = new Set(REPORT_TYPES.map((x) => x.id));
                      next.delete(t.id);
                      setSelectedTypes(next);
                    } else {
                      toggleType(t.id);
                    }
                  }}
                  testID={`map-filter-type-${t.id}`}
                >
                  <View style={[styles.sheetDot, { backgroundColor: t.color }]}>
                    <Ionicons name={t.icon as never} size={16} color={theme.bg} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.sheetRowLabel}>{t.label}</Text>
                    <Text style={styles.sheetRowDesc}>{t.short}</Text>
                  </View>
                  <Ionicons
                    name={on ? "checkbox" : "square-outline"}
                    size={22}
                    color={on ? theme.primary : theme.textMute}
                  />
                </TouchableOpacity>
              );
            })}
          </ScrollView>

          <View style={styles.sheetDivider} />

          <Text style={styles.sheetSection}>Préférences d&apos;affichage</Text>
          <View style={styles.sheetTogglesRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.sheetRowLabel}>Masquer les faux signalements</Text>
              <Text style={styles.sheetRowDesc}>
                Cache les points marqués comme faux par la communauté.
              </Text>
            </View>
            <Switch
              value={hideFakes}
              onValueChange={setHideFakes}
              trackColor={{ false: theme.border, true: theme.primary }}
              thumbColor={hideFakes ? theme.bg : theme.textDim}
              testID="map-hide-fakes-toggle"
            />
          </View>

          <TouchableOpacity style={styles.sheetApply} onPress={onApply} testID="map-filter-apply">
            <Text style={styles.sheetApplyText}>Appliquer</Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
