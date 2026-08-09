// SignalMar — Rangée « Pseudo » + modal d'édition.
// Déplacée de l'onglet Profil vers la page Réglages (11/07/2026) : sur le
// profil, le clic sur le pseudo ouvre désormais la page Abonnement.

import { useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { radii, spacing, theme } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";

export function PseudoEditRow() {
  const { user, setUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const pseudo = user?.pseudo || user?.name || "Marin";

  async function save() {
    const next = draft.trim();
    if (next.length < 3) {
      showToast("error", "Pseudo trop court (min. 3 caractères)");
      return;
    }
    if (next === pseudo.trim()) {
      setOpen(false);
      return;
    }
    setSaving(true);
    try {
      const updated = await api.updateMe({ pseudo: next });
      setUser(updated);
      setOpen(false);
      showToast("success", "Pseudo mis à jour");
    } catch (e) {
      showToast("error", (e as Error).message || "Échec de la mise à jour");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <TouchableOpacity
        style={styles.row}
        onPress={() => { setDraft(user?.pseudo || user?.name || ""); setOpen(true); }}
        activeOpacity={0.85}
        testID="settings-pseudo-edit"
      >
        <Ionicons name="person-circle-outline" size={20} color={theme.primary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.rowLabel}>Pseudo</Text>
          <Text style={styles.rowValue} numberOfLines={1}>{pseudo}</Text>
        </View>
        <Ionicons name="create-outline" size={18} color={theme.textMute} />
      </TouchableOpacity>

      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={() => (saving ? null : setOpen(false))}
      >
        <Pressable style={styles.backdrop} onPress={() => (saving ? null : setOpen(false))}>
          <Pressable style={styles.card} onPress={(e) => e.stopPropagation()}>
            <View style={styles.header}>
              <View style={styles.iconWrap}>
                <Ionicons name="person-circle" size={22} color={theme.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>Modifier le pseudo</Text>
                <Text style={styles.subtitle}>
                  C{"\u2019"}est le nom qui apparaîtra sur vos signalements.
                </Text>
              </View>
              <TouchableOpacity
                onPress={() => (saving ? null : setOpen(false))}
                hitSlop={10}
                testID="pseudo-modal-close"
              >
                <Ionicons name="close" size={22} color={theme.textDim} />
              </TouchableOpacity>
            </View>
            <TextInput
              style={styles.input}
              value={draft}
              onChangeText={setDraft}
              placeholder="Votre pseudo"
              placeholderTextColor={theme.textMute}
              autoFocus
              selectTextOnFocus
              maxLength={24}
              editable={!saving}
              returnKeyType="done"
              onSubmitEditing={save}
              testID="pseudo-modal-input"
            />
            <Text style={styles.counter}>{draft.trim().length}/24</Text>
            <View style={styles.actions}>
              <TouchableOpacity
                style={[styles.btn, styles.btnGhost]}
                onPress={() => setOpen(false)}
                disabled={saving}
                testID="pseudo-modal-cancel"
              >
                <Text style={styles.btnGhostText}>Annuler</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.btn,
                  styles.btnPrimary,
                  (saving || draft.trim().length < 3) && { opacity: 0.5 },
                ]}
                onPress={save}
                disabled={saving || draft.trim().length < 3}
                testID="pseudo-modal-save"
              >
                {saving ? (
                  <ActivityIndicator size="small" color={theme.bg} />
                ) : (
                  <>
                    <Ionicons name="checkmark" size={18} color={theme.bg} />
                    <Text style={styles.btnPrimaryText}>Enregistrer</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md, padding: spacing.md,
    borderWidth: 1, borderColor: theme.border, minHeight: 56,
  },
  rowLabel: { color: theme.textDim, fontSize: 11, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1 },
  rowValue: { color: theme.text, fontWeight: "800", fontSize: 15, marginTop: 1 },

  backdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  card: {
    width: "100%", maxWidth: 420,
    backgroundColor: theme.bg2, borderRadius: radii.lg,
    padding: spacing.lg, borderWidth: 1, borderColor: theme.border,
    gap: spacing.sm,
  },
  header: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, marginBottom: 4 },
  iconWrap: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: "rgba(72,202,228,0.15)",
    alignItems: "center", justifyContent: "center",
  },
  title: { color: theme.text, fontSize: 16, fontWeight: "900" },
  subtitle: { color: theme.textDim, fontSize: 12, marginTop: 2, lineHeight: 16 },
  input: {
    backgroundColor: theme.bg, color: theme.text,
    borderWidth: 1, borderColor: theme.primary,
    borderRadius: radii.md, paddingHorizontal: spacing.md, paddingVertical: 12,
    fontSize: 16, fontWeight: "700", marginTop: spacing.sm,
  },
  counter: { color: theme.textMute, fontSize: 11, alignSelf: "flex-end", marginTop: -4, marginBottom: 4 },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  btn: {
    flex: 1, minHeight: 46, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingHorizontal: spacing.md,
  },
  btnGhost: { backgroundColor: "transparent", borderWidth: 1, borderColor: theme.border },
  btnGhostText: { color: theme.textDim, fontWeight: "800", fontSize: 14 },
  btnPrimary: { backgroundColor: theme.primary },
  btnPrimaryText: { color: theme.bg, fontWeight: "900", fontSize: 14 },
});
