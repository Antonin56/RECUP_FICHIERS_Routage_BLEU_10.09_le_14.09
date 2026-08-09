/**
 * Onglet Profil — refonte 10/07/2026 (maquette utilisateur).
 *
 * Structure (de haut en bas) :
 *   • Carte profil : engrenage Réglages (haut-droit), pills « Mes amis » /
 *     « Groupes » de part et d'autre de l'avatar (éditable, badge appareil
 *     photo), pseudo → page Abonnement (l'édition du pseudo vit désormais
 *     dans Réglages, 11/07), pill grade + points (→ RanksModal), pill
 *     indice de fiabilité (→ /profile/reliability), tagline de partage
 *     et gros bouton « Partager SignalMar ».
 *   • 2 tuiles stats : Signalements / Confirmations.
 *   • MON HISTORIQUE — REPLIÉ par défaut, double flèche pour déplier/replier,
 *     pagination 5 par page (20 max).
 *   • Se déconnecter (rouge).
 *   • Rangées : Abonnement & parrainage · Diagnostic & logs · Comptes de
 *     test (whitelist QA).
 *   • Liens discrets côte à côte : Voir la démo · Revoir l'intro.
 *   • Disclaimer sécurité.
 */
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api, type ReportItem, type SavedRoute, type User } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { radii, spacing, theme } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";
import { RanksModal } from "@/src/components/RanksModal";
import { rankForPoints } from "@/src/lib/marine-ranks";
import { reliabilityTier, RELIABILITY_DEFAULT } from "@/src/lib/reliability";
import { ShareAppVisual } from "@/src/components/ShareAppVisual";
import { pickAndUploadAvatar } from "@/src/lib/avatar";
import { TYPE_BY_ID, type ReportTypeId } from "@/src/lib/report-types";
import { formatTimeAgo } from "@/src/lib/coords";
import { isTestAccount } from "@/src/lib/test-accounts";
import { getWarmLocation } from "@/src/lib/gps-warmup";

const HISTORY_PAGE_SIZE = 5;
const HISTORY_MAX_TOTAL = 20;

type ProfilePayload = User & {
  reports_count: number;
  confirmations_count: number;
  history: ReportItem[];
  history_total: number;
};

export default function ProfileScreen() {
  const router = useRouter();
  const { user, setUser, signOut, demoMode } = useAuth();
  const [data, setData] = useState<ProfilePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [ranksOpen, setRanksOpen] = useState(false);
  // Historique — REPLIÉ par défaut (maquette 10/07).
  const [histOpen, setHistOpen] = useState(false);
  const [page, setPage] = useState(0);
  const [pageLoading, setPageLoading] = useState(false);
  // 13/07/2026 — lot de 5 signalements de test d'alarme (whitelist).
  const [alertBatchBusy, setAlertBatchBusy] = useState(false);
  // Mode test BÊTA (19/07/2026) — statut testeur/admin + toggle mode test.
  const [beta, setBeta] = useState<{ is_tester: boolean; is_admin: boolean; test_mode: boolean } | null>(null);
  const [testModeBusy, setTestModeBusy] = useState(false);

  // Crée 5 signalements DÉCLENCHEURS autour de la position courante
  // (600 m / 1 / 3 / 10 / 20 km) — le lot précédent est effacé côté serveur.
  async function createAlertTestBatch() {
    if (alertBatchBusy) return;
    setAlertBatchBusy(true);
    try {
      let fix = getWarmLocation();
      if (!fix) {
        const Location = await import("expo-location");
        const perm = await Location.requestForegroundPermissionsAsync();
        if (!perm.granted) {
          showToast("error", "Position requise pour placer les signalements de test.");
          return;
        }
        const pos = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        fix = {
          lat: pos.coords.latitude, lng: pos.coords.longitude,
          speed: null, heading: null, ts: Date.now(),
        };
      }
      const r = await api.devAlertTestBatch(fix.lat, fix.lng);
      showToast(
        "success",
        `${r.created.length} signalements de test créés (600 m → 20 km)` +
          (r.deleted > 0 ? ` — ${r.deleted} anciens effacés` : ""),
      );
      router.push("/(tabs)/map");
    } catch (e) {
      showToast("error", (e as Error).message || "Création du lot de test impossible.");
    } finally {
      setAlertBatchBusy(false);
    }
  }

  const load = useCallback(async (targetPage: number = 0) => {
    if (demoMode && !user) {
      setLoading(false);
      return;
    }
    try {
      const r = await api.profileMe({
        limit: HISTORY_PAGE_SIZE,
        offset: targetPage * HISTORY_PAGE_SIZE,
      });
      setData(r as ProfilePayload);
      setPage(targetPage);
    } catch (e) {
      showToast("error", (e as Error).message);
    } finally {
      setLoading(false);
      setRefreshing(false);
      setPageLoading(false);
    }
  }, [demoMode, user]);

  useFocusEffect(useCallback(() => { load(0); }, [load]));
  // 26/07 — « Mes routes » : 5 dernières routes enregistrées (focus = à jour).
  const [myRoutes, setMyRoutes] = useState<SavedRoute[] | null>(null);
  useFocusEffect(useCallback(() => {
    if (demoMode && !user) { setMyRoutes([]); return; }
    api.savedRoutes().then((r) => setMyRoutes(r.routes)).catch(() => setMyRoutes([]));
  }, [demoMode, user]));
  // Statut bêta rafraîchi à chaque focus (l'admin peut ajouter/retirer des
  // testeurs à tout moment ; la bascule de compte change aussi le statut).
  useFocusEffect(useCallback(() => {
    api.betaStatus().then(setBeta).catch(() => setBeta(null));
  }, [user?.user_id]));

  async function goToPage(next: number) {
    if (next === page || pageLoading) return;
    setPageLoading(true);
    await load(next);
  }

  async function pickAvatar() {
    setUploadingAvatar(true);
    try {
      const updated = await pickAndUploadAvatar();
      if (updated) {
        setUser(updated);
        setData((d) => (d ? { ...d, picture: updated.picture } : d));
        showToast("success", "Avatar mis à jour");
      }
    } catch (e) {
      showToast("error", (e as Error).message || "Upload échoué");
    } finally {
      setUploadingAvatar(false);
    }
  }

  const logout = () => {
    Alert.alert(
      "Se déconnecter ?",
      "Tu pourras te reconnecter à tout moment.",
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Se déconnecter", style: "destructive",
          onPress: () => {
            signOut();
            router.replace("/(auth)/welcome");
          },
        },
      ],
    );
  };

  // ── Demo-mode shortcut (unchanged from previous UX) ─────────────────
  if (demoMode && !user) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.demoCard}>
          <Ionicons name="eye" size={44} color={theme.warning} />
          <Text style={styles.demoTitle}>Mode démo</Text>
          <Text style={styles.demoBody}>
            Explore SignalMar librement. Crée un compte pour signaler,
            confirmer et gagner des points.
          </Text>
          <TouchableOpacity
            style={styles.primaryCta}
            onPress={() => router.push("/(auth)/login")}
          >
            <Text style={styles.primaryCtaTxt}>Se connecter / Créer un compte</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={theme.primary} />
      </View>
    );
  }

  const pseudo = data?.pseudo || data?.name || user?.pseudo || "Marin";
  const points = data?.points ?? user?.points ?? 0;
  const rankLabel = data?.rank_label || rankForPoints(points).label;
  const reliability = data?.reliability_score ?? RELIABILITY_DEFAULT;
  const tier = reliabilityTier(reliability);
  const historyTotal = Math.min(data?.history_total ?? 0, HISTORY_MAX_TOTAL);
  const totalPages = Math.max(1, Math.ceil(historyTotal / HISTORY_PAGE_SIZE));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(0); }}
            tintColor={theme.primary}
          />
        }
      >
        {/* ── CARTE PROFIL ─────────────────────────────────────────── */}
        <View style={styles.headerCard}>
          {/* Engrenage Réglages — haut-droit de la carte. */}
          <TouchableOpacity
            style={styles.gearBtn}
            onPress={() => router.push("/profile/settings")}
            hitSlop={8}
            testID="profile-open-settings"
            accessibilityLabel="Ouvrir les réglages"
          >
            <Ionicons name="settings-outline" size={20} color={theme.textDim} />
          </TouchableOpacity>

          {/* Pills Mes amis / Groupes de part et d'autre de l'avatar. */}
          <View style={styles.pillsAvatarRow}>
            <TouchableOpacity
              style={[styles.sidePill, styles.friendsPill]}
              onPress={() => router.push("/profile/friends")}
              activeOpacity={0.85}
              testID="profile-friends-btn"
            >
              <Ionicons name="people" size={15} color="#0B132B" />
              <Text style={styles.sidePillText}>Mes amis</Text>
            </TouchableOpacity>

            <TouchableOpacity
              onPress={pickAvatar}
              activeOpacity={0.85}
              style={styles.avatarBtn}
              testID="profile-avatar-edit"
            >
              {data?.picture ? (
                <Image source={{ uri: data.picture }} style={styles.avatar} />
              ) : (
                <View style={[styles.avatar, styles.avatarFallback]}>
                  <Ionicons name="person" size={40} color={theme.bg} />
                </View>
              )}
              <View style={styles.avatarBadge}>
                {uploadingAvatar ? (
                  <ActivityIndicator size="small" color={theme.bg} />
                ) : (
                  <Ionicons name="camera" size={13} color={theme.bg} />
                )}
              </View>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.sidePill, styles.groupsPill]}
              onPress={() => router.push("/groups")}
              activeOpacity={0.85}
              testID="profile-groups-btn"
            >
              <Ionicons name="boat" size={15} color="#0B132B" />
              <Text style={styles.sidePillText}>Groupes</Text>
            </TouchableOpacity>
          </View>

          {/* Pseudo → page Abonnement (11/07 — l'édition vit dans Réglages). */}
          <TouchableOpacity
            style={styles.pseudoRow}
            onPress={() => router.push("/profile/subscription")}
            activeOpacity={0.7}
            testID="profile-pseudo-btn"
            accessibilityLabel="Ouvrir la page Abonnement"
          >
            <Text style={styles.pseudoText} numberOfLines={1}>{pseudo}</Text>
            <Ionicons name="diamond-outline" size={15} color="#F4A261" />
            <Ionicons name="chevron-forward" size={14} color={theme.textMute} />
          </TouchableOpacity>

          {/* Grade + points → échelle des grades. */}
          <TouchableOpacity
            style={styles.rankPill}
            onPress={() => setRanksOpen(true)}
            activeOpacity={0.85}
            testID="profile-rank-badge"
          >
            <Ionicons name="star" size={14} color={theme.bg} />
            <Text style={styles.rankText}>{rankLabel}</Text>
            <View style={styles.pointBubble}>
              <Text style={styles.pointText}>{points} pts</Text>
            </View>
          </TouchableOpacity>

          {/* Indice de fiabilité → page explicative. */}
          <TouchableOpacity
            style={styles.relPill}
            onPress={() => router.push("/profile/reliability")}
            activeOpacity={0.85}
            testID="profile-reliability-badge"
          >
            <Ionicons name="star" size={13} color="#FFD166" />
            <Text style={styles.relText}>
              Indice de fiabilité{" "}
              <Text style={[styles.relScore, { color: tier.color }]}>{reliability}%</Text>
            </Text>
            <Ionicons name="information-circle-outline" size={13} color={theme.textDim} />
          </TouchableOpacity>

          {/* Visuel principal de partage (composant partagé). */}
          <ShareAppVisual />
        </View>

        {/* ── STATS ────────────────────────────────────────────────── */}
        <View style={styles.statsRow}>
          <View style={styles.stat}>
            <Ionicons name="megaphone" size={18} color={theme.primary} />
            <Text style={styles.statValue}>{data?.reports_count ?? 0}</Text>
            <Text style={styles.statLabel}>Signalements</Text>
          </View>
          <View style={styles.stat}>
            <Ionicons name="checkmark-done" size={18} color={theme.primary} />
            <Text style={styles.statValue}>{data?.confirmations_count ?? 0}</Text>
            <Text style={styles.statLabel}>Confirmations</Text>
          </View>
        </View>

        {/* ── MES ROUTES (26/07, demande armateur) — 5 dernières routes
            enregistrées, AU-DESSUS de l'historique. Détails = consultation
            sur la carte (avec bouton retour), Suivre = navigation directe. */}
        <View style={styles.histHeader}>
          <Text style={styles.histTitle}>Mes routes</Text>
          <Text style={styles.histCount}>
            {myRoutes == null ? "…" : myRoutes.length === 0 ? "Aucune route" : `${Math.min(myRoutes.length, 5)} dernière${myRoutes.length > 1 ? "s" : ""}`}
          </Text>
        </View>
        {myRoutes != null && myRoutes.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="navigate-outline" size={32} color={theme.textMute} />
            <Text style={styles.emptyText}>Aucune route enregistrée.</Text>
            <Text style={styles.emptySub}>Créez une route sur la carte puis touchez le signet pour l&apos;enregistrer.</Text>
          </View>
        ) : (
          <View style={{ gap: spacing.sm }}>
            {(myRoutes ?? []).slice(0, 5).map((sr) => (
              <TouchableOpacity
                key={sr.id}
                style={styles.historyRow}
                onPress={() => router.push({ pathname: "/(tabs)/map", params: { saved_route_id: sr.id, saved_route_action: "view" } })}
                testID={`my-route-${sr.id}`}
              >
                <View style={[styles.histDot, { backgroundColor: "#2EC4B6" }]}>
                  <Ionicons name={sr.mode === "manual" ? "create" : "flash"} size={18} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.histRowTitle} numberOfLines={1}>{sr.name}</Text>
                  <Text style={styles.histRowSub}>
                    {(sr.distance_m / 1000).toFixed(1)} km · {sr.mode === "manual" ? "manuelle" : "auto"} · {new Date(sr.created_at).toLocaleDateString("fr-FR")}
                  </Text>
                </View>
                <TouchableOpacity
                  style={styles.routeBtn}
                  onPress={() => router.push({ pathname: "/(tabs)/map", params: { saved_route_id: sr.id, saved_route_action: "view" } })}
                  hitSlop={6}
                  testID={`my-route-details-${sr.id}`}
                >
                  <Ionicons name="map-outline" size={14} color={theme.text} />
                  <Text style={styles.routeBtnTxt}>Détails</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.routeBtn, styles.routeBtnGo]}
                  onPress={() => router.push({ pathname: "/(tabs)/map", params: { saved_route_id: sr.id, saved_route_action: "follow" } })}
                  hitSlop={6}
                  testID={`my-route-follow-${sr.id}`}
                >
                  <Ionicons name="play" size={14} color="#04121F" />
                  <Text style={[styles.routeBtnTxt, { color: "#04121F" }]}>Suivre</Text>
                </TouchableOpacity>
              </TouchableOpacity>
            ))}
          </View>
        )}

        {/* ── MON HISTORIQUE — replié par défaut ───────────────────── */}
        <TouchableOpacity
          style={styles.histHeader}
          onPress={() => setHistOpen((v) => !v)}
          activeOpacity={0.7}
          testID="profile-history-toggle"
          accessibilityLabel={histOpen ? "Replier l'historique" : "Déplier l'historique"}
        >
          <Text style={styles.histTitle}>Mon historique</Text>
          <View style={styles.histRight}>
            {data && (data.reports_count ?? 0) > 0 ? (
              <Text style={styles.histCount}>
                {data.reports_count > HISTORY_MAX_TOTAL
                  ? `${HISTORY_MAX_TOTAL} derniers / ${data.reports_count}`
                  : `${data.reports_count} signalement${data.reports_count > 1 ? "s" : ""}`}
              </Text>
            ) : (
              <Text style={styles.histCount}>Aucun signalement</Text>
            )}
            <Ionicons
              name={histOpen ? "chevron-collapse" : "chevron-expand"}
              size={18}
              color={theme.primary}
            />
          </View>
        </TouchableOpacity>

        {histOpen && (
          (data?.history ?? []).length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="navigate-circle-outline" size={38} color={theme.textMute} />
              <Text style={styles.emptyText}>{"Aucun signalement pour l'instant."}</Text>
              <Text style={styles.emptySub}>Touchez « Signaler » sur la carte pour aider la communauté.</Text>
            </View>
          ) : (
            <View style={{ gap: spacing.sm }}>
              {data?.history.map((r) => {
                const t = TYPE_BY_ID[r.type as ReportTypeId];
                return (
                  <TouchableOpacity
                    key={r.id}
                    style={styles.historyRow}
                    onPress={() => router.push(`/report/${r.id}`)}
                    testID={`history-row-${r.id}`}
                  >
                    <View style={[styles.histDot, { backgroundColor: t?.color || theme.primary }]}>
                      <Ionicons name={(t?.icon as never) || "alert-circle"} size={18} color="#fff" />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.histRowTitle}>{t?.label || r.type}</Text>
                      <Text style={styles.histRowSub}>{formatTimeAgo(r.created_at)} · {r.confirm_count} conf.</Text>
                    </View>
                    <Ionicons name="chevron-forward" size={20} color={theme.textMute} />
                  </TouchableOpacity>
                );
              })}

              {totalPages > 1 && (
                <View style={styles.pager}>
                  <TouchableOpacity
                    style={[styles.pagerBtn, page <= 0 && styles.pagerBtnDisabled]}
                    onPress={() => goToPage(page - 1)}
                    disabled={page <= 0 || pageLoading}
                    testID="history-prev-page"
                  >
                    <Ionicons name="chevron-back" size={18} color={page <= 0 ? theme.textMute : theme.text} />
                    <Text style={[styles.pagerBtnText, page <= 0 && { color: theme.textMute }]}>Précédent</Text>
                  </TouchableOpacity>
                  <View style={styles.pagerLabel}>
                    {pageLoading ? (
                      <ActivityIndicator size="small" color={theme.primary} />
                    ) : (
                      <Text style={styles.pagerLabelText}>
                        Page <Text style={{ color: theme.primary, fontWeight: "900" }}>{page + 1}</Text> / {totalPages}
                      </Text>
                    )}
                  </View>
                  <TouchableOpacity
                    style={[styles.pagerBtn, page >= totalPages - 1 && styles.pagerBtnDisabled]}
                    onPress={() => goToPage(page + 1)}
                    disabled={page >= totalPages - 1 || pageLoading}
                    testID="history-next-page"
                  >
                    <Text style={[styles.pagerBtnText, page >= totalPages - 1 && { color: theme.textMute }]}>Suivant</Text>
                    <Ionicons name="chevron-forward" size={18} color={page >= totalPages - 1 ? theme.textMute : theme.text} />
                  </TouchableOpacity>
                </View>
              )}
            </View>
          )
        )}

        {/* ── DÉCONNEXION ──────────────────────────────────────────── */}
        <TouchableOpacity style={styles.logout} onPress={logout} testID="profile-logout-button">
          <Ionicons name="log-out-outline" size={20} color={theme.danger} />
          <Text style={styles.logoutText}>Se déconnecter</Text>
        </TouchableOpacity>

        {/* ── RANGÉES ──────────────────────────────────────────────── */}
        {/* 23/07/2026 (demande armateur) — « Mon bateau » retiré d'ici :
            doublon avec Réglages → Mon bateau (page unique). */}
        <TouchableOpacity
          style={styles.menuRow}
          onPress={() => router.push("/profile/subscription")}
          activeOpacity={0.85}
          testID="profile-open-subscription"
        >
          <Ionicons name="diamond-outline" size={18} color="#F4A261" />
          <Text style={[styles.menuRowText, { color: theme.text }]}>Abonnement &amp; parrainage</Text>
          <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.menuRow}
          onPress={() => router.push("/diagnostic")}
          activeOpacity={0.85}
          testID="profile-diagnostic"
        >
          <Ionicons name="bug-outline" size={18} color={theme.textDim} />
          <Text style={styles.menuRowText}>Diagnostic &amp; logs (signaler un bug)</Text>
          <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
        </TouchableOpacity>

        {/* 19/07/2026 — bascule de comptes réservée aux BÊTA-TESTEURS
            déclarés (et à l'admin) ; le backend applique la même règle. */}
        {beta?.is_tester && (
          <TouchableOpacity
            style={[styles.menuRow, styles.testSwitchRow]}
            onPress={() => router.push("/profile/test-switch")}
            activeOpacity={0.85}
            testID="profile-test-switch"
          >
            <Ionicons name="flask" size={18} color={theme.primary} />
            <Text style={[styles.menuRowText, { color: theme.primary }]}>
              Comptes de test — bascule rapide
            </Text>
            <Ionicons name="chevron-forward" size={18} color={theme.primary} />
          </TouchableOpacity>
        )}

        {/* 19/07/2026 — MODE TEST bêta : signalements marqués TEST et
            autorisés depuis la terre (validation croisée entre testeurs). */}
        {beta?.is_tester && (
          <View style={[styles.menuRow, styles.testSwitchRow]} testID="profile-test-mode-row">
            <Ionicons name="construct-outline" size={18} color="#F4A261" />
            <View style={{ flex: 1 }}>
              <Text style={[styles.menuRowText, { color: "#F4A261" }]}>
                Mode test bêta
              </Text>
              <Text style={styles.testModeHint}>
                Signalements marqués « TEST », autorisés depuis la terre
              </Text>
            </View>
            <Switch
              value={!!beta.test_mode}
              disabled={testModeBusy}
              onValueChange={async (v) => {
                setTestModeBusy(true);
                try {
                  await api.setTestMode(v);
                  setBeta((b) => (b ? { ...b, test_mode: v } : b));
                  showToast("info", v
                    ? "Mode test activé — vos signalements seront marqués TEST"
                    : "Mode test désactivé");
                } catch {
                  showToast("error", "Impossible de changer le mode test");
                } finally {
                  setTestModeBusy(false);
                }
              }}
              trackColor={{ false: theme.border, true: "rgba(244,162,97,0.55)" }}
              thumbColor={beta.test_mode ? "#F4A261" : theme.textMute}
              testID="profile-test-mode-switch"
            />
          </View>
        )}

        {/* 19/07/2026 — gestion de la liste des bêta-testeurs (ADMIN). */}
        {beta?.is_admin && (
          <TouchableOpacity
            style={[styles.menuRow, styles.testSwitchRow]}
            onPress={() => router.push("/profile/beta-testers")}
            activeOpacity={0.85}
            testID="profile-beta-testers"
          >
            <Ionicons name="people-circle-outline" size={18} color={theme.primary} />
            <Text style={[styles.menuRowText, { color: theme.primary }]}>
              Bêta-testeurs — gestion (admin)
            </Text>
            <Ionicons name="chevron-forward" size={18} color={theme.primary} />
          </TouchableOpacity>
        )}

        {/* 13/07/2026 — Lot de 5 signalements de TEST d'alarme autour de la
            position (200 m / 1 / 3 / 10 / 20 km). Whitelist uniquement ;
            chaque nouveau lot efface le précédent (côté serveur). */}
        {isTestAccount(user?.email) && (
          <TouchableOpacity
            style={[styles.menuRow, styles.testSwitchRow]}
            onPress={createAlertTestBatch}
            disabled={alertBatchBusy}
            activeOpacity={0.85}
            testID="profile-alert-test-batch"
          >
            <Ionicons name="notifications-circle-outline" size={18} color="#F4A261" />
            <Text style={[styles.menuRowText, { color: "#F4A261" }]}>
              {alertBatchBusy
                ? "Création du lot de test…"
                : "Test d'alarme — créer 5 signalements"}
            </Text>
            {alertBatchBusy
              ? <ActivityIndicator size="small" color="#F4A261" />
              : <Ionicons name="chevron-forward" size={18} color="#F4A261" />}
          </TouchableOpacity>
        )}

        {/* ── Liens discrets : démo + intro côte à côte ────────────── */}
        <View style={styles.footerLinks}>
          <TouchableOpacity
            style={styles.footerLink}
            onPress={() => router.push("/demo-autopilot")}
            testID="profile-demo-launch"
          >
            <Ionicons name="play-circle-outline" size={17} color="#F4A261" />
            <Text style={[styles.footerLinkText, { color: "#F4A261" }]}>Voir la démo</Text>
          </TouchableOpacity>
          <View style={styles.footerLinkSep} />
          <TouchableOpacity
            style={styles.footerLink}
            onPress={() => router.push("/(auth)/welcome")}
            testID="profile-replay-onboarding"
          >
            <Ionicons name="play-circle-outline" size={17} color={theme.primary} />
            <Text style={styles.footerLinkText}>{"Revoir l'intro"}</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.disclaimer}>
          SignalMar n{"\u2019"}est qu{"\u2019"}une aide à l{"\u2019"}amélioration de la sécurité en mer.
          Elle ne remplace en aucun cas les cartes marines et ne se substitue pas
          à la plus grande vigilance du barreur et de son équipage.
        </Text>
      </ScrollView>

      <RanksModal
        visible={ranksOpen}
        onClose={() => setRanksOpen(false)}
        points={points}
        customTitle={data?.title ?? null}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.bg },
  scroll: { padding: spacing.md, gap: spacing.md, paddingBottom: 40 },

  // Demo mode
  demoCard: {
    flex: 1, alignItems: "center", justifyContent: "center",
    gap: 12, padding: spacing.lg,
  },
  demoTitle: { color: theme.text, fontSize: 20, fontWeight: "900" },
  demoBody: {
    color: theme.textDim, fontSize: 14, textAlign: "center",
    paddingHorizontal: 6, lineHeight: 20,
  },
  primaryCta: {
    backgroundColor: theme.primary,
    paddingHorizontal: 24, paddingVertical: 12,
    borderRadius: radii.md, marginTop: 6,
  },
  primaryCtaTxt: { color: theme.bg, fontWeight: "800", fontSize: 15 },

  // ── Carte profil ──
  headerCard: {
    backgroundColor: theme.bg2, borderRadius: radii.lg,
    borderWidth: 1, borderColor: theme.border,
    padding: spacing.lg, paddingTop: spacing.lg + 6,
    alignItems: "center", gap: 10,
  },
  gearBtn: {
    position: "absolute", top: 10, right: 10, zIndex: 2,
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
  },
  pillsAvatarRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    alignSelf: "stretch", gap: 8,
  },
  sidePill: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    minHeight: 36,
  },
  friendsPill: { backgroundColor: "#FFD166" },
  groupsPill: { backgroundColor: "#8ECAE6" },
  sidePillText: { color: "#0B132B", fontWeight: "900", fontSize: 13 },
  avatarBtn: { position: "relative" },
  avatar: { width: 92, height: 92, borderRadius: 46, borderWidth: 3, borderColor: theme.primary },
  avatarFallback: {
    backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  avatarBadge: {
    position: "absolute", bottom: 0, right: 0, width: 26, height: 26, borderRadius: 13,
    backgroundColor: theme.primary, alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.bg2,
  },
  pseudoRow: { flexDirection: "row", alignItems: "center", gap: 6, maxWidth: "90%" },
  pseudoText: { color: theme.text, fontSize: 24, fontWeight: "900", flexShrink: 1 },
  rankPill: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: theme.primary,
    paddingHorizontal: 16, paddingVertical: 9, borderRadius: radii.pill,
  },
  rankText: { color: theme.bg, fontWeight: "900", fontSize: 15 },
  pointBubble: { backgroundColor: theme.bg, paddingHorizontal: 9, paddingVertical: 3, borderRadius: radii.sm },
  pointText: { color: theme.primary, fontWeight: "900", fontSize: 12 },
  relPill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(72,202,228,0.08)",
    borderColor: "rgba(72,202,228,0.30)", borderWidth: 1,
    paddingHorizontal: 14, paddingVertical: 7, borderRadius: radii.pill,
  },
  relText: { color: theme.textDim, fontSize: 13, fontWeight: "700" },
  relScore: { fontWeight: "900", fontSize: 14 },

  // ── Stats ──
  statsRow: { flexDirection: "row", gap: spacing.sm },
  stat: {
    flex: 1, backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    alignItems: "flex-start", gap: 4, borderWidth: 1, borderColor: theme.border,
  },
  statValue: { color: theme.text, fontSize: 20, fontWeight: "900" },
  statLabel: { color: theme.textDim, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 },

  // ── Historique ──
  histHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    minHeight: 44, paddingHorizontal: 2,
  },
  histTitle: {
    color: theme.textDim, fontWeight: "800", fontSize: 12, letterSpacing: 2,
    textTransform: "uppercase",
  },
  histRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  histCount: { color: theme.textMute, fontSize: 11, fontWeight: "700" },
  historyRow: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 64,
    borderWidth: 1, borderColor: theme.border,
  },
  histDot: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  histRowTitle: { color: theme.text, fontWeight: "800" },
  histRowSub: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  // 26/07 — boutons Détails / Suivre du tableau « Mes routes ».
  routeBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(255,255,255,0.08)", borderWidth: 1, borderColor: theme.border,
    borderRadius: 8, paddingHorizontal: 8, paddingVertical: 7, marginLeft: 6, minHeight: 32,
  },
  routeBtnGo: { backgroundColor: "#2EC4B6", borderColor: "#2EC4B6" },
  routeBtnTxt: { color: theme.text, fontSize: 11, fontWeight: "800" },
  empty: {
    backgroundColor: theme.bg2, padding: spacing.xl, borderRadius: radii.md,
    alignItems: "center", gap: 6, borderWidth: 1, borderColor: theme.border,
  },
  emptyText: { color: theme.text, fontWeight: "700" },
  emptySub: { color: theme.textDim, fontSize: 12, textAlign: "center" },
  pager: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    gap: spacing.sm, marginTop: 2,
  },
  pagerBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, minHeight: 44,
  },
  pagerBtnDisabled: { opacity: 0.45 },
  pagerBtnText: { color: theme.text, fontWeight: "800", fontSize: 13 },
  pagerLabel: { flex: 1, alignItems: "center", justifyContent: "center", minHeight: 44 },
  pagerLabelText: { color: theme.textDim, fontSize: 13, fontWeight: "700" },

  // ── Déconnexion + rangées ──
  logout: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderWidth: 1, borderColor: theme.danger, minHeight: 52,
  },
  logoutText: { color: theme.danger, fontWeight: "800", fontSize: 15 },
  menuRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md, padding: spacing.md,
    borderWidth: 1, borderColor: theme.border, minHeight: 52,
  },
  menuRowText: { color: theme.textDim, fontWeight: "700", fontSize: 14, flex: 1 },
  testSwitchRow: {
    borderColor: theme.primary,
    backgroundColor: "rgba(72,202,228,0.06)",
  },
  // 19/07 — sous-titre du toggle « Mode test bêta ».
  testModeHint: { color: theme.textMute, fontSize: 11, marginTop: 2 },

  // ── Liens discrets bas de page ──
  footerLinks: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.md, marginTop: 2,
  },
  footerLink: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 10, paddingHorizontal: 4, minHeight: 40,
  },
  footerLinkText: { color: theme.primary, fontWeight: "700", fontSize: 13 },
  footerLinkSep: { width: 1, height: 16, backgroundColor: theme.border },

  disclaimer: {
    color: theme.textMute, fontSize: 11, fontStyle: "italic",
    textAlign: "center", lineHeight: 15, paddingHorizontal: spacing.sm,
  },
});
