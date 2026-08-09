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
import { Stack, useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth/AuthContext";
import { api } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";
import {
  RELIABILITY_DEFAULT,
  RELIABILITY_MAX,
  RELIABILITY_MIN,
  reliabilityPct,
  reliabilityTier,
} from "@/src/lib/reliability";
import { formatTimeAgo } from "@/src/lib/coords";

type HistoryItem = {
  ts: string;
  delta_points: number;
  delta_reliability: number;
  reason: string;
  report_id: string | null;
};

/**
 * SignalMar — page "Indice de fiabilité".
 *
 * V1.2 (Phase 2 Gamification): full rules table + last-10 events journal.
 */
export default function ReliabilityScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const score = user?.reliability_score ?? RELIABILITY_DEFAULT;
  const tier = reliabilityTier(score);
  const pct = reliabilityPct(score);

  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  const loadHistory = useCallback(async () => {
    try {
      const r = await api.pointsHistory(10);
      setHistory(r.items);
    } catch {
      /* silent — non-critical */
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { void loadHistory(); }, [loadHistory]));

  useEffect(() => { void loadHistory(); }, [loadHistory]);

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          style={styles.iconBtn}
          testID="reliability-back"
        >
          <Ionicons name="chevron-back" size={24} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Points & Fiabilité</Text>
        <View style={styles.iconBtn} />
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        {/* ── Score visuel ─────────────────────────────────────────── */}
        <View style={[styles.scoreCard, { borderColor: tier.color }]}>
          <View style={[styles.scoreBadge, { backgroundColor: tier.color }]}>
            <Ionicons name={tier.icon as never} size={28} color="#0B132B" />
          </View>
          <Text style={styles.scoreLabel}>Votre indice</Text>
          <Text style={styles.scoreNumber}>
            {score}
            <Text style={styles.scoreDenom}>%</Text>
          </Text>
          <Text style={[styles.tierLabel, { color: tier.color }]}>{tier.label}</Text>
          <Text style={styles.tierDesc}>{tier.description}</Text>
          <View style={styles.scaleBar}>
            <View
              style={[
                styles.scaleFill,
                { width: `${pct}%`, backgroundColor: tier.color },
              ]}
            />
          </View>
          <View style={styles.scaleRow}>
            <Text style={styles.scaleEnd}>{RELIABILITY_MIN}%</Text>
            <Text style={styles.scaleEnd}>{RELIABILITY_MAX}%</Text>
          </View>
          <Text style={styles.subtle}>
            {"Tout le monde commence à "}{RELIABILITY_DEFAULT}{" %. L'indice évolue en positif ou en négatif selon la validation communautaire de vos signalements, borné entre 0 % et 100 %."}
          </Text>
        </View>

        {/* ── Historique récent ────────────────────────────────────── */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Historique récent</Text>
          {loadingHistory ? (
            <View style={styles.centerRow}>
              <ActivityIndicator size="small" color={theme.primary} />
            </View>
          ) : history.length === 0 ? (
            <Text style={styles.empty}>
              {"Aucune activité récente. Ouvrez l'application chaque jour pour gagner des points !"}
            </Text>
          ) : (
            <View style={{ gap: 8 }}>
              {history.map((h, i) => {
                const positive = (h.delta_points + h.delta_reliability) >= 0;
                const iconName = positive ? "arrow-up-circle" : "arrow-down-circle";
                const color = positive ? theme.primary : theme.danger;
                return (
                  <View key={`${h.ts}-${i}`} style={styles.histRow}>
                    <View style={[styles.histIcon, { backgroundColor: color + "22" }]}>
                      <Ionicons name={iconName as never} size={20} color={color} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.histReason} numberOfLines={2}>{h.reason}</Text>
                      <Text style={styles.histWhen}>{formatTimeAgo(h.ts)}</Text>
                    </View>
                    <View style={{ alignItems: "flex-end" }}>
                      {h.delta_points !== 0 ? (
                        <Text style={[styles.histDelta, { color }]}>
                          {h.delta_points > 0 ? "+" : ""}{h.delta_points} pt{Math.abs(h.delta_points) > 1 ? "s" : ""}
                        </Text>
                      ) : null}
                      {h.delta_reliability !== 0 ? (
                        <Text style={[styles.histDeltaRel, { color }]}>
                          {h.delta_reliability > 0 ? "+" : ""}{h.delta_reliability} %
                        </Text>
                      ) : null}
                    </View>
                  </View>
                );
              })}
            </View>
          )}
        </View>

        {/* ── Règle des points de grade ────────────────────────────── */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Points de grade — comment gagner ?</Text>
          <RuleRow icon="sunny-outline" text="Ouvrir l'application" delta="+1" color={theme.primary} />
          <RuleRow icon="flame" text="3 jours de suite" delta="+4 bonus" color={theme.primary} />
          <RuleRow icon="star" text="1er signalement à vie" delta="+10" color={theme.primary} />
          <RuleRow icon="megaphone" text="Chaque signalement suivant" delta="+5" color={theme.primary} />
          <RuleRow icon="checkmark-done" text="Confirmer un signalement" delta="+2" color={theme.primary} sub="Max 10 confirmations récompensées / jour" />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Points de grade — comment perdre ?</Text>
          <RuleRow icon="hourglass-outline" text="Inactivité 30 jours" delta="−1" color={theme.danger} />
          <RuleRow icon="close-circle" text="Signalement déclaré faux" delta="−10" color={theme.danger} />
          <RuleRow icon="shield-half" text="Contenu modéré" delta="−30" color={theme.danger} />
          <RuleRow icon="alert-circle" text="Avertissement (3ᵉ modération / 30 j)" delta="−100" color={theme.danger} />
        </View>

        {/* ── Règle de fiabilité ───────────────────────────────────── */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Indice de fiabilité — évolution</Text>
          <RuleRow icon="thumbs-up" text="Signalement confirmé par un autre" delta="+3 %" color={theme.primary} />
          <RuleRow icon="thumbs-down" text="Signalement infirmé (< 1h)" delta="−2 %" color={theme.danger} />
          <RuleRow icon="warning" text="Déclaré faux (≥ 2 infirmations en < 1h)" delta="−10 %" color={theme.danger} />
          <Text style={styles.body}>
            {"Plus votre indice est fort, plus vos signalements résistent aux infirmations. Un indice élevé donne aussi accès à des privilèges (édition du cap sur les autorités, etc.)."}
          </Text>
        </View>

        {/* ── Détails compte ────────────────────────────────────────── */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{"Détails de votre compte"}</Text>
          <View style={styles.kvRow}>
            <Text style={styles.kvKey}>Points de grade</Text>
            <Text style={styles.kvVal}>{user?.points ?? 0}</Text>
          </View>
          <View style={styles.kvRow}>
            <Text style={styles.kvKey}>Rang actuel</Text>
            <Text style={styles.kvVal}>{user?.rank_label ?? "—"}</Text>
          </View>
          <View style={styles.kvRow}>
            <Text style={styles.kvKey}>Indice de fiabilité</Text>
            <Text style={[styles.kvVal, { color: tier.color }]}>{score} / {RELIABILITY_MAX} %</Text>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function RuleRow({
  icon, text, delta, color, sub,
}: {
  icon: string;
  text: string;
  delta: string;
  color: string;
  sub?: string;
}) {
  return (
    <View style={styles.ruleRow}>
      <View style={[styles.ruleIcon, { backgroundColor: color + "22" }]}>
        <Ionicons name={icon as never} size={18} color={color} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.ruleText}>{text}</Text>
        {sub ? <Text style={styles.ruleSub}>{sub}</Text> : null}
      </View>
      <Text style={[styles.ruleDelta, { color }]}>{delta}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  iconBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  title: { color: theme.text, fontWeight: "800", fontSize: 16, letterSpacing: 0.3 },
  scroll: { padding: spacing.md, paddingBottom: spacing.xl, gap: spacing.lg },
  scoreCard: {
    backgroundColor: theme.bg2, borderRadius: radii.lg,
    borderWidth: 2, padding: spacing.lg, alignItems: "center", gap: 8,
  },
  scoreBadge: {
    width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center",
    marginBottom: 6,
  },
  scoreLabel: { color: theme.textDim, fontSize: 12, fontWeight: "600", letterSpacing: 0.5 },
  scoreNumber: { color: theme.text, fontSize: 48, fontWeight: "900", lineHeight: 52 },
  scoreDenom: { color: theme.textDim, fontSize: 22, fontWeight: "700" },
  tierLabel: { fontWeight: "800", fontSize: 16, marginTop: 2 },
  tierDesc: { color: theme.textDim, fontSize: 13, textAlign: "center", marginTop: 2 },
  scaleBar: {
    width: "100%", height: 8, backgroundColor: theme.border, borderRadius: 4,
    marginTop: 14, overflow: "hidden",
  },
  scaleFill: { height: "100%" },
  scaleRow: { width: "100%", flexDirection: "row", justifyContent: "space-between", marginTop: 4 },
  scaleEnd: { color: theme.textMute, fontSize: 10, fontWeight: "700" },
  subtle: { color: theme.textDim, fontSize: 11, marginTop: 10, fontStyle: "italic", textAlign: "center" },
  section: { gap: 10 },
  sectionTitle: { color: theme.text, fontWeight: "800", fontSize: 14, letterSpacing: 0.4 },
  body: { color: theme.textDim, fontSize: 13, lineHeight: 19, marginTop: 4 },
  centerRow: { alignItems: "center", justifyContent: "center", paddingVertical: spacing.md },
  empty: {
    color: theme.textDim, fontSize: 13, fontStyle: "italic",
    padding: spacing.md, backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  histRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: spacing.sm, backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  histIcon: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
  },
  histReason: { color: theme.text, fontWeight: "700", fontSize: 13 },
  histWhen: { color: theme.textMute, fontSize: 11, marginTop: 2 },
  histDelta: { fontWeight: "900", fontSize: 13 },
  histDeltaRel: { fontWeight: "800", fontSize: 11, marginTop: 2 },
  ruleRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 8, paddingHorizontal: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  ruleIcon: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: "center", justifyContent: "center",
  },
  ruleText: { color: theme.text, fontSize: 13, fontWeight: "600" },
  ruleSub: { color: theme.textMute, fontSize: 11, marginTop: 2 },
  ruleDelta: { fontWeight: "900", fontSize: 14 },
  kvRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  kvKey: { color: theme.textDim, fontSize: 13, flex: 1 },
  kvVal: { color: theme.text, fontWeight: "800", fontSize: 14 },
});
