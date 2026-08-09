/**
 * 19/07/2026 — Gestion des BÊTA-TESTEURS (écran ADMIN uniquement).
 *
 * L'admin ajoute/retire des numéros de mobile FR. Chaque numéro présent :
 *   • donne accès au « Mode test bêta » (signalements TEST depuis la terre)
 *   • donne accès à la bascule rapide entre comptes de la liste bêta.
 * Le backend applique les mêmes règles (routers/beta.py).
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api/client";
import { radii, spacing, theme } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";

type Tester = {
  phone: string;
  note: string;
  pseudo?: string | null;
  has_account: boolean;
  test_mode: boolean;
};

export default function BetaTestersScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [testers, setTesters] = useState<Tester[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.betaTesters();
      setTesters(res.testers as Tester[]);
    } catch (e) {
      setErr((e as Error).message || "Accès refusé");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function add() {
    const p = phone.trim();
    if (!p) return;
    setBusy(true);
    try {
      await api.addBetaTester(p, note.trim() || undefined);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      setPhone("");
      setNote("");
      showToast("success", "Testeur ajouté");
      load();
    } catch (e) {
      showToast("error", (e as Error).message || "Numéro invalide");
    } finally {
      setBusy(false);
    }
  }

  function confirmRemove(t: Tester) {
    const msg = `${t.phone}${t.pseudo ? ` (${t.pseudo})` : ""} perdra le mode test et la bascule de comptes.`;
    const doRemove = async () => {
      try {
        await api.removeBetaTester(t.phone);
        showToast("info", "Testeur retiré");
        load();
      } catch {
        showToast("error", "Suppression impossible");
      }
    };
    // Alert.alert est un no-op sur RN Web (iter90) → window.confirm en preview.
    if (Platform.OS === "web") {
      if (window.confirm(`Retirer ce testeur ?\n${msg}`)) doRemove();
      return;
    }
    Alert.alert("Retirer ce testeur ?", msg, [
      { text: "Annuler", style: "cancel" },
      { text: "Retirer", style: "destructive", onPress: doRemove },
    ]);
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.hBtn} hitSlop={12} testID="beta-back">
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.title}>Bêta-testeurs</Text>
          <Text style={styles.sub}>Mode test + bascule de comptes (ADMIN)</Text>
        </View>
        <TouchableOpacity onPress={load} style={styles.hBtn} hitSlop={12}>
          <Ionicons name="refresh" size={22} color={theme.textDim} />
        </TouchableOpacity>
      </View>

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <View style={styles.addBox}>
          <TextInput
            style={styles.input}
            value={phone}
            onChangeText={setPhone}
            placeholder="06 12 34 56 78"
            placeholderTextColor={theme.textMute}
            keyboardType="phone-pad"
            testID="beta-phone-input"
          />
          <TextInput
            style={[styles.input, { flex: 1 }]}
            value={note}
            onChangeText={setNote}
            placeholder="Note (prénom…)"
            placeholderTextColor={theme.textMute}
            maxLength={60}
            testID="beta-note-input"
          />
          <TouchableOpacity
            style={[styles.addBtn, (busy || !phone.trim()) && { opacity: 0.5 }]}
            onPress={add}
            disabled={busy || !phone.trim()}
            testID="beta-add-button"
          >
            {busy
              ? <ActivityIndicator size="small" color="#04121F" />
              : <Ionicons name="add" size={22} color="#04121F" />}
          </TouchableOpacity>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={theme.primary} />
        ) : err ? (
          <Text style={styles.err}>{err}</Text>
        ) : (
          <FlatList
            data={testers}
            keyExtractor={(t) => t.phone}
            contentContainerStyle={{ padding: spacing.md, gap: spacing.sm }}
            ListEmptyComponent={
              <Text style={styles.empty}>
                Aucun bêta-testeur. Ajoutez un numéro de mobile ci-dessus —
                le testeur pourra créer plusieurs comptes avec ses numéros
                déclarés (code SMS de test : 123456).
              </Text>
            }
            renderItem={({ item }) => (
              <View style={styles.card} testID={`beta-tester-${item.phone}`}>
                <Ionicons
                  name={item.has_account ? "person-circle" : "person-circle-outline"}
                  size={30}
                  color={item.has_account ? theme.primary : theme.textMute}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardPhone}>{item.phone}</Text>
                  <Text style={styles.cardSub}>
                    {item.pseudo ? `${item.pseudo}` : "Pas encore de compte"}
                    {item.note ? ` · ${item.note}` : ""}
                    {item.test_mode ? " · mode test ON" : ""}
                  </Text>
                </View>
                <TouchableOpacity onPress={() => confirmRemove(item)} hitSlop={10} testID={`beta-remove-${item.phone}`}>
                  <Ionicons name="trash-outline" size={20} color={theme.danger} />
                </TouchableOpacity>
              </View>
            )}
          />
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.bg },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: spacing.sm, paddingVertical: spacing.sm,
  },
  hBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: theme.text, fontWeight: "800", fontSize: 17 },
  sub: { color: theme.textMute, fontSize: 11, marginTop: 2 },
  addBox: {
    flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm, alignItems: "center",
  },
  input: {
    backgroundColor: theme.bg2, borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.md, color: theme.text, paddingHorizontal: 12,
    paddingVertical: 10, fontSize: 14, minWidth: 136,
  },
  addBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  err: { color: theme.danger, textAlign: "center", marginTop: 40, paddingHorizontal: spacing.lg },
  empty: { color: theme.textMute, textAlign: "center", marginTop: 30, lineHeight: 20, paddingHorizontal: spacing.md },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: theme.bg2, borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.md, padding: spacing.md,
  },
  cardPhone: { color: theme.text, fontWeight: "800", fontSize: 15 },
  cardSub: { color: theme.textMute, fontSize: 12, marginTop: 2 },
});
