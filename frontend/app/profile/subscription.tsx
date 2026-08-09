/**
 * Phase B — Abonnement / Viral referral screen.
 *
 * Shows the user their Premium status and full referral history:
 *   • Header card : Premium état actuel (Free / Premium — valid until X)
 *   • Progress bloc : mois cumulés / cap 12 + parrainages pending / cap 10
 *   • Share pill : « Parrainer un ami » (Share sheet pré-rempli avec code)
 *   • List : each referral with referee avatar + pseudo + status chip
 *
 * States (from backend `status`) → visual chip mapping :
 *   pending_report          → « Inscrit — en attente de son 1er signalement » (gris)
 *   pending_confirmation    → « Signalement en attente d'une confirmation externe » (orange)
 *   confirmed               → « +1 mois débloqué ! » (vert)
 *   rejected_farm           → « Non éligible (plafond atteint) » (rouge doux)
 *   expired                 → « Expiré » (gris clair)
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, FlatList, Image,
  StyleSheet, Text, TouchableOpacity, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Clipboard from "expo-clipboard";

import { api, type ReferralItem, type ReferralStatus, type SubscriptionState } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { radii, spacing, theme } from "@/src/lib/theme";
import { pickAndUploadAvatar } from "@/src/lib/avatar";
import { showToast } from "@/src/components/Toast";

const STATUS_CONFIG: Record<ReferralStatus, {
  label: string;
  color: string;
  bg: string;
  icon: keyof typeof Ionicons.glyphMap;
}> = {
  pending_report: {
    label: "En attente de son 1er signalement",
    color: theme.textDim, bg: "rgba(255,255,255,0.06)",
    icon: "hourglass-outline",
  },
  pending_confirmation: {
    label: "Attente d'une confirmation externe",
    color: theme.warning, bg: "rgba(244,162,97,0.10)",
    icon: "time-outline",
  },
  confirmed: {
    label: "Filleul actif — +20 pts crédités",
    color: "#2EC4B6", bg: "rgba(46,196,182,0.14)",
    icon: "checkmark-circle",
  },
  rejected_farm: {
    label: "Non éligible (plafond atteint)",
    color: theme.danger, bg: "rgba(230,57,70,0.08)",
    icon: "close-circle-outline",
  },
  expired: {
    label: "Expiré",
    color: theme.textMute, bg: "rgba(255,255,255,0.04)",
    icon: "close-outline",
  },
};

function pctClamp(x: number, cap: number): number {
  if (!cap) return 0;
  return Math.max(0, Math.min(100, Math.round((x / cap) * 100)));
}

function humanDate(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "long", year: "numeric" });
  } catch { return ""; }
}

export default function SubscriptionScreen() {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [state, setState] = useState<SubscriptionState | null>(null);
  const [referrals, setReferrals] = useState<ReferralItem[]>([]);
  const [avatarUploading, setAvatarUploading] = useState(false);

  const changeAvatar = useCallback(async () => {
    setAvatarUploading(true);
    try {
      const updated = await pickAndUploadAvatar();
      if (updated) {
        setUser(updated);
        showToast("success", "Avatar mis à jour");
      }
    } catch (e) {
      showToast("error", (e as Error).message || "Upload échoué");
    } finally {
      setAvatarUploading(false);
    }
  }, [setUser]);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await api.getSubscription();
      setState(r.subscription);
      setReferrals(r.referrals);
    } catch (e) {
      setErr((e as Error).message || "Impossible de charger l'abonnement");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const copyCode = async () => {
    if (!user?.referral_code) return;
    await Clipboard.setStringAsync(user.referral_code);
    Alert.alert("Copié", `Code parrainage : ${user.referral_code}`);
  };

  // Bouton « Parrainer » → mécanique unique contacts + SMS groupé (l'écran
  // /share-invite garde un lien « Partager autrement… » pour les autres canaux).
  const share = () => router.push("/share-invite");

  const renderReferral = ({ item }: { item: ReferralItem }) => {
    const cfg = STATUS_CONFIG[item.status];
    return (
      <View style={styles.refRow}>
        {item.referee.picture ? (
          <Image source={{ uri: item.referee.picture }} style={styles.avatar} />
        ) : (
          <View style={[styles.avatar, styles.avatarFallback]}>
            <Text style={{ color: theme.primary, fontWeight: "800" }}>
              {(item.referee.pseudo || "?").slice(0, 1).toUpperCase()}
            </Text>
          </View>
        )}
        <View style={{ flex: 1 }}>
          <Text style={styles.refPseudo} numberOfLines={1}>{item.referee.pseudo}</Text>
          <View style={[styles.chip, { backgroundColor: cfg.bg }]}>
            <Ionicons name={cfg.icon} size={11} color={cfg.color} />
            <Text style={[styles.chipTxt, { color: cfg.color }]}>{cfg.label}</Text>
          </View>
        </View>
        {item.status === "confirmed" ? (
          <View style={styles.monthPill}>
            <Text style={styles.monthPillTxt}>+20 pts</Text>
          </View>
        ) : null}
      </View>
    );
  };

  const s = state;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.hBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Abonnement</Text>
        <TouchableOpacity onPress={load} style={styles.hBtn} hitSlop={12}>
          <Ionicons name="refresh" size={22} color={theme.textDim} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.centered}><ActivityIndicator color={theme.primary} /></View>
      ) : err ? (
        <View style={styles.centered}>
          <Ionicons name="cloud-offline-outline" size={40} color={theme.textMute} />
          <Text style={styles.errTxt}>{err}</Text>
          <TouchableOpacity style={styles.retry} onPress={load}>
            <Text style={styles.retryTxt}>Réessayer</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={referrals}
          keyExtractor={(r) => r.referral_id}
          renderItem={renderReferral}
          contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}
          ItemSeparatorComponent={() => <View style={styles.sep} />}
          ListHeaderComponent={
            <View>
              {/* ── Hero : photo/avatar modifiable + pseudo + pill Premium ── */}
              <View style={styles.hero} testID="subscription-hero">
                <View style={styles.heroGlow} />
                <View style={styles.heroRing} />
                <TouchableOpacity
                  onPress={changeAvatar}
                  activeOpacity={0.85}
                  style={styles.heroAvatarBtn}
                  testID="subscription-avatar-edit"
                  accessibilityLabel="Changer la photo de profil"
                >
                  {user?.picture ? (
                    <Image source={{ uri: user.picture }} style={styles.heroAvatar} />
                  ) : (
                    <View style={[styles.heroAvatar, styles.heroAvatarFallback]}>
                      <Ionicons name="person" size={46} color={theme.bg} />
                    </View>
                  )}
                  <View style={styles.heroAvatarBadge}>
                    {avatarUploading ? (
                      <ActivityIndicator size="small" color={theme.bg} />
                    ) : (
                      <Ionicons name="camera" size={14} color={theme.bg} />
                    )}
                  </View>
                </TouchableOpacity>
                <Text style={styles.heroPseudo} numberOfLines={1}>
                  {user?.pseudo || user?.name || "Marin"}
                </Text>
                <View style={[styles.heroPill, s?.is_premium ? styles.heroPillOn : styles.heroPillOff]}>
                  <Ionicons
                    name={s?.is_premium ? "diamond" : "diamond-outline"}
                    size={12}
                    color={s?.is_premium ? "#0B132B" : theme.textDim}
                  />
                  <Text style={[styles.heroPillTxt, !s?.is_premium && { color: theme.textDim }]}>
                    {s?.is_premium ? "Membre Premium" : "Premium expiré"}
                  </Text>
                </View>
                <Text style={styles.heroHint}>Touchez la photo pour la changer</Text>
              </View>

              {/* Premium status card — chaque compte est Premium OFFERT 1 an. */}
              <View style={[styles.premiumCard, s?.is_premium && styles.premiumCardActive]}>
                <View style={styles.premiumHead}>
                  <Ionicons
                    name={s?.is_premium ? "diamond" : "diamond-outline"}
                    size={20}
                    color={s?.is_premium ? "#F4A261" : theme.textDim}
                  />
                  <Text style={styles.premiumTitle}>
                    {s?.is_premium
                      ? (s.free_year_active ? "Premium offert" : "Premium actif")
                      : "Premium expiré"}
                  </Text>
                  {s?.free_year_active && (
                    <View style={styles.giftPill}>
                      <Ionicons name="gift" size={11} color="#0B132B" />
                      <Text style={styles.giftPillTxt}>1ʳᵉ année offerte</Text>
                    </View>
                  )}
                </View>
                {s?.is_premium && s.premium_valid_until_iso ? (
                  <Text style={styles.premiumSub}>
                    100 % gratuit, toutes options — valide jusqu&apos;au{" "}
                    <Text style={{ fontWeight: "800", color: theme.text }}>{humanDate(s.premium_valid_until_iso)}</Text>
                    {"  · "}
                    <Text style={{ color: theme.textDim }}>{s.remaining_days} jour{s.remaining_days > 1 ? "s" : ""}</Text>
                  </Text>
                ) : (
                  <Text style={styles.premiumSub}>
                    Prolonge ton Premium avec tes points (100 pts = 1 mois offert) ou
                    renouvelle manuellement — 1,99 €/mois ou 19,90 €/an.
                  </Text>
                )}
              </View>

              {/* Progression points → mois + parrainages en cours */}
              <View style={styles.progressRow}>
                <View style={styles.progressCard}>
                  <Text style={styles.progressLabel}>Prochain mois offert</Text>
                  <View style={styles.progressBarWrap}>
                    <View
                      style={[
                        styles.progressBarFill,
                        { width: `${pctClamp(s?.points_progress || 0, s?.points_per_month || 100)}%`, backgroundColor: "#2EC4B6" },
                      ]}
                    />
                  </View>
                  <Text style={styles.progressCounter}>
                    <Text style={styles.progressBigNum}>{s?.points_progress ?? 0}</Text>
                    {" / "}{s?.points_per_month ?? 100} pts
                  </Text>
                  {(s?.points_months_awarded ?? 0) > 0 && (
                    <Text style={styles.progressBonus}>
                      🎁 {s?.points_months_awarded} mois déjà gagné{(s?.points_months_awarded ?? 0) > 1 ? "s" : ""}
                    </Text>
                  )}
                </View>
                <View style={styles.progressCard}>
                  <Text style={styles.progressLabel}>Parrainages en cours</Text>
                  <View style={styles.progressBarWrap}>
                    <View
                      style={[
                        styles.progressBarFill,
                        { width: `${pctClamp(s?.bonus_months_pending || 0, s?.cap_pending || 10)}%`, backgroundColor: theme.warning },
                      ]}
                    />
                  </View>
                  <Text style={styles.progressCounter}>
                    <Text style={styles.progressBigNum}>{s?.bonus_months_pending ?? 0}</Text>
                    {" / "}{s?.cap_pending ?? 10}
                  </Text>
                </View>
              </View>

              {/* Referral code + share */}
              <View style={styles.shareBlock}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.shareLabel}>Ton code parrainage</Text>
                  <TouchableOpacity onPress={copyCode} activeOpacity={0.8}>
                    <Text style={styles.shareCode}>{user?.referral_code || "…"}</Text>
                    <Text style={styles.shareHint}>Tap pour copier</Text>
                  </TouchableOpacity>
                </View>
                <TouchableOpacity style={styles.shareBtn} onPress={share} testID="subscription-share">
                  <Ionicons name="share-social" size={16} color={theme.bg} />
                  <Text style={styles.shareBtnTxt}>Parrainer</Text>
                </TouchableOpacity>
              </View>

              <View style={styles.rulesCard}>
                <Text style={styles.rulesTitle}>Comment ça marche</Text>
                <Text style={styles.rulesTxt}>
                  🎁 Chaque compte profite du <Text style={{ fontWeight: "800" }}>Premium offert pendant 1 an</Text>.{"\n"}
                  1. Ton filleul s&apos;inscrit avec ton invitation SMS ou ton code{"\n"}
                  2. Il publie son 1er signalement → en attente{"\n"}
                  3. Un marin <Text style={{ fontWeight: "800" }}>externe à ses groupes privés</Text> confirme → <Text style={{ fontWeight: "800", color: "#2EC4B6" }}>+20 pts pour toi</Text>{"\n"}
                  4. Tous les <Text style={{ fontWeight: "800", color: "#2EC4B6" }}>100 pts gagnés = +1 mois de Premium</Text> automatique
                </Text>
                <Text style={styles.rulesFooter}>
                  Max 10 parrainages simultanés en cours. Les points de grade viennent
                  aussi de tes signalements et confirmations — tout compte !
                </Text>
              </View>

              {/* Engagements — paiement & renouvellement, en toute confiance. */}
              <View style={styles.trustCard} testID="subscription-trust">
                {([
                  ["sync-circle-outline", "Aucune tacite reconduction — renouvellement 100 % manuel"],
                  ["lock-closed-outline", "Données de paiement cryptées, jamais conservées"],
                  ["receipt-outline", "Seule votre facture est gardée dans votre compte"],
                ] as const).map(([icon, label]) => (
                  <View key={icon} style={styles.trustRow}>
                    <Ionicons name={icon} size={15} color="#2EC4B6" />
                    <Text style={styles.trustTxt}>{label}</Text>
                  </View>
                ))}
              </View>

              <Text style={styles.sectionTitle}>
                {referrals.length === 0
                  ? "Aucun parrainage pour l'instant"
                  : `${referrals.length} parrainage${referrals.length > 1 ? "s" : ""}`}
              </Text>
            </View>
          }
          ListEmptyComponent={null}
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
  headerTitle: { color: theme.text, fontSize: 17, fontWeight: "800" },
  centered: {
    flex: 1, alignItems: "center", justifyContent: "center", gap: 12,
    padding: spacing.lg,
  },
  errTxt: { color: theme.textDim, textAlign: "center" },
  retry: {
    paddingHorizontal: 20, paddingVertical: 8,
    borderRadius: radii.md, borderWidth: 1, borderColor: theme.border,
  },
  retryTxt: { color: theme.text, fontWeight: "700" },
  // ── Hero avatar (11/07/2026) ──
  hero: {
    alignItems: "center", paddingVertical: 18, marginBottom: 12,
    borderRadius: radii.lg, backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: "rgba(244,162,97,0.35)",
    overflow: "hidden",
  },
  heroGlow: {
    position: "absolute", top: -80, left: -60, right: -60, height: 170,
    borderRadius: 999, backgroundColor: "rgba(244,162,97,0.10)",
  },
  heroRing: {
    position: "absolute", top: 6, width: 128, height: 128, borderRadius: 64,
    borderWidth: 1, borderColor: "rgba(244,162,97,0.30)",
  },
  heroAvatarBtn: { position: "relative" },
  heroAvatar: {
    width: 104, height: 104, borderRadius: 52,
    borderWidth: 3, borderColor: "#F4A261",
  },
  heroAvatarFallback: {
    backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  heroAvatarBadge: {
    position: "absolute", bottom: 2, right: 2, width: 28, height: 28, borderRadius: 14,
    backgroundColor: "#F4A261", alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.bg2,
  },
  heroPseudo: {
    color: theme.text, fontSize: 22, fontWeight: "900",
    marginTop: 10, maxWidth: "85%",
  },
  heroPill: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 5, borderRadius: 999, marginTop: 8,
  },
  heroPillOn: { backgroundColor: "#F4A261" },
  heroPillOff: { backgroundColor: theme.bg3, borderWidth: 1, borderColor: theme.border },
  heroPillTxt: { color: "#0B132B", fontSize: 12, fontWeight: "900", letterSpacing: 0.3 },
  heroHint: { color: theme.textMute, fontSize: 10.5, marginTop: 8 },
  premiumCard: {
    borderRadius: radii.md, padding: spacing.md,
    backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
    marginBottom: 10,
  },
  premiumCardActive: {
    borderColor: "#F4A261",
    backgroundColor: "rgba(244,162,97,0.06)",
  },
  premiumHead: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  premiumTitle: { color: theme.text, fontSize: 17, fontWeight: "900" },
  giftPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#FFD166", paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
  },
  giftPillTxt: { color: "#0B132B", fontSize: 10.5, fontWeight: "900", letterSpacing: 0.3 },
  premiumSub: { color: theme.textDim, fontSize: 12, marginTop: 6, lineHeight: 17 },
  progressRow: {
    flexDirection: "row", gap: 8, marginBottom: 10,
  },
  progressCard: {
    flex: 1, borderRadius: radii.md,
    backgroundColor: theme.bg2, borderColor: theme.border, borderWidth: 1,
    padding: 12,
  },
  progressLabel: { color: theme.textDim, fontSize: 11, fontWeight: "700" },
  progressBarWrap: {
    height: 6, borderRadius: 3, backgroundColor: "rgba(255,255,255,0.06)",
    marginTop: 8, marginBottom: 6, overflow: "hidden",
  },
  progressBarFill: { height: "100%", borderRadius: 3 },
  progressCounter: { color: theme.textDim, fontSize: 12 },
  progressBigNum: { color: theme.text, fontWeight: "900", fontSize: 15 },
  progressBonus: { color: "#FFD166", fontSize: 11, fontWeight: "800", marginTop: 4 },
  shareBlock: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12, borderRadius: radii.md,
    backgroundColor: theme.bg2, borderColor: theme.border, borderWidth: 1,
    marginBottom: 10,
  },
  shareLabel: { color: theme.textDim, fontSize: 11, fontWeight: "700" },
  shareCode: {
    color: theme.primary, fontSize: 22, fontWeight: "900",
    letterSpacing: 3, marginTop: 4,
  },
  shareHint: { color: theme.textMute, fontSize: 10, marginTop: 2 },
  shareBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.primary,
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: radii.sm,
  },
  shareBtnTxt: { color: theme.bg, fontSize: 13, fontWeight: "800" },
  rulesCard: {
    borderRadius: radii.md, padding: 12,
    backgroundColor: "rgba(72,202,228,0.06)",
    borderWidth: 1, borderColor: "rgba(72,202,228,0.25)",
    marginBottom: 14,
  },
  rulesTitle: { color: theme.primary, fontSize: 12, fontWeight: "800", marginBottom: 6 },
  rulesTxt: { color: theme.text, fontSize: 12, lineHeight: 18 },
  rulesFooter: { color: theme.textDim, fontSize: 11, marginTop: 8 },
  trustCard: {
    borderRadius: radii.md, padding: 12, gap: 8,
    backgroundColor: "rgba(46,196,182,0.05)",
    borderWidth: 1, borderColor: "rgba(46,196,182,0.25)",
    marginBottom: 14,
  },
  trustRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  trustTxt: { color: theme.textDim, fontSize: 12, fontWeight: "600", flex: 1, lineHeight: 16 },
  sectionTitle: {
    color: theme.textDim, fontSize: 11, fontWeight: "800",
    letterSpacing: 0.6, textTransform: "uppercase",
    marginTop: 4, marginBottom: 6,
  },
  refRow: {
    flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 10,
  },
  avatar: { width: 40, height: 40, borderRadius: 20 },
  avatarFallback: {
    backgroundColor: theme.bg3, alignItems: "center", justifyContent: "center",
  },
  refPseudo: { color: theme.text, fontSize: 14, fontWeight: "700" },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: radii.sm, alignSelf: "flex-start", marginTop: 4,
  },
  chipTxt: { fontSize: 11, fontWeight: "700" },
  monthPill: {
    backgroundColor: "#2EC4B6",
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: radii.sm,
  },
  monthPillTxt: { color: "#0B132B", fontSize: 11, fontWeight: "900" },
  sep: { height: 1, backgroundColor: theme.border, marginLeft: 52 },
});
