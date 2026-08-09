// SignalMar — Page web PUBLIQUE d'un signalement : /s/[CODE] (12/07/2026).
//
// Cible des liens imprimés sur les posts viraux (Instagram/FB/X). Accessible
// SANS compte : montre un aperçu anonymisé (extrait 100 caractères, zone
// approximative floutée, pseudo) et convertit le visiteur en téléchargement.
// Un utilisateur déjà connecté peut ouvrir le signalement complet dans l'app.

import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api, type PublicReportPreview } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { theme, spacing, radii } from "@/src/lib/theme";
import { TYPE_BY_ID, type ReportTypeId } from "@/src/lib/report-types";
import { formatTimeAgo } from "@/src/lib/coords";
import { approxZone, approxTileUrl } from "@/src/components/SocialPostCard";
import { signalMarInviteUrl } from "@/src/lib/share-app";

const EMOJI: Record<string, string> = {
  autorites: "\u{1F6E1}\uFE0F", secours: "\u{1F6DF}", obstacle_nav: "\u26A0\uFE0F",
  animal_marin: "\u{1F42C}", pollution: "\u{1F6E2}\uFE0F", autre: "\u2049\uFE0F",
};

export default function PublicReportPage() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const [preview, setPreview] = useState<PublicReportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    api.getPublicReportPreview(String(code))
      .then((p) => { if (!cancelled) setPreview(p); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [code]);

  // Utilisateur déjà connecté → ouvrir le détail complet dans l'app.
  async function openInApp() {
    if (!preview || opening) return;
    setOpening(true);
    try {
      const r = await api.getReportByCode(preview.short_id);
      router.push(`/report/${r.id}`);
    } catch {
      setOpening(false);
    }
  }

  const t = preview ? TYPE_BY_ID[preview.type as ReportTypeId] : null;
  const color = t?.color || theme.primary;
  const emoji = preview ? (EMOJI[preview.type] || "\u2693") : "\u2693";
  const over = preview && preview.status !== "active";

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        {/* En-tête de marque. */}
        <View style={styles.brandRow}>
          <View style={styles.brandPill}>
            <Ionicons name="boat" size={16} color={theme.bg} />
            <Text style={styles.brandTxt}>SignalMar</Text>
          </View>
          <Text style={styles.tagline}>L&apos;appli collaborative des marins</Text>
        </View>

        {!preview && !error && (
          <View style={styles.center}>
            <ActivityIndicator color={theme.primary} size="large" />
            <Text style={styles.loadingTxt}>Chargement du signalement…</Text>
          </View>
        )}

        {error && (
          <View style={styles.card} testID="public-report-error">
            <Ionicons name="help-circle-outline" size={40} color={theme.textDim} />
            <Text style={styles.errTitle}>Signalement introuvable</Text>
            <Text style={styles.errTxt}>{error}</Text>
          </View>
        )}

        {preview && (
          <View style={styles.card} testID="public-report-card">
            {preview.photo ? (
              <Image source={{ uri: preview.photo }} style={styles.photo} resizeMode="cover" />
            ) : null}

            <View style={styles.cardBody}>
              <View style={styles.typeRow}>
                <View style={[styles.typePill, { backgroundColor: color }]}>
                  <Text style={styles.typeEmoji}>{emoji}</Text>
                  <Text style={styles.typeTxt} numberOfLines={1}>
                    {(t?.label || preview.type).toUpperCase()}
                  </Text>
                </View>
                {over ? (
                  <View style={styles.endedPill}>
                    <Text style={styles.endedTxt}>Terminé</Text>
                  </View>
                ) : null}
              </View>

              <Text style={styles.meta}>
                Signalé {formatTimeAgo(preview.created_at)} par {preview.author_pseudo}
                {preview.confirm_count > 0
                  ? ` · ${preview.confirm_count} confirmation${preview.confirm_count > 1 ? "s" : ""}`
                  : ""}
              </Text>

              {preview.description_excerpt ? (
                <Text style={styles.excerpt}>
                  {"\u00AB "}{preview.description_excerpt}{" \u00BB"}
                </Text>
              ) : null}

              {/* Zone approximative FLOUTÉE — la position exacte n'est
                  visible que dans l'app. */}
              <View style={styles.mapStrip}>
                <Image
                  source={{ uri: approxTileUrl(preview.approx_lat, preview.approx_lng) }}
                  style={StyleSheet.absoluteFill}
                  resizeMode="cover"
                  blurRadius={6}
                />
                <View style={styles.mapVeil} />
                <Ionicons name="location" size={18} color={theme.warning} />
                <Text style={styles.zoneTxt}>
                  {approxZone(preview.approx_lat, preview.approx_lng)} (approx.)
                </Text>
              </View>
              <View style={styles.lockRow}>
                <Ionicons name="lock-closed" size={12} color={theme.textDim} />
                <Text style={styles.lockTxt}>
                  Position exacte, photos et suivi en direct dans l&apos;app
                </Text>
              </View>

              <View style={styles.codeRow}>
                <Text style={styles.codeLabel}>Code signalement</Text>
                <Text style={styles.codeTxt}>{preview.short_id}</Text>
              </View>
            </View>
          </View>
        )}

        {/* CTA conversion. */}
        <View style={styles.ctaBlock}>
          <TouchableOpacity
            style={styles.ctaBtn}
            onPress={() => Linking.openURL(signalMarInviteUrl())}
            activeOpacity={0.85}
            testID="public-report-get-app"
          >
            <Ionicons name="phone-portrait" size={18} color={theme.bg} />
            <Text style={styles.ctaBtnTxt}>Obtenir SignalMar gratuitement</Text>
          </TouchableOpacity>
          <Text style={styles.ctaSub}>
            Disponible sur Android et iPhone — SignalMar.app
          </Text>
          {user && preview ? (
            <TouchableOpacity
              style={styles.openBtn}
              onPress={openInApp}
              disabled={opening}
              testID="public-report-open-app"
            >
              {opening ? (
                <ActivityIndicator color={theme.primary} />
              ) : (
                <>
                  <Ionicons name="open-outline" size={16} color={theme.primary} />
                  <Text style={styles.openBtnTxt}>Voir en détail dans l&apos;app</Text>
                </>
              )}
            </TouchableOpacity>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.bg },
  scroll: {
    padding: spacing.md, gap: spacing.md,
    width: "100%", maxWidth: 520, alignSelf: "center",
  },
  brandRow: { alignItems: "center", gap: 6, marginTop: spacing.sm },
  brandPill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.primary, borderRadius: radii.pill,
    paddingHorizontal: 14, paddingVertical: 6,
  },
  brandTxt: { color: theme.bg, fontWeight: "900", fontSize: 16 },
  tagline: { color: theme.textDim, fontSize: 12, fontWeight: "600" },
  center: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl },
  loadingTxt: { color: theme.textDim, fontSize: 14 },
  card: {
    backgroundColor: theme.bg2, borderRadius: radii.lg, overflow: "hidden",
    borderWidth: 1, borderColor: theme.border, alignItems: "stretch",
  },
  errTitle: {
    color: theme.text, fontWeight: "800", fontSize: 17,
    textAlign: "center", marginTop: spacing.sm,
  },
  errTxt: {
    color: theme.textDim, fontSize: 14, textAlign: "center",
    padding: spacing.md, paddingTop: 4,
  },
  photo: { width: "100%", height: 200, backgroundColor: theme.bg3 },
  cardBody: { padding: spacing.md, gap: spacing.sm },
  typeRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  typePill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderRadius: radii.pill, paddingHorizontal: 12, paddingVertical: 6,
  },
  typeEmoji: { fontSize: 14 },
  typeTxt: { color: theme.bg, fontWeight: "900", fontSize: 14, letterSpacing: 0.5 },
  endedPill: {
    backgroundColor: theme.bg3, borderRadius: radii.pill,
    paddingHorizontal: 10, paddingVertical: 5,
    borderWidth: 1, borderColor: theme.borderStrong,
  },
  endedTxt: { color: theme.textDim, fontWeight: "800", fontSize: 11 },
  meta: { color: theme.textDim, fontSize: 13, fontWeight: "600" },
  excerpt: {
    color: theme.text, fontSize: 15, fontStyle: "italic",
    lineHeight: 21, fontWeight: "500",
  },
  mapStrip: {
    height: 90, borderRadius: radii.md, overflow: "hidden",
    alignItems: "center", justifyContent: "center", gap: 4,
    borderWidth: 1, borderColor: theme.borderStrong,
  },
  mapVeil: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(11,19,43,0.35)" },
  zoneTxt: { color: theme.text, fontWeight: "800", fontSize: 13 },
  lockRow: { flexDirection: "row", alignItems: "center", gap: 5, justifyContent: "center" },
  lockTxt: { color: theme.textDim, fontSize: 11.5, fontWeight: "600" },
  codeRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: theme.bg, borderRadius: radii.md,
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderWidth: 1, borderColor: theme.border,
  },
  codeLabel: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  codeTxt: { color: theme.primary, fontWeight: "900", fontSize: 16, letterSpacing: 2 },
  ctaBlock: { gap: spacing.sm, alignItems: "center" },
  ctaBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.warning, borderRadius: radii.md,
    paddingVertical: 14, width: "100%",
  },
  ctaBtnTxt: { color: theme.bg, fontWeight: "900", fontSize: 16 },
  ctaSub: { color: theme.textDim, fontSize: 12, fontWeight: "600" },
  openBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderRadius: radii.md, paddingVertical: 12, width: "100%",
    borderWidth: 1, borderColor: theme.primary,
  },
  openBtnTxt: { color: theme.primary, fontWeight: "800", fontSize: 14 },
});
