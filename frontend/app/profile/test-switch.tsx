/**
 * Phase T — Test-account fast switcher (QA convenience screen).
 *
 * Small, focused UI:
 *   1. Fetches the whitelisted test accounts from /api/dev/test-accounts.
 *   2. Renders them as tap-to-switch cards; the current account is
 *      marked and disabled.
 *   3. On tap → POST /api/dev/switch-account, hydrate the new JWT via
 *      AuthContext.switchToTestAccount(), then bounce back to the
 *      previous route so the caller sees the app "as" the new user.
 *
 * If the backend returns 403 (user not whitelisted), we show a friendly
 * empty state — the button that opens this screen is *itself* already
 * gated on the whitelist, so this is only a safety net for stale
 * navigations.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, type TestAccount } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { logger } from "@/src/lib/logger";
import { radii, spacing, theme } from "@/src/lib/theme";

export default function TestSwitchScreen() {
  const router = useRouter();
  const { switchToTestAccount, user } = useAuth();

  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState<TestAccount[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.devListTestAccounts();
      setAccounts(res.accounts);
    } catch (e) {
      setErr((e as Error).message || "Impossible de charger les comptes");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const doSwitch = useCallback(async (acc: TestAccount) => {
    if (acc.is_current) return;
    setSwitching(acc.user_id);
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
      await switchToTestAccount(acc.user_id);
      logger.event("app", "test_account_switched", {
        from: user?.user_id, to: acc.user_id,
      });
      // Bounce back — the router stack refresh with the new AuthContext
      // will re-render the whole app as the target user.
      router.replace("/(tabs)/profile");
    } catch (e) {
      Alert.alert(
        "Bascule impossible",
        (e as Error).message || "Erreur inconnue lors de la bascule.",
      );
    } finally {
      setSwitching(null);
    }
  }, [switchToTestAccount, user?.user_id, router]);

  const renderItem = ({ item }: { item: TestAccount }) => {
    const busy = switching === item.user_id;
    return (
      <TouchableOpacity
        style={[
          styles.card,
          item.is_current && styles.cardCurrent,
          busy && { opacity: 0.5 },
        ]}
        onPress={() => doSwitch(item)}
        disabled={item.is_current || busy}
        activeOpacity={0.85}
        testID={`test-switch-${item.user_id}`}
      >
        {item.picture ? (
          <Image source={{ uri: item.picture }} style={styles.avatar} />
        ) : (
          <View style={[styles.avatar, styles.avatarFallback]}>
            <Text style={styles.avatarInitial}>
              {item.pseudo.slice(0, 1).toUpperCase()}
            </Text>
          </View>
        )}
        <View style={{ flex: 1 }}>
          <Text style={styles.pseudo} numberOfLines={1}>{item.pseudo}</Text>
          <Text style={styles.email} numberOfLines={1}>{item.phone || item.email || "—"}</Text>
          <Text style={styles.points}>{item.points} pts</Text>
        </View>
        {item.is_current ? (
          <View style={styles.currentChip}>
            <Ionicons name="checkmark-circle" size={14} color={theme.primary} />
            <Text style={styles.currentChipTxt}>Actif</Text>
          </View>
        ) : busy ? (
          <ActivityIndicator color={theme.primary} />
        ) : (
          <Ionicons name="swap-horizontal" size={22} color={theme.primary} />
        )}
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.hBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.title}>Comptes de test</Text>
          <Text style={styles.sub}>Bascule instantanée entre les comptes (DEV)</Text>
        </View>
        <TouchableOpacity onPress={load} style={styles.hBtn} hitSlop={12}>
          <Ionicons name="refresh" size={22} color={theme.textDim} />
        </TouchableOpacity>
      </View>

      <View style={styles.infoBanner}>
        <Ionicons name="flask" size={16} color={theme.primary} />
        <Text style={styles.infoTxt}>
          Mode DEV — tous les comptes créés pendant les tests sont listés et
          basculables en un tap. Sera restreint à l{"\u2019"}admin avant la
          publication de l{"\u2019"}app.
        </Text>
      </View>

      {loading ? (
        <View style={styles.centered}>
          <ActivityIndicator color={theme.primary} size="large" />
        </View>
      ) : err ? (
        <View style={styles.centered}>
          <Ionicons name="warning-outline" size={40} color={theme.warning} />
          <Text style={styles.errTxt}>{err}</Text>
          <TouchableOpacity style={styles.retry} onPress={load}>
            <Text style={styles.retryTxt}>Réessayer</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={accounts}
          keyExtractor={(a) => a.user_id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: spacing.md, gap: 10, paddingBottom: 40 }}
        />
      )}
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
  hBtn: { padding: 4, minWidth: 36, alignItems: "center" },
  title: { color: theme.text, fontSize: 17, fontWeight: "800" },
  sub: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  infoBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: spacing.md, marginTop: spacing.sm,
    padding: 10, borderRadius: radii.md,
    backgroundColor: "rgba(46,196,182,0.10)",
    borderColor: "rgba(46,196,182,0.35)", borderWidth: 1,
  },
  infoTxt: { color: theme.text, fontSize: 11, flex: 1, lineHeight: 16 },
  centered: {
    flex: 1, alignItems: "center", justifyContent: "center",
    gap: 12, padding: spacing.lg,
  },
  errTxt: { color: theme.textDim, textAlign: "center" },
  retry: {
    paddingHorizontal: 16, paddingVertical: 8,
    borderRadius: radii.md, borderColor: theme.border, borderWidth: 1,
  },
  retryTxt: { color: theme.text, fontWeight: "700" },
  card: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12, borderRadius: radii.md,
    backgroundColor: theme.bg2, borderWidth: 1, borderColor: theme.border,
  },
  cardCurrent: {
    borderColor: theme.primary,
    backgroundColor: "rgba(72,202,228,0.08)",
  },
  avatar: { width: 48, height: 48, borderRadius: 24 },
  avatarFallback: {
    backgroundColor: theme.bg3, alignItems: "center", justifyContent: "center",
  },
  avatarInitial: { color: theme.primary, fontSize: 20, fontWeight: "900" },
  pseudo: { color: theme.text, fontSize: 15, fontWeight: "800" },
  email: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  points: { color: theme.primary, fontSize: 10, fontWeight: "700", marginTop: 2 },
  currentChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(72,202,228,0.15)",
    borderColor: theme.primary, borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: radii.sm,
  },
  currentChipTxt: { color: theme.primary, fontSize: 11, fontWeight: "800" },
});
