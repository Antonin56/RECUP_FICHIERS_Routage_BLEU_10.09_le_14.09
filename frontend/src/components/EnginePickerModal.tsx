/**
 * SignalMar — Sélecteur de moteur pour le recalcul A/B (02/08/2026).
 *
 * Demande armateur : « au clic tu ouvres en liste déroulante les moteurs
 * dispos triés par ID décroissants, je choisis un moteur et tu relances le
 * calcul ». Le moteur qui a produit la route affichée est signalé et non
 * sélectionnable (il sert de RÉFÉRENCE dans la comparaison).
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text,
  TouchableOpacity, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api, type RoutingEngine } from "@/src/api/client";
import { radii, spacing, theme } from "@/src/lib/theme";

export function EnginePickerModal(props: {
  visible: boolean;
  /** Moteur de la route affichée (référence) — non sélectionnable. */
  baseEngineId?: string | null;
  baseEngineName?: string | null;
  busy?: boolean;
  onPick: (engine: RoutingEngine) => void;
  onClose: () => void;
}) {
  const { visible, baseEngineId, baseEngineName, busy, onPick, onClose } = props;
  const [engines, setEngines] = useState<RoutingEngine[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await api.listRoutingEngines();
      // Tri par ID DÉCROISSANT (consigne armateur) : le dernier moteur créé
      // (engine_c, engine_b…) arrive en tête de liste.
      setEngines([...r.engines].sort((a, b) => b.id.localeCompare(a.id)));
    } catch (e) {
      setErr((e as Error).message || "Chargement des moteurs impossible.");
      setEngines([]);
    }
  }, []);

  useEffect(() => {
    if (visible) void load();
  }, [visible, load]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={busy ? undefined : onClose}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          <View style={styles.head}>
            <Ionicons name="git-compare-outline" size={18} color="#48CAE4" />
            <Text style={styles.title}>Recalculer avec un autre moteur</Text>
            <TouchableOpacity onPress={onClose} hitSlop={10} disabled={busy} testID="engine-picker-close">
              <Ionicons name="close" size={20} color={theme.textMute} />
            </TouchableOpacity>
          </View>
          <Text style={styles.sub}>
            {baseEngineName
              ? `Route actuelle : ${baseEngineName}${baseEngineId ? ` · ${baseEngineId}` : ""}. `
              : ""}
            Choisissez le moteur à comparer — les deux tracés seront superposés
            et les écarts surlignés.
          </Text>

          {engines == null ? (
            <View style={styles.loading}>
              <ActivityIndicator size="small" color={theme.accent} />
              <Text style={styles.loadingTxt}>Chargement des moteurs…</Text>
            </View>
          ) : err ? (
            <Text style={styles.err}>{err}</Text>
          ) : (
            <ScrollView style={{ maxHeight: 300 }} contentContainerStyle={{ gap: 8 }}>
              {engines.map((e) => {
                const isBase = !!baseEngineId && e.id === baseEngineId;
                return (
                  <TouchableOpacity
                    key={e.id}
                    style={[styles.row, isBase && styles.rowOff]}
                    onPress={() => (isBase || busy ? undefined : onPick(e))}
                    disabled={isBase || !!busy}
                    activeOpacity={0.8}
                    testID={`engine-pick-${e.id}`}
                  >
                    <Ionicons
                      name={isBase ? "radio-button-on" : "swap-horizontal"}
                      size={16}
                      color={isBase ? theme.textMute : "#FFB703"}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowName} numberOfLines={1}>
                        {e.name}
                        {isBase ? " (route actuelle)" : ""}
                      </Text>
                      <Text style={styles.rowMeta} numberOfLines={1}>
                        ID : {e.id} · {e.algo}
                      </Text>
                    </View>
                    {busy ? null : (
                      <Ionicons name="chevron-forward" size={16} color={theme.textMute} />
                    )}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          )}
          {busy ? (
            <View style={styles.loading}>
              <ActivityIndicator size="small" color="#FFB703" />
              <Text style={styles.loadingTxt}>Recalcul en cours…</Text>
            </View>
          ) : null}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(4,10,20,0.72)",
    alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  sheet: {
    width: "100%", maxWidth: 460, backgroundColor: "#0B132B",
    borderRadius: radii.lg, borderWidth: 1, borderColor: theme.border,
    padding: spacing.md, gap: spacing.sm,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { flex: 1, color: theme.text, fontSize: 15, fontWeight: "800" },
  sub: { color: theme.textDim, fontSize: 11.5, lineHeight: 16 },
  loading: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8 },
  loadingTxt: { color: theme.textDim, fontSize: 12 },
  err: { color: "#E5383B", fontSize: 12 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 12,
    backgroundColor: "rgba(255,255,255,0.05)", borderRadius: radii.md,
    borderWidth: 1, borderColor: "rgba(255,255,255,0.08)",
    minHeight: 48,
  },
  rowOff: { opacity: 0.5 },
  rowName: { color: theme.text, fontSize: 13.5, fontWeight: "700" },
  rowMeta: { color: theme.textDim, fontSize: 10.5, marginTop: 2 },
});
