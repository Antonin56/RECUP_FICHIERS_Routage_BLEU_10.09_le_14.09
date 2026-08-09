import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { api, ReportItem } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";
import { formatTimeAgo } from "@/src/lib/coords";
import { showToast } from "@/src/components/Toast";
import { REPORT_TYPES } from "@/src/lib/report-types";

type Friend = {
  user_id: string;
  pseudo: string;
  picture: string;
  rank_label: string;
  points: number;
  reliability_score: number;
  referral_bonus_paid: boolean;
  created_at: string | null;
  last_open_day: string | null;
};

/**
 * Phase 3a — friend detail sheet.
 *
 * Guardrail: the backend refuses to expose a user who wasn't referred by the
 * caller, so a 403 sends the visitor back to the friends list with a toast.
 */
export default function FriendDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [friend, setFriend] = useState<Friend | null>(null);
  const [lastReports, setLastReports] = useState<ReportItem[]>([]);
  const [lastConfirms, setLastConfirms] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const r = await api.getFriendDetail(String(id));
      setFriend(r.friend);
      setLastReports(r.last_reports);
      setLastConfirms(r.last_confirmations);
    } catch (e) {
      showToast("error", (e as Error).message);
      router.back();
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => { void load(); }, [load]);

  if (loading || !friend) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={theme.primary} />
      </View>
    );
  }

  const lastSeenLabel = friend.last_open_day
    ? formatTimeAgo(friend.last_open_day + "T12:00:00Z")
    : "jamais connecté";

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          style={styles.iconBtn}
          testID="friend-detail-back"
        >
          <Ionicons name="chevron-back" size={24} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.title} numberOfLines={1}>{friend.pseudo}</Text>
        <View style={styles.iconBtn} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* ── Identity card ────────────────────────────────────────── */}
        <View style={styles.card}>
          <View style={styles.avatar}>
            <Ionicons name="person" size={36} color={theme.primary} />
            {friend.referral_bonus_paid && (
              <View style={styles.activePill}>
                <Ionicons name="checkmark" size={12} color="#0B132B" />
              </View>
            )}
          </View>
          <Text style={styles.pseudo}>{friend.pseudo}</Text>
          <Text style={styles.rankLabel}>{friend.rank_label}</Text>
          <View style={styles.statsRow}>
            <Stat label="Points" value={String(friend.points)} />
            <Stat label="Fiabilité" value={`${friend.reliability_score}%`} />
            <Stat label="Vu" value={lastSeenLabel} />
          </View>
        </View>

        {/* ── Last reports ─────────────────────────────────────────── */}
        <Section title="3 derniers signalements">
          {lastReports.length === 0 ? (
            <Text style={styles.empty}>Aucun signalement</Text>
          ) : (
            lastReports.map((r) => <ReportRow key={r.id} r={r} onPress={() => router.push(`/report/${r.id}`)} />)
          )}
        </Section>

        {/* ── Last confirmations ───────────────────────────────────── */}
        <Section title="3 dernières confirmations">
          {lastConfirms.length === 0 ? (
            <Text style={styles.empty}>Aucune confirmation</Text>
          ) : (
            lastConfirms.map((r) => <ReportRow key={r.id} r={r} onPress={() => router.push(`/report/${r.id}`)} />)
          )}
        </Section>

        <Text style={styles.footer}>
          {"Le partage de position en direct arrivera avec la Phase 3 (Groupes privés)."}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue} numberOfLines={1}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: 8 }}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={{ gap: 8 }}>{children}</View>
    </View>
  );
}

function ReportRow({ r, onPress }: { r: ReportItem; onPress: () => void }) {
  const typeMeta = REPORT_TYPES.find((t) => t.id === r.type);
  return (
    <TouchableOpacity style={styles.reportRow} onPress={onPress} activeOpacity={0.85}>
      <View style={[styles.reportIcon, { backgroundColor: typeMeta?.color || theme.primary }]}>
        <Ionicons name={(typeMeta?.icon ?? "alert") as never} size={18} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.reportLabel} numberOfLines={1}>{typeMeta?.label ?? r.type}</Text>
        <Text style={styles.reportMeta}>{formatTimeAgo(r.created_at)}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={theme.textDim} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  iconBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  title: { color: theme.text, fontWeight: "800", fontSize: 16, flex: 1, textAlign: "center" },
  scroll: { padding: spacing.md, paddingBottom: spacing.xl, gap: spacing.lg },
  card: {
    backgroundColor: theme.bg2, borderRadius: radii.lg, padding: spacing.lg,
    alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: theme.border,
  },
  avatar: {
    width: 72, height: 72, borderRadius: 36, backgroundColor: theme.bg,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.primary, position: "relative",
  },
  activePill: {
    position: "absolute", right: -2, bottom: -2,
    width: 22, height: 22, borderRadius: 11,
    backgroundColor: theme.success,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.bg2,
  },
  pseudo: { color: theme.text, fontWeight: "900", fontSize: 20 },
  rankLabel: { color: theme.primary, fontWeight: "700", fontSize: 13 },
  statsRow: {
    flexDirection: "row", gap: spacing.sm,
    width: "100%", marginTop: spacing.sm,
  },
  stat: {
    flex: 1, backgroundColor: theme.bg, borderRadius: radii.md,
    paddingVertical: 10, paddingHorizontal: 8, alignItems: "center",
    borderWidth: 1, borderColor: theme.border, minHeight: 60, justifyContent: "center",
  },
  statValue: { color: theme.text, fontWeight: "900", fontSize: 15 },
  statLabel: { color: theme.textDim, fontSize: 10, marginTop: 2, fontWeight: "700", letterSpacing: 0.5 },
  sectionTitle: { color: theme.text, fontWeight: "800", fontSize: 14, letterSpacing: 0.4 },
  empty: {
    color: theme.textDim, fontSize: 13, fontStyle: "italic",
    padding: spacing.md, backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  reportRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: spacing.sm, backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  reportIcon: {
    width: 34, height: 34, borderRadius: 17,
    alignItems: "center", justifyContent: "center",
  },
  reportLabel: { color: theme.text, fontWeight: "700", fontSize: 13 },
  reportMeta: { color: theme.textMute, fontSize: 11, marginTop: 2 },
  footer: {
    color: theme.textMute, fontSize: 11, fontStyle: "italic",
    textAlign: "center", marginTop: spacing.md,
  },
});
