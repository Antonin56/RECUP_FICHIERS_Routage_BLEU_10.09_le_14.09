/**
 * Phase 4.1 — Join-via-code screen.
 *
 * User pastes / types an 8-char invite code, sees a preview of the group
 * (name, owner, member count) and confirms with "Rejoindre".
 */
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Image,
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
import { Stack, useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, GroupInvitePreview } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";

export default function JoinGroupScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ code?: string }>();
  const initialCode = String(params.code || "").toUpperCase();

  const [code, setCode] = useState(initialCode);
  const [preview, setPreview] = useState<GroupInvitePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [joining, setJoining] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const doPreview = useCallback(async (raw: string) => {
    const c = raw.trim().toUpperCase();
    if (c.length < 8) {
      setPreview(null);
      return;
    }
    setErr(null);
    setPreviewing(true);
    try {
      const p = await api.groupPreviewInvite(c);
      setPreview(p);
    } catch (e) {
      setPreview(null);
      setErr((e as Error).message || "Code invalide");
    } finally {
      setPreviewing(false);
    }
  }, []);

  const onChangeCode = (v: string) => {
    const clean = v.replace(/[^A-Z0-9]/gi, "").toUpperCase();
    setCode(clean);
    if (clean.length === 8) doPreview(clean);
    else setPreview(null);
  };

  const doJoin = async () => {
    if (!preview) return;
    setJoining(true);
    setErr(null);
    try {
      await api.groupJoinByCode(code);
      router.replace(`/groups/${preview.group_id}`);
    } catch (e) {
      setErr((e as Error).message || "Impossible de rejoindre");
    } finally {
      setJoining(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.headerBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Rejoindre un groupe</Text>
        <View style={{ width: 36 }} />
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Code d&apos;invitation</Text>
          <TextInput
            style={styles.codeInput}
            value={code}
            onChangeText={onChangeCode}
            placeholder="XXXXXXXX"
            placeholderTextColor={theme.textMute}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={8}
            testID="group-join-code-input"
          />
          <Text style={styles.hint}>
            Colle ici le code à 8 caractères que le propriétaire du groupe t&apos;a partagé.
          </Text>

          {previewing && (
            <View style={styles.previewLoading}>
              <ActivityIndicator color={theme.primary} />
              <Text style={{ color: theme.textDim, marginLeft: 8 }}>Recherche du groupe…</Text>
            </View>
          )}

          {preview && (
            <View style={styles.previewCard} testID="group-join-preview">
              <View style={styles.previewHead}>
                {preview.avatar_url ? (
                  <Image source={{ uri: preview.avatar_url }} style={styles.previewAvatar} />
                ) : (
                  <View style={[styles.previewAvatar, styles.previewAvatarFallback]}>
                    <Ionicons name="people" size={26} color={theme.primary} />
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={styles.previewName}>{preview.name}</Text>
                  <Text style={styles.previewMeta}>
                    par {preview.owner_pseudo} · {preview.member_count}/{preview.max_members} membres
                  </Text>
                </View>
              </View>
              {!!preview.description && (
                <Text style={styles.previewDesc}>{preview.description}</Text>
              )}
              <Pressable
                style={[styles.primaryBtn, joining && { opacity: 0.6 }]}
                disabled={joining}
                onPress={doJoin}
                testID="group-join-confirm"
              >
                {joining ? (
                  <ActivityIndicator color={theme.bg} />
                ) : (
                  <>
                    <Ionicons name="enter" size={20} color={theme.bg} />
                    <Text style={styles.primaryBtnTxt}>Rejoindre le groupe</Text>
                  </>
                )}
              </Pressable>
            </View>
          )}

          {!!err && (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={16} color={theme.danger} />
              <Text style={styles.errTxt}>{err}</Text>
            </View>
          )}
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
  label: { color: theme.textDim, fontSize: 13, fontWeight: "800", marginBottom: 8, letterSpacing: 0.3 },
  codeInput: {
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    color: theme.text, fontSize: 26, fontWeight: "900",
    letterSpacing: 6, textAlign: "center",
    paddingHorizontal: 14, paddingVertical: 14,
  },
  hint: { color: theme.textMute, fontSize: 12, marginTop: 6, textAlign: "center" },
  previewLoading: {
    marginTop: 24, flexDirection: "row", alignItems: "center", justifyContent: "center",
  },
  previewCard: {
    marginTop: 24, backgroundColor: theme.bg2, borderRadius: radii.lg,
    borderWidth: 1, borderColor: theme.border, padding: spacing.md, gap: 12,
  },
  previewHead: { flexDirection: "row", alignItems: "center", gap: 12 },
  previewAvatar: { width: 56, height: 56, borderRadius: 28 },
  previewAvatarFallback: {
    backgroundColor: theme.bg3, alignItems: "center", justifyContent: "center",
  },
  previewName: { color: theme.text, fontSize: 18, fontWeight: "800" },
  previewMeta: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  previewDesc: { color: theme.textDim, fontSize: 13, lineHeight: 18 },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.primary, paddingVertical: 12, borderRadius: radii.md,
  },
  primaryBtnTxt: { color: theme.bg, fontSize: 15, fontWeight: "800" },
  errBox: {
    marginTop: 14, flexDirection: "row", gap: 6, alignItems: "center",
    backgroundColor: "rgba(230,57,70,0.12)", padding: 10, borderRadius: radii.sm,
    borderWidth: 1, borderColor: theme.danger,
  },
  errTxt: { color: theme.text, fontSize: 13, flex: 1 },
});
