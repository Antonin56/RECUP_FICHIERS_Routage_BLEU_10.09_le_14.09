/**
 * SignalMar — Panneau de sélection du moteur de routage (01/08/2026).
 *
 * Affiché dans Profil › Navigation & routes. Permet à l'utilisateur de :
 *   • Voir la liste des moteurs disponibles (A, B, dupliqués…).
 *   • Choisir son moteur actif (radio-select — persistant côté serveur).
 *   • ADMIN uniquement : dupliquer un moteur (nom au choix), renommer,
 *     supprimer (refusé si le moteur a servi à générer une route enregistrée
 *     — cf. contrainte serveur Option A).
 *
 * Aucune modification frontend n'est requise sur la page /map — les endpoints
 * de calcul route utilisent automatiquement `user.active_engine_id` en
 * l'absence de `engine_id` explicite dans le body.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, Modal, Platform, Pressable, StyleSheet, Text,
  TextInput, TouchableOpacity, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";

import { api, type RoutingEngine } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { showToast } from "@/src/components/Toast";
import { theme, spacing, radii } from "@/src/lib/theme";

type EngineListResp = Awaited<ReturnType<typeof api.listRoutingEngines>>;

export function RoutingEnginePanel() {
  const { user, refresh } = useAuth();
  const [state, setState] = useState<EngineListResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [dupModal, setDupModal] = useState<null | { source: RoutingEngine }>(null);
  const [dupName, setDupName] = useState("");
  const [dupDesc, setDupDesc] = useState("");
  const [renameModal, setRenameModal] = useState<null | { engine: RoutingEngine }>(null);
  const [renameName, setRenameName] = useState("");

  const isAdmin = !!user?.is_signalmar_admin;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.listRoutingEngines();
      setState(r);
    } catch (err) {
      console.warn("engines load", err);
      showToast("error", "Chargement des moteurs impossible.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const onPick = useCallback(async (engine: RoutingEngine) => {
    if (busyId) return;
    setBusyId(engine.id);
    try {
      await api.setActiveRoutingEngine(engine.id);
      showToast("success", `Moteur actif : ${engine.name}`);
      await refresh().catch(() => {});
      await reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Bascule impossible.";
      showToast("error", msg);
    } finally {
      setBusyId(null);
    }
  }, [busyId, refresh, reload]);

  const onDuplicate = useCallback(async () => {
    if (!dupModal) return;
    const name = dupName.trim();
    if (!name) {
      showToast("error", "Choisissez un nom.");
      return;
    }
    setBusyId(dupModal.source.id);
    try {
      const r = await api.duplicateRoutingEngine(
        dupModal.source.id, name, dupDesc.trim() || undefined,
      );
      showToast("success", `Moteur créé : ${r.engine.name} (${r.engine.id})`);
      setDupModal(null); setDupName(""); setDupDesc("");
      await reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Duplication impossible.";
      showToast("error", msg);
    } finally {
      setBusyId(null);
    }
  }, [dupModal, dupName, dupDesc, reload]);

  const onRename = useCallback(async () => {
    if (!renameModal) return;
    const name = renameName.trim();
    if (!name) {
      showToast("error", "Le nom ne peut pas être vide.");
      return;
    }
    setBusyId(renameModal.engine.id);
    try {
      await api.renameRoutingEngine(renameModal.engine.id, name);
      showToast("success", "Moteur renommé.");
      setRenameModal(null); setRenameName("");
      await reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Renommage impossible.";
      showToast("error", msg);
    } finally {
      setBusyId(null);
    }
  }, [renameModal, renameName, reload]);

  const onDelete = useCallback((engine: RoutingEngine) => {
    if (engine.built_in) return;
    Alert.alert(
      "Supprimer ce moteur ?",
      `« ${engine.name} » sera définitivement supprimé. Cette action est irréversible.\n\nNote : si le moteur a servi à générer une route enregistrée, la suppression sera refusée pour préserver l'historique.`,
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Supprimer", style: "destructive",
          onPress: async () => {
            setBusyId(engine.id);
            try {
              await api.deleteRoutingEngine(engine.id);
              showToast("success", "Moteur supprimé.");
              await reload();
            } catch (err: unknown) {
              const msg = err instanceof Error ? err.message : "Suppression impossible.";
              showToast("error", msg);
            } finally {
              setBusyId(null);
            }
          },
        },
      ],
    );
  }, [reload]);

  if (loading && !state) {
    return (
      <View style={styles.loadingRow}>
        <ActivityIndicator size="small" color={theme.accent} />
        <Text style={styles.loadingText}>Chargement des moteurs…</Text>
      </View>
    );
  }
  if (!state) return null;

  const activeId = state.active_id;

  return (
    <View style={styles.root}>
      <View style={styles.headerRow}>
        <Ionicons name="cog-outline" size={16} color={theme.textDim} />
        <Text style={styles.headerText}>Moteur de calcul de route</Text>
      </View>
      <Text style={styles.help}>
        Choisissez le moteur qui calculera vos routes automatiques et
        manuelles. Chaque route enregistrée conserve le nom du moteur qui
        {"\u00A0"}l&apos;a produite, pour comparer les évolutions.
      </Text>

      {state.engines.map((e) => {
        const active = e.id === activeId;
        return (
          <View key={e.id} style={[styles.card, active && styles.cardActive]}>
            <Pressable
              onPress={() => onPick(e)}
              disabled={busyId === e.id}
              style={styles.cardMain}
              testID={`engine-row-${e.id}`}
            >
              <View style={[styles.radio, active && styles.radioActive]}>
                {active ? <View style={styles.radioDot} /> : null}
              </View>
              <View style={styles.cardText}>
                <View style={styles.cardTitleRow}>
                  <Text style={styles.cardTitle} numberOfLines={1}>{e.name}</Text>
                  {e.built_in ? (
                    <View style={styles.badgeBuiltIn}>
                      <Text style={styles.badgeBuiltInText}>BUILT-IN</Text>
                    </View>
                  ) : null}
                  {active ? (
                    <View style={styles.badgeActive}>
                      <Text style={styles.badgeActiveText}>ACTIF</Text>
                    </View>
                  ) : null}
                </View>
                {e.description ? (
                  <Text style={styles.cardDesc} numberOfLines={2}>{e.description}</Text>
                ) : null}
                <View style={styles.metaRow}>
                  <Text style={styles.meta}>Algo : {e.algo}</Text>
                  {typeof e.usage_count === "number" && e.usage_count > 0 ? (
                    <Text style={styles.meta}> · {e.usage_count} route{e.usage_count > 1 ? "s" : ""}</Text>
                  ) : null}
                  {e.parent_id ? (
                    <Text style={styles.meta}> · issu de {e.parent_id}</Text>
                  ) : null}
                </View>
                {/* 02/08/2026 — ID STABLE du moteur : indépendant du nom
                    (renommage libre), c'est la clé de traçabilité citée sur
                    chaque route calculée. Tap = copie. */}
                <TouchableOpacity
                  style={styles.idChip}
                  onPress={async () => {
                    await Clipboard.setStringAsync(e.id);
                    showToast("success", `ID copié : ${e.id}`);
                  }}
                  activeOpacity={0.7}
                  hitSlop={6}
                  testID={`engine-id-${e.id}`}
                >
                  <Ionicons name="finger-print-outline" size={11} color={theme.textDim} />
                  <Text style={styles.idChipText}>ID : {e.id}</Text>
                  <Ionicons name="copy-outline" size={10} color={theme.textDim} />
                </TouchableOpacity>
              </View>
              {busyId === e.id ? (
                <ActivityIndicator size="small" color={theme.accent} />
              ) : null}
            </Pressable>

            {isAdmin ? (
              <View style={styles.adminRow}>
                <TouchableOpacity
                  style={styles.adminBtn}
                  onPress={() => {
                    setDupModal({ source: e });
                    setDupName(`Copie de ${e.name}`);
                    setDupDesc("");
                  }}
                  hitSlop={6}
                >
                  <Ionicons name="copy-outline" size={14} color={theme.textDim} />
                  <Text style={styles.adminBtnText}>Dupliquer</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.adminBtn}
                  onPress={() => {
                    setRenameModal({ engine: e });
                    setRenameName(e.name);
                  }}
                  hitSlop={6}
                >
                  <Ionicons name="pencil-outline" size={14} color={theme.textDim} />
                  <Text style={styles.adminBtnText}>Renommer</Text>
                </TouchableOpacity>
                {!e.built_in ? (
                  <TouchableOpacity
                    style={[styles.adminBtn, styles.adminBtnDanger]}
                    onPress={() => onDelete(e)}
                    hitSlop={6}
                  >
                    <Ionicons name="trash-outline" size={14} color="#E5383B" />
                    <Text style={[styles.adminBtnText, { color: "#E5383B" }]}>Supprimer</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            ) : null}
          </View>
        );
      })}

      {/* Modale duplication */}
      <Modal
        visible={!!dupModal}
        transparent
        animationType="fade"
        onRequestClose={() => setDupModal(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Dupliquer un moteur</Text>
            <Text style={styles.modalSub}>
              Source : {dupModal?.source.name}
            </Text>
            <Text style={styles.label}>Nom du nouveau moteur</Text>
            <TextInput
              value={dupName}
              onChangeText={setDupName}
              placeholder="ex. Moteur test 01/08"
              placeholderTextColor="#5A6270"
              maxLength={80}
              style={styles.input}
            />
            <Text style={styles.label}>Description (facultatif)</Text>
            <TextInput
              value={dupDesc}
              onChangeText={setDupDesc}
              placeholder="Objectif du test…"
              placeholderTextColor="#5A6270"
              maxLength={200}
              multiline
              style={[styles.input, { height: 60 }]}
            />
            <View style={styles.modalBtns}>
              <TouchableOpacity
                style={[styles.modalBtn, styles.modalBtnGhost]}
                onPress={() => setDupModal(null)}
              >
                <Text style={styles.modalBtnGhostText}>Annuler</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalBtn, styles.modalBtnPrimary]}
                onPress={onDuplicate}
                disabled={!!busyId}
              >
                <Text style={styles.modalBtnPrimaryText}>Dupliquer</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Modale renommage */}
      <Modal
        visible={!!renameModal}
        transparent
        animationType="fade"
        onRequestClose={() => setRenameModal(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Renommer le moteur</Text>
            <Text style={styles.label}>Nouveau nom</Text>
            <TextInput
              value={renameName}
              onChangeText={setRenameName}
              placeholder="Nouveau nom"
              placeholderTextColor="#5A6270"
              maxLength={80}
              autoFocus
              style={styles.input}
            />
            <View style={styles.modalBtns}>
              <TouchableOpacity
                style={[styles.modalBtn, styles.modalBtnGhost]}
                onPress={() => setRenameModal(null)}
              >
                <Text style={styles.modalBtnGhostText}>Annuler</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalBtn, styles.modalBtnPrimary]}
                onPress={onRename}
                disabled={!!busyId}
              >
                <Text style={styles.modalBtnPrimaryText}>Enregistrer</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { gap: spacing.sm },
  loadingRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8 },
  loadingText: { color: theme.textDim, fontSize: 12 },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },
  headerText: { color: theme.text, fontSize: 13, fontWeight: "800" },
  help: { color: theme.textDim, fontSize: 11.5, lineHeight: 16, marginBottom: 4 },
  card: {
    backgroundColor: "rgba(255,255,255,0.04)",
    borderRadius: radii.md, borderWidth: 1, borderColor: "rgba(255,255,255,0.08)",
  },
  cardActive: {
    borderColor: "rgba(72,202,228,0.6)", backgroundColor: "rgba(72,202,228,0.10)",
  },
  cardMain: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 12,
  },
  radio: {
    width: 18, height: 18, borderRadius: 9, borderWidth: 1.5,
    borderColor: "rgba(255,255,255,0.35)",
    alignItems: "center", justifyContent: "center",
  },
  radioActive: { borderColor: "#48CAE4" },
  radioDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#48CAE4" },
  cardText: { flex: 1 },
  idChip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    alignSelf: "flex-start", marginTop: 6,
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: 5,
    backgroundColor: "rgba(255,255,255,0.06)",
  },
  idChipText: {
    color: theme.textDim, fontSize: 10.5, fontWeight: "700",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
  },
  cardTitleRow: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  cardTitle: { color: theme.text, fontSize: 14, fontWeight: "800", maxWidth: "70%" },
  badgeBuiltIn: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
    backgroundColor: "rgba(46,196,182,0.15)",
  },
  badgeBuiltInText: { color: "#2EC4B6", fontSize: 9, fontWeight: "900", letterSpacing: 0.5 },
  badgeActive: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
    backgroundColor: "rgba(72,202,228,0.20)",
  },
  badgeActiveText: { color: "#48CAE4", fontSize: 9, fontWeight: "900", letterSpacing: 0.5 },
  cardDesc: { color: theme.textDim, fontSize: 11.5, lineHeight: 15, marginTop: 3 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", marginTop: 4 },
  meta: { color: "#7A8291", fontSize: 10.5 },
  adminRow: {
    flexDirection: "row", gap: 6, paddingHorizontal: 10, paddingBottom: 8,
    borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.06)", paddingTop: 6,
  },
  adminBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 5, borderRadius: 6,
    backgroundColor: "rgba(255,255,255,0.05)",
  },
  adminBtnDanger: { backgroundColor: "rgba(229,56,59,0.10)" },
  adminBtnText: { color: theme.textDim, fontSize: 11, fontWeight: "700" },
  modalOverlay: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "center", alignItems: "center", padding: 20,
  },
  modalCard: {
    backgroundColor: "#0F1B2E", borderRadius: radii.lg,
    borderWidth: 1, borderColor: "rgba(72,202,228,0.35)",
    padding: 18, width: "100%", maxWidth: 400,
  },
  modalTitle: { color: theme.text, fontSize: 16, fontWeight: "900", marginBottom: 4 },
  modalSub: { color: theme.textDim, fontSize: 12, marginBottom: 12 },
  label: { color: theme.textDim, fontSize: 11, fontWeight: "700", marginBottom: 4, marginTop: 8 },
  input: {
    backgroundColor: "rgba(255,255,255,0.06)", color: theme.text,
    borderRadius: radii.sm, paddingHorizontal: 10, paddingVertical: 8,
    fontSize: 13, borderWidth: 1, borderColor: "rgba(255,255,255,0.1)",
  },
  modalBtns: { flexDirection: "row", gap: 8, marginTop: 16, justifyContent: "flex-end" },
  modalBtn: { paddingVertical: 9, paddingHorizontal: 14, borderRadius: radii.sm },
  modalBtnGhost: { backgroundColor: "rgba(255,255,255,0.06)" },
  modalBtnGhostText: { color: theme.textDim, fontWeight: "700", fontSize: 13 },
  modalBtnPrimary: { backgroundColor: "#48CAE4" },
  modalBtnPrimaryText: { color: "#0B132B", fontWeight: "900", fontSize: 13 },
});
