/**
 * Phase 4.1 — Create-group screen.
 *
 * Simple form: name (required, 2-40 chars), description (optional, ≤240),
 * avatar (optional data URI). Server auto-adds creator as owner.
 */
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Stack, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";

const NAME_MIN = 2;
const NAME_MAX = 40;
const DESC_MAX = 240;

export default function NewGroupScreen() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canSubmit = name.trim().length >= NAME_MIN && !busy;

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      const g = await api.groupCreate({
        name: name.trim(),
        description: description.trim(),
      });
      // Jump straight to the detail so the user can share the code.
      router.replace(`/groups/${g.group_id}`);
    } catch (e) {
      setErr((e as Error).message || "Erreur inconnue");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.headerBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Nouveau groupe</Text>
        <View style={{ width: 36 }} />
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.label}>Nom du groupe *</Text>
          <TextInput
            style={styles.input}
            value={name}
            onChangeText={setName}
            placeholder="Ex : Copains du port"
            placeholderTextColor={theme.textMute}
            maxLength={NAME_MAX}
            returnKeyType="next"
            testID="group-new-name"
          />
          <Text style={styles.hint}>{name.length} / {NAME_MAX} caractères</Text>

          <Text style={[styles.label, { marginTop: 20 }]}>Description (optionnelle)</Text>
          <TextInput
            style={[styles.input, styles.inputMulti]}
            value={description}
            onChangeText={setDescription}
            placeholder="Un mot sur l'usage du groupe : régate, sortie du week-end…"
            placeholderTextColor={theme.textMute}
            maxLength={DESC_MAX}
            multiline
            numberOfLines={3}
            testID="group-new-desc"
          />
          <Text style={styles.hint}>{description.length} / {DESC_MAX}</Text>

          {!!err && (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={16} color={theme.danger} />
              <Text style={styles.errTxt}>{err}</Text>
            </View>
          )}

          <Text style={styles.disclaimer}>
            Chaque groupe accepte jusqu&apos;à 20 marins. Tu deviendras propriétaire
            et pourras partager un lien d&apos;invitation à tes contacts.
          </Text>

          <Pressable
            style={[styles.primaryBtn, !canSubmit && { opacity: 0.5 }]}
            disabled={!canSubmit}
            onPress={submit}
            testID="group-new-submit"
          >
            {busy ? (
              <ActivityIndicator color={theme.bg} />
            ) : (
              <>
                <Ionicons name="checkmark-circle" size={22} color={theme.bg} />
                <Text style={styles.primaryBtnTxt}>Créer le groupe</Text>
              </>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  headerBtn: { padding: 4, minWidth: 36, alignItems: "center" },
  headerTitle: { color: theme.text, fontSize: 18, fontWeight: "800" },
  content: { padding: spacing.lg, paddingBottom: 60 },
  label: { color: theme.textDim, fontSize: 13, fontWeight: "800", marginBottom: 6, letterSpacing: 0.3 },
  input: {
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    color: theme.text, fontSize: 16, fontWeight: "600",
    paddingHorizontal: 14, paddingVertical: 12,
  },
  inputMulti: { minHeight: 92, textAlignVertical: "top" },
  hint: { color: theme.textMute, fontSize: 11, marginTop: 4, textAlign: "right" },
  disclaimer: { color: theme.textDim, fontSize: 12, marginTop: 20, lineHeight: 18 },
  errBox: {
    marginTop: 14, flexDirection: "row", gap: 6, alignItems: "center",
    backgroundColor: "rgba(230,57,70,0.12)", padding: 10, borderRadius: radii.sm,
    borderWidth: 1, borderColor: theme.danger,
  },
  errTxt: { color: theme.text, fontSize: 13, flex: 1 },
  primaryBtn: {
    marginTop: 24, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, backgroundColor: theme.primary,
    paddingHorizontal: 22, paddingVertical: 14, borderRadius: radii.md,
  },
  primaryBtnTxt: { color: theme.bg, fontSize: 16, fontWeight: "800" },
});
