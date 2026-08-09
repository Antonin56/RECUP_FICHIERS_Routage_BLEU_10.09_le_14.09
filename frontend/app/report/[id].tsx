import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Clipboard from "expo-clipboard";
import * as Sharing from "expo-sharing";
import { captureRef } from "react-native-view-shot";

import { api, type ChatMessage, type ReportItem, type ReportEdit } from "@/src/api/client";
import { removeReportFromCache } from "@/src/lib/reports-cache";
import { theme, spacing, radii } from "@/src/lib/theme";
import { TYPE_BY_ID, type ReportTypeId } from "@/src/lib/report-types";
import {
  SUBTYPE_LABEL,
  ACTIVITY_LABEL,
  type AuthoritySubtype,
  type AuthorityActivity,
} from "@/src/lib/authorities";
import { formatTimeAgo, formatDM } from "@/src/lib/coords";
import { showToast } from "@/src/components/Toast";
import { useAuth } from "@/src/auth/AuthContext";
import { PhotoViewer } from "@/src/components/PhotoViewer";
import { ReportSharePreview } from "@/src/components/ReportSharePreview";
import { HeadingEditModal } from "@/src/components/HeadingEditModal";
import { SocialPostCard, approxZone } from "@/src/components/SocialPostCard";
import { signalMarInviteUrl, signalMarReportUrl } from "@/src/lib/share-app";

// Phase E.3 — non-authors need at least this reliability score (%) to edit
// the heading on autorities / drift-eligible reports. Mirrors the backend.
const HEADING_EDIT_RELIABILITY_THRESHOLD = 65;
// Marine ranks in ascending order (mirrors MARINE_RANK_LADDER in the backend).
// Cap edition unlocks at "maitre" (index 5 = the 6th rank, "Maître").
const MARINE_RANK_ORDER = [
  "mousse", "matelot", "qm2", "qm1", "second_maitre", "maitre",
  "premier_maitre", "maitre_principal", "major", "aspirant",
  "ev2", "ev1", "lv", "cc", "cf", "cv",
  "contre_amiral", "vice_amiral", "vae", "amiral", "amiral_de_france",
];
const HEADING_EDIT_MIN_RANK_INDEX = 5; // "maitre"

export default function ReportDetail() {
  const params = useLocalSearchParams<{ id: string; created?: string }>();
  const { id } = params;
  const justCreated = params.created === "1";
  const router = useRouter();
  const { user, refresh: refreshAuthUser } = useAuth();
  const [report, setReport] = useState<ReportItem | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [submittingEdit, setSubmittingEdit] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerIndex, setViewerIndex] = useState(0);
  const [mapReady, setMapReady] = useState(false);
  const [headingModalOpen, setHeadingModalOpen] = useState(false);
  const [lockedModalOpen, setLockedModalOpen] = useState(false);
  // Phase 3d — Coordinates sharing sheet (Navionics / Google Maps / Copy).
  const [coordSheetOpen, setCoordSheetOpen] = useState(false);
  // Posts « viraux » Instagram / Facebook / X (11/07/2026).
  const [socialBusy, setSocialBusy] = useState<null | "instagram" | "facebook" | "x">(null);
  const socialCardRef = useRef<View>(null);

  // Partage (10/07/2026) — mécanique unique : écran /share-invite (choix de
  // contacts + SMS groupé prérempli, avec lien « Partager autrement… »).
  function shareReport() {
    if (!report) return;
    router.push({
      pathname: "/share-invite",
      params: {
        type_label: TYPE_BY_ID[report.type as ReportTypeId]?.label || report.type,
        coords: formatDM(report.lat, report.lng),
        description: report.description?.slice(0, 200) || "",
      },
    });
  }

  // Post « viral » (11/07/2026) : visuel 1080×1080 (position APPROXIMATIVE
  // uniquement + mention SignalMar.app) capturé hors écran, légende copiée
  // dans le presse-papiers (Instagram/FB ne préremplissent pas le texte),
  // puis feuille de partage native.
  async function shareSocial(network: "instagram" | "facebook" | "x") {
    if (!report || socialBusy) return;
    if (Platform.OS === "web") {
      showToast("info", "Partage en post disponible sur téléphone.");
      return;
    }
    setSocialBusy(network);
    try {
      const typeLabel = TYPE_BY_ID[report.type as ReportTypeId]?.label || report.type;
      const zone = approxZone(report.lat, report.lng);
      const tags = network === "x"
        ? "#SignalMar #EnMer"
        : "#SignalMar #EnMer #SécuritéMaritime #Mer";
      const caption =
        `\u{1F6A8} ${typeLabel} signalé en mer — ${zone} (position approximative)\n` +
        `Obtenez gratuitement SignalMar sur SignalMar.app (Android et Iphone) ` +
        `et retrouvez en détail ce signalement : ${report.short_id || ""}\n` +
        `${signalMarReportUrl(report.short_id)}\n` +
        `${signalMarInviteUrl(user?.referral_code)}\n${tags}`;
      await Clipboard.setStringAsync(caption);
      const uri = await captureRef(socialCardRef, {
        format: "png", quality: 1, result: "tmpfile", width: 1080, height: 1080,
      });
      showToast("success", "Visuel prêt — légende copiée, collez-la dans votre post \u{1F4CB}");
      await Sharing.shareAsync(uri, {
        mimeType: "image/png",
        dialogTitle: network === "x" ? "Partager sur X" : network === "facebook" ? "Partager sur Facebook" : "Partager sur Instagram",
      });
    } catch (e) {
      showToast("error", (e as Error).message || "Partage impossible");
    } finally {
      setSocialBusy(null);
    }
  }

  async function submitEdit(kind: "fake" | "ended" | "shift") {
    if (!id) return;
    const isAuthor = !!user && user.user_id === report?.author.user_id;
    // For shift: navigate to the map in picking mode, centered on the current report.
    if (kind === "shift") {
      setEditModalOpen(false);
      router.push({
        pathname: "/(tabs)/map",
        params: {
          shift_report_id: id,
          shift_lat: report ? String(report.lat) : "",
          shift_lng: report ? String(report.lng) : "",
          ...(isAuthor ? { shift_author: "1" } : {}),
        },
      });
      return;
    }
    setSubmittingEdit(true);
    try {
      if (isAuthor && kind === "ended") {
        // Direct author edit — no community vote.
        const updated = await api.authorEdit(id, { status: "ended" });
        setReport(updated);
        setEditModalOpen(false);
        showToast("success", "Signalement marqué terminé.");
      } else {
        const updated = await api.proposeEdit(id, { kind });
        setReport(updated);
        setEditModalOpen(false);
        showToast(
          "success",
          kind === "fake"
            ? "Signalé comme faux — la communauté décide."
            : "Marqué terminé — la communauté décide.",
        );
      }
    } catch (e) {
      showToast("error", (e as Error).message);
    } finally {
      setSubmittingEdit(false);
    }
  }

  async function deleteOwn() {
    if (!id) return;
    setSubmittingEdit(true);
    try {
      await api.deleteReport(id);
      showToast("success", "Signalement supprimé.");
      router.replace("/(tabs)/map");
    } catch (e) {
      showToast("error", (e as Error).message);
    } finally {
      setSubmittingEdit(false);
    }
  }

  async function voteOnEdit(editId: string, vote: "up" | "down") {
    if (!id) return;
    try {
      const updated = await api.voteEdit(id, editId, vote);
      setReport(updated);
    } catch (e) {
      showToast("error", (e as Error).message);
    }
  }

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [r, m] = await Promise.all([api.getReport(id), api.listMessages(id)]);
      setReport(r);
      setMessages(m);
    } catch (e) {
      // 23/07/2026 — signalement SUPPRIMÉ côté serveur (404) : on le purge du
      // cache hors-ligne pour que son marqueur disparaisse de la carte au
      // lieu de rouvrir « introuvable » à chaque tap.
      if ((e as Error & { status?: number }).status === 404) {
        void removeReportFromCache(id);
      } else {
        showToast("error", (e as Error).message);
      }
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Poll messages every 6s while screen is open.
  useEffect(() => {
    if (!id) return;
    const t = setInterval(async () => {
      try {
        const m = await api.listMessages(id);
        setMessages(m);
      } catch {
        /* ignore */
      }
    }, 6000);
    return () => clearInterval(t);
  }, [id]);

  async function confirm() {
    if (!id) return;
    setConfirming(true);
    try {
      const r = await api.confirmReport(id);
      setReport(r);
      // V1.2 — enriched toast: show the confirmer's grade gain + the author's
      // fiabilité delta. If a referral bonus was released, mention it too.
      const gainedGrade = Number(r.confirmer_points_awarded ?? 0);
      const gainedFiab = Number(r.author_reliability_awarded ?? 0);
      const authorLabel = r.author_pseudo || "l'auteur";
      const parts: string[] = ["Signalement confirmé"];
      if (gainedGrade > 0) parts.push(`+${gainedGrade} pts pour vous`);
      if (gainedFiab > 0) parts.push(`+${gainedFiab} % fiabilité pour ${authorLabel}`);
      if (r.referral_bonus_paid) parts.push("bonus parrainage débloqué 🎉");
      showToast("success", parts.join(" · "));
      // Refresh AuthContext so the profile badge/points reflect the +2 gain.
      void refreshAuthUser();
    } catch (e) {
      showToast("error", (e as Error).message);
    } finally {
      setConfirming(false);
    }
  }

  async function send() {
    if (!id || !text.trim()) return;
    setSending(true);
    try {
      const m = await api.postMessage(id, text.trim());
      setMessages((p) => [...p, m]);
      setText("");
    } catch (e) {
      showToast("error", (e as Error).message);
    } finally {
      setSending(false);
    }
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={theme.primary} />
      </View>
    );
  }
  // FIX 11/07/2026 (crash signalé depuis les notifications) : un signalement
  // supprimé/expiré (404 — ex. purge DB) laissait un spinner INFINI sans
  // retour possible. On affiche désormais un écran « introuvable » propre.
  if (!report) {
    return (
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        <View style={[styles.center, { gap: spacing.sm, padding: spacing.lg }]} testID="report-not-found">
          <Ionicons name="help-buoy-outline" size={54} color={theme.textDim} />
          <Text style={{ color: theme.text, fontWeight: "900", fontSize: 17 }}>
            Signalement introuvable
          </Text>
          <Text style={{ color: theme.textDim, fontSize: 13, textAlign: "center", lineHeight: 19, maxWidth: 300 }}>
            Il a peut-être expiré ou été supprimé par son auteur ou la communauté.
          </Text>
          <TouchableOpacity
            style={[styles.actionBtn, { flex: 0, paddingHorizontal: 28, marginTop: spacing.sm }]}
            onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/map"))}
            testID="report-not-found-back"
            activeOpacity={0.85}
          >
            <Ionicons name="arrow-back" size={18} color={theme.bg} />
            <Text style={styles.actionText}>Retour</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const t = TYPE_BY_ID[report.type as ReportTypeId];
  const isAuthor = !!user && user.user_id === report.author.user_id;

  // Phase E.3 — Cap (heading) editing eligibility.
  // Type eligibility: autorites / secours OR drift-eligible reports (their
  // presence of drift_cone is the canonical signal).
  const capEditableType =
    report.type === "autorites" ||
    report.type === "secours" ||
    !!report.drift_cone;
  const userReliability = user?.reliability_score ?? 0;
  const userRankId = user?.rank_id ?? "mousse";
  const userRankIndex = Math.max(0, MARINE_RANK_ORDER.indexOf(userRankId));
  const userRankLabel = user?.rank_label ?? "Mousse";
  // V1.1 — Cap edit is now restricted to trusted contributors:
  //   • rank ≥ Maître (index 5) OR the report's author
  //   • reliability score ≥ 65 %
  const userCanEditHeading =
    capEditableType && (
      isAuthor ||
      (userRankIndex >= HEADING_EDIT_MIN_RANK_INDEX && userReliability >= HEADING_EDIT_RELIABILITY_THRESHOLD)
    );
  // Cap card is shown whenever the type is eligible, even if no heading is set
  // yet (so eligible editors can fill it in, and others can see "non défini").
  const showCapCard = capEditableType;
  const capContextLabel =
    report.type === "autorites" || report.type === "secours"
      ? "Cap de navigation"
      : "Cap de dérive";

  async function saveHeading(deg: number, speedKnots?: number) {
    if (!report) return;
    try {
      const updated = await api.authorEdit(report.id, {
        heading: deg,
        ...(speedKnots != null ? { speed_knots: speedKnots } : {}),
      });
      setReport(updated);
      setHeadingModalOpen(false);
      showToast(
        "success",
        speedKnots != null
          ? `Cap ${Math.round(deg).toString().padStart(3, "0")}° · ${speedKnots} nds — en navigation`
          : `Cap mis à jour : ${Math.round(deg).toString().padStart(3, "0")}°`,
      );
    } catch (e) {
      showToast("error", (e as Error).message || "Impossible de mettre à jour le cap");
    }
  }

  function viewOnMap() {
    if (!report) return;
    router.push({
      pathname: "/(tabs)/map",
      params: {
        focus_id: report.id,
        focus_lat: String(report.lat),
        focus_lng: String(report.lng),
      },
    });
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={[styles.header, { backgroundColor: (t?.color || theme.primary) + "22" }]}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="report-detail-close">
            <Ionicons name="chevron-down" size={22} color={theme.text} />
          </TouchableOpacity>
          <View style={[styles.dot, { backgroundColor: t?.color || theme.primary }]}>
            <Ionicons name={(t?.icon as never) || "alert-circle"} size={20} color="#fff" />
          </View>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Text style={styles.title}>{t?.label || report.type}</Text>
              {/* 19/07/2026 — badge signalement de TEST (mode bêta). */}
              {report.is_test && (
                <View style={styles.testChip} testID="report-test-badge">
                  <Text style={styles.testChipText}>TEST</Text>
                </View>
              )}
            </View>
            <Text style={styles.sub}>
              Créé {formatTimeAgo(report.created_at)} · par{" "}
              {isAuthor ? "vous" : (report.author.pseudo || report.author.name || "Anonyme")}
            </Text>
          </View>
          <TouchableOpacity
            onPress={shareReport}
            style={styles.iconBtn}
            testID="report-share-button"
          >
            <Ionicons name="share-social-outline" size={22} color={theme.text} />
          </TouchableOpacity>
        </View>

        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={{ backgroundColor: theme.bg }}>
          <View style={styles.metaCard}>
            <TouchableOpacity
              style={styles.metaRow}
              onPress={() => setCoordSheetOpen(true)}
              activeOpacity={0.7}
              testID="report-coords-open"
              accessibilityLabel="Options de partage de la position"
            >
              <Ionicons name="navigate" size={16} color={theme.primary} />
              <Text style={[styles.metaText, styles.coords, styles.coordsLinked]}>
                {formatDM(report.lat, report.lng)}
              </Text>
              <Ionicons
                name="open-outline"
                size={14}
                color={theme.primary}
                style={{ marginLeft: "auto" }}
              />
            </TouchableOpacity>
            {report.confirm_count > 0 ? (
              <View style={styles.metaRow}>
                <Ionicons name="checkmark-done" size={16} color={theme.success} />
                <Text style={styles.metaText}>
                  Confirmé {formatTimeAgo(report.last_confirmed_at)}
                  {" · "}{report.confirm_count} confirmation{report.confirm_count > 1 ? "s" : ""}
                </Text>
              </View>
            ) : (
              <View style={styles.metaRow}>
                <Ionicons name="time" size={16} color={theme.primary} />
                <Text style={styles.metaText}>
                  Aucune confirmation pour le moment
                </Text>
              </View>
            )}
            <TouchableOpacity
              style={styles.idRow}
              onPress={async () => {
                try {
                  await Clipboard.setStringAsync(report.id);
                  showToast("success", "ID copié");
                } catch {
                  /* noop */
                }
              }}
              testID="report-id-copy"
            >
              <Ionicons name="finger-print" size={12} color={theme.textMute} />
              <Text style={styles.idText} selectable>
                ID {report.id.slice(0, 8)}…
              </Text>
              <Ionicons name="copy-outline" size={12} color={theme.textMute} />
            </TouchableOpacity>
          </View>

          {report.description ? (
            <View style={styles.descCard}>
              <Text style={styles.descText}>{report.description}</Text>
            </View>
          ) : null}

          {showCapCard && (
            <View style={styles.capCard} testID="report-cap-card">
              <View style={styles.capRow}>
                <View style={styles.capIconWrap}>
                  <Ionicons name="compass" size={20} color={theme.primary} />
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.capLabel}>{capContextLabel}</Text>
                  {(() => {
                    // Priorities:
                    //   1) user-set heading (report.heading) → "manuel"
                    //   2) automatic bearing from drift cone (algo_bearing_deg) → "auto (vent+courant)"
                    //   3) nothing → "non défini"
                    const manual = typeof report.heading === "number" ? report.heading : null;
                    const auto = typeof report.drift_cone?.algo_bearing_deg === "number"
                      ? report.drift_cone!.algo_bearing_deg
                      : null;
                    const deg = manual ?? auto;
                    if (deg == null) {
                      // 13/07/2026 — autorités/secours stationnaires ou en
                      // contrôle : on affiche l'ÉTAT (« Stationnaire »…) au
                      // lieu d'un « non défini » trompeur.
                      const stateLabel =
                        (report.type === "autorites" || report.type === "secours") &&
                        report.activity && report.activity !== "navigation"
                          ? ACTIVITY_LABEL[report.activity as AuthorityActivity]
                          : null;
                      return (
                        <Text style={styles.capValue}>
                          {stateLabel ?? "non défini"}
                        </Text>
                      );
                    }
                    return (
                      <>
                        <Text style={styles.capValue}>
                          {Math.round(deg).toString().padStart(3, "0")}°
                        </Text>
                        <View
                          style={[
                            styles.capOriginBadge,
                            manual != null
                              ? styles.capOriginBadgeManual
                              : styles.capOriginBadgeAuto,
                          ]}
                        >
                          <Ionicons
                            name={manual != null ? "hand-left" : "flash"}
                            size={10}
                            color={manual != null ? theme.primary : "#FF9F45"}
                          />
                          <Text
                            style={[
                              styles.capOriginText,
                              { color: manual != null ? theme.primary : "#FF9F45" },
                            ]}
                            numberOfLines={1}
                          >
                            {manual != null ? "manuel" : "auto"}
                          </Text>
                        </View>
                      </>
                    );
                  })()}
                  {report.heading_edited_at ? (
                    <Text style={styles.capMeta}>
                      Modifié {formatTimeAgo(report.heading_edited_at)}
                    </Text>
                  ) : null}
                </View>
                {capEditableType ? (
                  <TouchableOpacity
                    style={[
                      styles.capEditBtn,
                      !userCanEditHeading && styles.capEditBtnLocked,
                    ]}
                    onPress={() => {
                      if (userCanEditHeading) setHeadingModalOpen(true);
                      else setLockedModalOpen(true);
                    }}
                    testID="report-cap-edit"
                    activeOpacity={0.85}
                  >
                    <Ionicons
                      name={userCanEditHeading ? "create" : "lock-closed"}
                      size={16}
                      color={userCanEditHeading ? theme.primary : "#FFB84D"}
                    />
                    <Text
                      style={[
                        styles.capEditText,
                        !userCanEditHeading && { color: "#FFB84D" },
                      ]}
                    >
                      Modifier
                    </Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            </View>
          )}

          {(report.subtype || report.activity) && (
            <View style={styles.descCard}>
              {report.subtype && (
                <View style={styles.metaRow}>
                  <Ionicons name="shield-checkmark" size={16} color={theme.primary} />
                  <Text style={styles.metaText}>
                    {(() => {
                      // Look the subtype up across ALL types (autorites,
                      // secours, obstacle_nav, animal_marin, pollution).
                      // Fall back to a humanised version (no underscores)
                      // for any unknown id.
                      const local = SUBTYPE_LABEL[report.subtype as AuthoritySubtype];
                      if (local) return local;
                      const parentType = TYPE_BY_ID[report.type as ReportTypeId];
                      const s = parentType?.subtypes.find((x) => x.id === report.subtype);
                      if (s) return s.label;
                      return String(report.subtype).replace(/_/g, " ");
                    })()}
                  </Text>
                </View>
              )}
              {report.activity && (
                <View style={styles.metaRow}>
                  <Ionicons name="ellipsis-horizontal-circle" size={16} color={theme.primary} />
                  <Text style={styles.metaText}>
                    {ACTIVITY_LABEL[report.activity as AuthorityActivity] || report.activity}
                  </Text>
                </View>
              )}
              {report.activity === "navigation" && report.speed_knots != null && (
                <View style={styles.metaRow}>
                  <Ionicons name="speedometer" size={16} color={theme.primary} />
                  <Text style={styles.metaText}>
                    {report.speed_knots} nœuds
                  </Text>
                </View>
              )}
              {report.drift_cone && report.drift_cone.distance_km > 0.005 && (
                <View testID="drift-cone-info" style={{ gap: 4 }}>
                  <View style={styles.metaRow}>
                    <Ionicons name="trending-up" size={16} color="#FF7A1A" />
                    <Text style={[styles.metaText, { flex: 1, flexShrink: 1 }]}>
                      {(() => {
                        const dc = report.drift_cone!;
                        const dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSO","SO","OSO","O","ONO","NO","NNO"];
                        const idx = Math.round(((dc.bearing_deg % 360) / 22.5)) % 16;
                        const km = dc.distance_km < 1
                          ? `${Math.round(dc.distance_km * 1000)} m`
                          : `${dc.distance_km.toFixed(2)} km`;
                        return `Dérive 1 h : ${km} vers ${dirs[idx]} (${Math.round(dc.bearing_deg)}°)`;
                      })()}
                    </Text>
                  </View>
                  {report.drift_cone.bearing_source === "user" ? (
                    <View style={styles.driftBadge}>
                      <Ionicons name="person" size={10} color={theme.bg} />
                      <Text style={styles.driftBadgeText}>
                        Cap observé
                        {report.heading_edited_by_name
                          ? ` par ${report.heading_edited_by_name}`
                          : ""}
                      </Text>
                    </View>
                  ) : null}
                  {report.drift_cone.bearing_source === "user" &&
                    typeof report.drift_cone.algo_bearing_deg === "number" &&
                    Math.abs(
                      ((report.drift_cone.algo_bearing_deg -
                        report.drift_cone.bearing_deg + 540) % 360) - 180,
                    ) > 5 ? (
                    <Text style={styles.driftAlgoNote}>
                      Cap calculé (vent+courant) :{" "}
                      {Math.round(report.drift_cone.algo_bearing_deg)
                        .toString()
                        .padStart(3, "0")}°
                    </Text>
                  ) : null}
                  {report.drift_cone.wind_source ? (
                    <Text style={styles.driftAlgoNote}>
                      {report.drift_cone.wind_source.startsWith("AROME")
                        ? "🟢 "
                        : report.drift_cone.wind_source.startsWith("ARPEGE")
                        ? "🟡 "
                        : "⚪ "}
                      Vent : {report.drift_cone.wind_source}
                      {report.drift_cone.wind_only ? "" : " · Courant : Open-Meteo"}
                    </Text>
                  ) : null}
                  {report.drift_cone.wind_only ? (
                    <Text style={styles.driftAlgoWarn}>
                      ⚠️ Dérive estimée uniquement avec les valeurs des vents sur
                      le secteur (signalement à moins de 20 km des côtes) —
                      utilisez vos connaissances des courants locaux pour affiner
                      l&apos;estimation de la direction de dérive de l&apos;objet.
                    </Text>
                  ) : (
                    <Text style={styles.driftAlgoWarn}>
                      ⚠️ Le courant Open-Meteo peut être approximatif en zone tidale française.
                    </Text>
                  )}
                </View>
              )}
            </View>
          )}

          {report.photos.length > 0 && (
            <>
              <Text style={styles.sectionTitle}>Photos</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
                {report.photos.map((p, i) => (
                  <TouchableOpacity
                    key={i}
                    activeOpacity={0.85}
                    onPress={() => {
                      setViewerIndex(i);
                      setViewerOpen(true);
                    }}
                    testID={`report-photo-${i}`}
                  >
                    <Image source={{ uri: p }} style={styles.gallery} />
                    <View style={styles.galleryZoomBadge}>
                      <Ionicons name="expand" size={12} color="#fff" />
                    </View>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            </>
          )}
          {/* Phase D — Mini-map preview embarquée dans le screenshot partagé.
              Affichée systématiquement : c'est joli, ça contextualise, et ça
              garantit que le WebView est déjà prêt quand l'utilisateur tape
              "Partager". V1.1 — tap sur l'aperçu = raccourci vers la carte. */}
          <Text style={styles.sectionTitle}>Aperçu de la carte</Text>
          <TouchableOpacity
            activeOpacity={0.85}
            onPress={viewOnMap}
            testID="report-preview-open-map"
            accessibilityLabel="Ouvrir sur la carte"
            style={{ position: "relative" }}
          >
            <ReportSharePreview
              lat={report.lat}
              lng={report.lng}
              color={t?.color || theme.primary}
              emoji={
                report.type === "autorites" ? "\u{1F6E1}" :
                report.type === "secours" ? "\u{1F6DF}" :
                report.type === "obstacle_nav" ? "\u26A0" :
                report.type === "animal_marin" ? "\u{1F42C}" :
                report.type === "pollution" ? "\u{1F6E2}" : "\u2049"
              }
              driftPolygon={report.drift_cone?.polygon ?? null}
              height={210}
              onReady={() => setMapReady(true)}
            />
            {/* Overlay hint bottom-right so it's clear the preview is tappable. */}
            <View style={styles.previewHint} pointerEvents="none">
              <Ionicons name="expand" size={12} color={theme.bg} />
              <Text style={styles.previewHintText}>Ouvrir</Text>
            </View>
          </TouchableOpacity>
          {/* Subtle brand watermark only visible in shared screenshots. */}
          <View style={styles.shareWatermark}>
            <Ionicons name="boat" size={12} color={theme.primary} />
            <Text style={styles.shareWatermarkText}>Signalé via SignalMar</Text>
          </View>
          </View>

          {justCreated && (
            <View style={styles.justCreatedBanner} testID="just-created-banner">
              <Ionicons name="checkmark-circle" size={20} color={theme.success} />
              <Text style={styles.justCreatedText}>
                Signalement publié. Vous pouvez le voir sur la carte.
              </Text>
            </View>
          )}

          <View style={styles.actionsRow}>
            {isAuthor ? (
              <TouchableOpacity
                style={styles.actionBtn}
                onPress={viewOnMap}
                testID="report-view-on-map"
              >
                <Ionicons name="map" size={20} color={theme.bg} />
                <Text style={styles.actionText}>Voir sur la carte</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={[styles.actionBtn, report.confirmed_by_me && { backgroundColor: theme.success }]}
                onPress={confirm}
                disabled={confirming}
                testID="report-confirm-button"
              >
                {confirming ? (
                  <ActivityIndicator color={theme.bg} />
                ) : (
                  <>
                    <Ionicons
                      name={report.confirmed_by_me ? "checkmark-done" : "checkmark"}
                      size={20}
                      color={theme.bg}
                    />
                    <Text style={styles.actionText}>
                      {report.confirmed_by_me ? "Confirmé" : "Confirmer"}
                    </Text>
                  </>
                )}
              </TouchableOpacity>
            )}
            <TouchableOpacity
              style={styles.actionBtnAlt}
              onPress={() => setEditModalOpen(true)}
              testID="report-update-button"
            >
              <Ionicons name="create-outline" size={20} color={theme.primary} />
              <Text style={[styles.actionText, { color: theme.primary }]}>Mettre à jour</Text>
            </TouchableOpacity>
          </View>

          {/* Posts « viraux » (11/07/2026) — visuel 1080×1080 + légende copiée.
              Position APPROXIMATIVE uniquement sur le visuel public. */}
          <View style={styles.socialRow} testID="report-social-row">
            <View style={{ flex: 1 }}>
              <Text style={styles.socialTitle}>Partager en post</Text>
              <Text style={styles.socialSub}>Visuel prêt à publier · position approximative</Text>
            </View>
            {([
              { id: "instagram" as const, icon: "logo-instagram" as const, bg: "#E1306C" },
              { id: "facebook" as const, icon: "logo-facebook" as const, bg: "#1877F2" },
              { id: "x" as const, icon: "logo-twitter" as const, bg: "#14171A" },
            ]).map((n) => (
              <TouchableOpacity
                key={n.id}
                style={[styles.socialBtn, { backgroundColor: n.bg }]}
                onPress={() => shareSocial(n.id)}
                disabled={!!socialBusy}
                activeOpacity={0.85}
                testID={`report-social-${n.id}`}
                accessibilityLabel={`Partager sur ${n.id}`}
              >
                {socialBusy === n.id ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name={n.icon} size={20} color="#fff" />
                )}
              </TouchableOpacity>
            ))}
          </View>

          {isAuthor && (
            <TouchableOpacity
              style={styles.viewMapSecondary}
              onPress={viewOnMap}
              testID="report-view-on-map-secondary"
            >
              <Ionicons name="map-outline" size={16} color={theme.textDim} />
              <Text style={styles.viewMapSecondaryText}>Localiser sur la carte</Text>
            </TouchableOpacity>
          )}

          {(report.flagged_fake || report.status === "ended") && (
            <View
              style={[
                styles.flagBanner,
                {
                  borderColor: report.flagged_fake ? theme.danger : theme.textMute,
                  backgroundColor: report.flagged_fake ? "rgba(230,57,70,0.12)" : theme.bg2,
                },
              ]}
              testID="report-flag-banner"
            >
              <Ionicons
                name={report.flagged_fake ? "alert" : "checkmark-done-circle"}
                size={20}
                color={report.flagged_fake ? theme.danger : theme.textMute}
              />
              <Text style={styles.flagText}>
                {report.flagged_fake
                  ? "La communauté a marqué ce signalement comme faux."
                  : "Signalement terminé selon la communauté."}
              </Text>
            </View>
          )}

          <Text style={styles.sectionTitle}>
            Propositions de la communauté ({report.edits.length})
          </Text>
          {report.edits.length === 0 ? (
            <Text style={styles.emptyChat}>
              Aucune proposition pour l&apos;instant. Tapez &quot;Mettre à jour&quot; pour signaler un faux,
              un signalement terminé ou un décalage.
            </Text>
          ) : (
            <View style={{ gap: spacing.sm }}>
              {report.edits.map((e: ReportEdit) => {
                const kindLabel =
                  e.kind === "fake"
                    ? "Faux signalement"
                    : e.kind === "ended"
                      ? "Terminé / Plus là"
                      : "Décaler la position";
                const kindIcon =
                  e.kind === "fake" ? "alert" : e.kind === "ended" ? "checkmark-done" : "swap-horizontal";
                const kindColor =
                  e.kind === "fake" ? theme.danger : e.kind === "ended" ? theme.textMute : theme.warning;
                return (
                  <View
                    key={e.id}
                    style={[styles.editCard, e.applied && styles.editCardApplied]}
                    testID={`edit-card-${e.id}`}
                  >
                    <View style={styles.editHeader}>
                      <View style={[styles.editKindPill, { backgroundColor: kindColor + "22", borderColor: kindColor }]}>
                        <Ionicons name={kindIcon} size={14} color={kindColor} />
                        <Text style={[styles.editKindText, { color: kindColor }]}>{kindLabel}</Text>
                      </View>
                      {e.applied && (
                        <View style={styles.appliedPill}>
                          <Ionicons name="checkmark-circle" size={14} color={theme.success} />
                          <Text style={styles.appliedText}>Appliquée</Text>
                        </View>
                      )}
                    </View>
                    <Text style={styles.editAuthor}>
                      par {e.proposer.name || "Anonyme"} · {formatTimeAgo(e.created_at)}
                    </Text>
                    {e.kind === "shift" && e.new_lat != null && e.new_lng != null && (
                      <Text style={styles.editShift} selectable>
                        Nouvelle position : {formatDM(e.new_lat, e.new_lng)}
                      </Text>
                    )}
                    <View style={styles.voteRow}>
                      <TouchableOpacity
                        style={[styles.voteBtn, e.my_vote === "up" && { backgroundColor: theme.success, borderColor: theme.success }]}
                        onPress={() => voteOnEdit(e.id, "up")}
                        testID={`edit-${e.id}-up`}
                      >
                        <Ionicons
                          name="thumbs-up"
                          size={16}
                          color={e.my_vote === "up" ? theme.bg : theme.success}
                        />
                        <Text style={[styles.voteText, e.my_vote === "up" && { color: theme.bg }]}>
                          {e.up_count}
                        </Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        style={[styles.voteBtn, e.my_vote === "down" && { backgroundColor: theme.danger, borderColor: theme.danger }]}
                        onPress={() => voteOnEdit(e.id, "down")}
                        testID={`edit-${e.id}-down`}
                      >
                        <Ionicons
                          name="thumbs-down"
                          size={16}
                          color={e.my_vote === "down" ? "#fff" : theme.danger}
                        />
                        <Text style={[styles.voteText, e.my_vote === "down" && { color: "#fff" }]}>
                          {e.down_count}
                        </Text>
                      </TouchableOpacity>
                      <Text style={styles.netText}>
                        Solde net : {e.net >= 0 ? `+${e.net}` : e.net} (seuil +2)
                      </Text>
                    </View>
                  </View>
                );
              })}
            </View>
          )}

          <Text style={styles.sectionTitle}>Discussion</Text>
          {messages.length === 0 ? (
            <Text style={styles.emptyChat}>Aucun message. Lancez la discussion.</Text>
          ) : (
            <FlatList
              scrollEnabled={false}
              data={messages}
              keyExtractor={(m) => m.id}
              contentContainerStyle={{ gap: spacing.sm }}
              renderItem={({ item }) => {
                const mine = item.user_id === user?.user_id;
                return (
                  <View style={[styles.msg, mine ? styles.msgMine : styles.msgOther]}>
                    {!mine && <Text style={styles.msgName}>{item.name || "Anonyme"}</Text>}
                    <Text style={styles.msgText}>{item.text}</Text>
                    <Text style={styles.msgTime}>{formatTimeAgo(item.created_at)}</Text>
                  </View>
                );
              }}
            />
          )}
        </ScrollView>

        <View style={styles.chatInput}>
          <TextInput
            style={styles.input}
            placeholder="Écrire un message…"
            placeholderTextColor={theme.textMute}
            value={text}
            onChangeText={setText}
            maxLength={400}
            testID="chat-input"
          />
          <TouchableOpacity
            style={styles.sendBtn}
            onPress={send}
            disabled={sending || !text.trim()}
            testID="chat-send"
          >
            {sending ? <ActivityIndicator color={theme.bg} /> : <Ionicons name="send" size={18} color={theme.bg} />}
          </TouchableOpacity>
        </View>

        <Modal
          visible={editModalOpen}
          transparent
          animationType="fade"
          onRequestClose={() => setEditModalOpen(false)}
        >
          <View style={styles.modalBackdrop}>
            <View style={styles.modalSheet} testID="edit-modal">
              <View style={styles.modalHandle} />
              <Text style={styles.modalTitle}>Mettre à jour ce signalement</Text>
              <Text style={styles.modalSub}>
                {isAuthor
                  ? "Vous êtes l'auteur — les changements sont appliqués directement."
                  : "Votre proposition est validée par la communauté (seuil +2 en votes). Vous comptez pour 1 voix, comme les autres marins."}
              </Text>

              {!isAuthor && (
                <TouchableOpacity
                  style={[styles.modalOption, { borderColor: theme.danger }]}
                  onPress={() => submitEdit("fake")}
                  disabled={submittingEdit}
                  testID="edit-option-fake"
                >
                  <View style={[styles.modalIcon, { backgroundColor: theme.danger }]}>
                    <Ionicons name="alert" size={20} color="#fff" />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.modalOptLabel}>Faux signalement</Text>
                    <Text style={styles.modalOptDesc}>Rien à signaler à cet endroit.</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={20} color={theme.textMute} />
                </TouchableOpacity>
              )}

              <TouchableOpacity
                style={[styles.modalOption, { borderColor: theme.textMute }]}
                onPress={() => submitEdit("ended")}
                disabled={submittingEdit}
                testID="edit-option-ended"
              >
                <View style={[styles.modalIcon, { backgroundColor: theme.textMute }]}>
                  <Ionicons name="checkmark-done" size={20} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.modalOptLabel}>
                    {isAuthor ? "Marquer comme terminé" : "Terminé / Plus là"}
                  </Text>
                  <Text style={styles.modalOptDesc}>
                    {isAuthor
                      ? "La situation n'est plus active — clôt votre signalement."
                      : "La situation n'est plus active."}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={20} color={theme.textMute} />
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.modalOption, { borderColor: theme.warning }]}
                onPress={() => submitEdit("shift")}
                disabled={submittingEdit}
                testID="edit-option-shift"
              >
                <View style={[styles.modalIcon, { backgroundColor: theme.warning }]}>
                  <Ionicons name="swap-horizontal" size={20} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.modalOptLabel}>
                    {isAuthor ? "Modifier ma position" : "Décaler la position"}
                  </Text>
                  <Text style={styles.modalOptDesc}>Faites glisser la carte pour positionner exactement.</Text>
                </View>
                <Ionicons name="chevron-forward" size={20} color={theme.textMute} />
              </TouchableOpacity>

              {isAuthor && (
                <TouchableOpacity
                  style={[styles.modalOption, { borderColor: theme.danger }]}
                  onPress={deleteOwn}
                  disabled={submittingEdit}
                  testID="edit-option-delete"
                >
                  <View style={[styles.modalIcon, { backgroundColor: theme.danger }]}>
                    <Ionicons name="trash" size={20} color="#fff" />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.modalOptLabel}>Supprimer mon signalement</Text>
                    <Text style={styles.modalOptDesc}>Action irréversible.</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={20} color={theme.textMute} />
                </TouchableOpacity>
              )}

              <TouchableOpacity
                style={styles.modalClose}
                onPress={() => setEditModalOpen(false)}
                disabled={submittingEdit}
                testID="edit-modal-close"
              >
                <Text style={styles.modalCloseText}>Annuler</Text>
              </TouchableOpacity>
              {submittingEdit && (
                <View style={styles.modalOverlay}>
                  <ActivityIndicator color={theme.primary} />
                </View>
              )}
            </View>
          </View>
        </Modal>
      </KeyboardAvoidingView>
      {/* Carte 1080×1080 rendue HORS ÉCRAN pour la capture des posts. */}
      <View style={styles.socialCardOffscreen} pointerEvents="none">
        <View ref={socialCardRef} collapsable={false}>
          <SocialPostCard report={report} />
        </View>
      </View>
      <PhotoViewer
        visible={viewerOpen}
        photos={report.photos}
        initialIndex={viewerIndex}
        onClose={() => setViewerOpen(false)}
      />
      <HeadingEditModal
        visible={headingModalOpen}
        initialHeading={report.heading}
        contextLabel={capContextLabel}
        speedSuggested={report.type === "autorites" || report.type === "secours"}
        initialSpeedKnots={report.speed_knots ?? null}
        onClose={() => setHeadingModalOpen(false)}
        onSave={saveHeading}
      />
      {/* V1.1 — Sexy locked-feature explainer. Shown when a user tries to edit
          the cap but doesn't meet the rank ≥ 6 (Maître) + reliability ≥ 65 %
          criteria. Uses the same modal layout as the compass so the visual
          language stays consistent. */}
      <Modal
        visible={lockedModalOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setLockedModalOpen(false)}
        statusBarTranslucent
      >
        <Pressable
          style={styles.lockBackdrop}
          onPress={() => setLockedModalOpen(false)}
        >
          <Pressable style={styles.lockSheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.lockBadge}>
              <Ionicons name="lock-closed" size={26} color="#0B132B" />
            </View>
            <Text style={styles.lockTitle}>Modification du cap verrouillée</Text>
            <Text style={styles.lockSubtitle}>
              Cette fonctionnalité est réservée aux marins expérimentés dont les
              observations sont validées par la communauté.
            </Text>
              <View style={styles.lockReqRow}>
                <View style={[
                  styles.lockReqBox,
                  userRankIndex >= HEADING_EDIT_MIN_RANK_INDEX && styles.lockReqBoxOk,
                ]}>
                  <Ionicons
                    name={userRankIndex >= HEADING_EDIT_MIN_RANK_INDEX ? "checkmark-circle" : "medal"}
                    size={22}
                    color={userRankIndex >= HEADING_EDIT_MIN_RANK_INDEX ? "#4CD964" : "#FFB84D"}
                  />
                  <Text style={styles.lockReqLabel}>Grade requis</Text>
                  <Text style={styles.lockReqValue}>Maître ou +</Text>
                  <Text style={styles.lockReqStatus} numberOfLines={1}>Vous : {userRankLabel}</Text>
                </View>
              <View style={[
                styles.lockReqBox,
                userReliability >= HEADING_EDIT_RELIABILITY_THRESHOLD && styles.lockReqBoxOk,
              ]}>
                <Ionicons
                  name={
                    userReliability >= HEADING_EDIT_RELIABILITY_THRESHOLD
                      ? "checkmark-circle"
                      : "shield-checkmark"
                  }
                  size={22}
                  color={
                    userReliability >= HEADING_EDIT_RELIABILITY_THRESHOLD
                      ? "#4CD964"
                      : "#FFB84D"
                  }
                />
                <Text style={styles.lockReqLabel}>Fiabilité</Text>
                <Text style={styles.lockReqValue}>≥ {HEADING_EDIT_RELIABILITY_THRESHOLD}%</Text>
                <Text style={styles.lockReqStatus}>Vous : {Math.round(userReliability)}%</Text>
              </View>
            </View>
            <View style={styles.lockTipRow}>
              <Ionicons name="rocket" size={14} color="#48CAE4" />
              <Text style={styles.lockTip}>
                Continuez à signaler et à confirmer les points des autres marins
                pour monter en grade et gagner de la fiabilité.
              </Text>
            </View>
            <TouchableOpacity
              style={styles.lockCta}
              onPress={() => setLockedModalOpen(false)}
              activeOpacity={0.85}
            >
              <Text style={styles.lockCtaText}>J&apos;ai compris</Text>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>

      {/* Phase 3d — Coordinates share sheet. Opened by tapping the coordinates
          row in the meta card. Offers Navionics (webapp), Google Maps, or
          copy-to-clipboard. Uses Linking.openURL which spawns the native app
          when available (Google Maps app on iOS/Android → falls back to
          Safari/Chrome) or the browser for the Navionics webapp. */}
      <Modal
        visible={coordSheetOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setCoordSheetOpen(false)}
        statusBarTranslucent
      >
        <Pressable
          style={styles.coordBackdrop}
          onPress={() => setCoordSheetOpen(false)}
          testID="report-coords-backdrop"
        >
          <Pressable style={styles.coordSheet} onPress={(e) => e.stopPropagation?.()}>
            <View style={styles.coordHandle} />
            <View style={styles.coordHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.coordSheetTitle}>Position du signalement</Text>
                <Text style={styles.coordSheetSub}>
                  {formatDM(report.lat, report.lng)}
                </Text>
              </View>
              <TouchableOpacity
                onPress={() => setCoordSheetOpen(false)}
                style={styles.coordCloseBtn}
                testID="report-coords-close"
                hitSlop={10}
              >
                <Ionicons name="close" size={22} color={theme.text} />
              </TouchableOpacity>
            </View>

            <TouchableOpacity
              style={styles.coordOption}
              onPress={async () => {
                // Format Navionics/Garmin officiel utilisé par le partage
                // natif de l'app Navionics Boating. Ouvre l'app Navionics
                // sur mobile si installée, sinon fallback webapp Garmin.
                const title = encodeURIComponent(
                  `Signalement SignalMar — ${TYPE_BY_ID[report.type as ReportTypeId]?.label || report.type}`,
                );
                const url = `https://marine.garmin.com/sclsharing/preview?type=SHARE_LOCATION&lat=${report.lat}&lng=${report.lng}&title=${title}`;
                setCoordSheetOpen(false);
                try {
                  await Linking.openURL(url);
                } catch {
                  showToast("error", "Impossible d'ouvrir Navionics.");
                }
              }}
              testID="report-coords-navionics"
              activeOpacity={0.85}
            >
              <View style={[styles.coordIcon, { backgroundColor: "#0077B6" }]}>
                <Ionicons name="boat" size={20} color="#FFFFFF" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.coordOptTitle}>Ouvrir dans Navionics</Text>
                <Text style={styles.coordOptSub}>Carte marine (Garmin)</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.textDim} />
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.coordOption}
              onPress={async () => {
                const url = `https://www.google.com/maps/search/?api=1&query=${report.lat},${report.lng}`;
                setCoordSheetOpen(false);
                try {
                  await Linking.openURL(url);
                } catch {
                  showToast("error", "Impossible d'ouvrir Google Maps.");
                }
              }}
              testID="report-coords-gmaps"
              activeOpacity={0.85}
            >
              <View style={[styles.coordIcon, { backgroundColor: "#34A853" }]}>
                <Ionicons name="map" size={20} color="#FFFFFF" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.coordOptTitle}>Ouvrir dans Google Maps</Text>
                <Text style={styles.coordOptSub}>Itinéraire & vue satellite</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.textDim} />
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.coordOption}
              onPress={async () => {
                try {
                  await Clipboard.setStringAsync(`${report.lat}, ${report.lng}`);
                  setCoordSheetOpen(false);
                  showToast("success", "Coordonnées copiées.");
                } catch {
                  showToast("error", "Copie impossible.");
                }
              }}
              testID="report-coords-copy"
              activeOpacity={0.85}
            >
              <View style={[styles.coordIcon, { backgroundColor: theme.bg3 }]}>
                <Ionicons name="copy" size={20} color={theme.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.coordOptTitle}>Copier les coordonnées</Text>
                <Text style={styles.coordOptSub}>
                  {report.lat.toFixed(5)}, {report.lng.toFixed(5)}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.textDim} />
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.bg },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  iconBtn: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
  },
  dot: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { color: theme.text, fontWeight: "900", fontSize: 18 },
  // 19/07 — badge « TEST » (mode test bêta) accolé au titre.
  testChip: {
    backgroundColor: "#F4A261", borderRadius: 6,
    paddingHorizontal: 6, paddingVertical: 1,
  },
  testChipText: { color: "#04121F", fontWeight: "900", fontSize: 10, letterSpacing: 0.5 },
  sub: { color: theme.textDim, fontSize: 12 },
  scroll: { padding: spacing.md, gap: spacing.sm, paddingBottom: 100 },
  metaCard: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    gap: 8, borderWidth: 1, borderColor: theme.border,
  },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  metaText: { color: theme.text, fontWeight: "600" },
  coords: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  // Phase 3d — coords row is now tappable → uses accent colour + underline.
  coordsLinked: { color: theme.primary, textDecorationLine: "underline" },
  // Phase 3d — Coordinate share sheet.
  coordBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  coordSheet: {
    backgroundColor: theme.bg2, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    paddingHorizontal: spacing.md, paddingTop: spacing.sm, paddingBottom: spacing.lg + 8,
    borderTopWidth: 1, borderColor: theme.border, gap: 6,
  },
  coordHandle: {
    width: 44, height: 4, borderRadius: 2, backgroundColor: theme.border,
    alignSelf: "center", marginBottom: spacing.sm,
  },
  coordHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  coordSheetTitle: { color: theme.text, fontWeight: "900", fontSize: 16 },
  coordSheetSub: {
    color: theme.textDim, fontSize: 12, marginTop: 2,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
  },
  coordCloseBtn: {
    width: 36, height: 36, borderRadius: 18, backgroundColor: theme.bg3,
    alignItems: "center", justifyContent: "center",
  },
  coordOption: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 12, paddingHorizontal: 12,
    borderRadius: radii.md, backgroundColor: theme.bg3, marginTop: 8,
    borderWidth: 1, borderColor: theme.border, minHeight: 60,
  },
  coordIcon: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: "center", justifyContent: "center",
  },
  coordOptTitle: { color: theme.text, fontWeight: "800", fontSize: 14 },
  coordOptSub: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  // Phase E.3 — Cap (heading) card
  capCard: {
    backgroundColor: theme.bg2,
    padding: spacing.md,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: theme.border,
  },
  capRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  capIconWrap: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: "rgba(72,202,228,0.10)",
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "rgba(72,202,228,0.30)",
  },
  capLabel: {
    color: theme.textDim,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.2,
    textTransform: "uppercase",
  },
  capValue: {
    color: theme.text,
    fontSize: 18,
    fontWeight: "900",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    letterSpacing: 0.5,
    marginTop: 2,
  },
  capMeta: {
    color: theme.textMute,
    fontSize: 11,
    marginTop: 2,
    fontStyle: "italic",
  },
  capOriginBadge: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
    marginTop: 4,
    maxWidth: "100%",
  },
  capOriginBadgeManual: {
    backgroundColor: "rgba(72,202,228,0.10)",
    borderColor: "rgba(72,202,228,0.35)",
  },
  capOriginBadgeAuto: {
    backgroundColor: "rgba(255,159,69,0.10)",
    borderColor: "rgba(255,159,69,0.35)",
  },
  capOriginText: {
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  previewHint: {
    position: "absolute",
    right: 8,
    bottom: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "rgba(11,19,43,0.85)",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#48CAE4",
  },
  previewHintText: {
    color: "#FFF",
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  capEditBtnLocked: {
    backgroundColor: "rgba(255,159,69,0.08)",
    borderColor: "rgba(255,159,69,0.5)",
  },
  // ── Sexy locked-feature modal (V1.1) ──────────────────────────────
  lockBackdrop: {
    flex: 1,
    backgroundColor: "rgba(11,19,43,0.85)",
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 24,
  },
  lockSheet: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: "#0B132B",
    borderRadius: 22,
    padding: 22,
    borderWidth: 1,
    borderColor: "#48CAE4",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.5,
    shadowRadius: 20,
    elevation: 12,
    alignItems: "center",
  },
  lockBadge: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: "#FFB84D",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 12,
    shadowColor: "#FFB84D",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.5,
    shadowRadius: 12,
  },
  lockTitle: {
    color: "#FFF",
    fontSize: 18,
    fontWeight: "900",
    textAlign: "center",
    marginBottom: 6,
  },
  lockSubtitle: {
    color: "#B9CEE3",
    fontSize: 13,
    textAlign: "center",
    lineHeight: 18,
    marginBottom: 18,
  },
  lockReqRow: {
    flexDirection: "row",
    gap: 10,
    width: "100%",
    marginBottom: 14,
  },
  lockReqBox: {
    flex: 1,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "rgba(255,184,77,0.35)",
    backgroundColor: "rgba(255,184,77,0.08)",
    padding: 10,
    alignItems: "center",
    gap: 3,
  },
  lockReqBoxOk: {
    borderColor: "rgba(76,217,100,0.45)",
    backgroundColor: "rgba(76,217,100,0.10)",
  },
  lockReqLabel: {
    color: "#8FA0B8",
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.4,
    marginTop: 2,
  },
  lockReqValue: {
    color: "#FFF",
    fontSize: 13,
    fontWeight: "900",
  },
  lockReqStatus: {
    color: "#8FA0B8",
    fontSize: 10,
    fontStyle: "italic",
  },
  lockTipRow: {
    flexDirection: "row",
    gap: 8,
    alignItems: "flex-start",
    backgroundColor: "rgba(72,202,228,0.10)",
    borderRadius: 10,
    padding: 10,
    marginBottom: 16,
    width: "100%",
  },
  lockTip: {
    flex: 1,
    color: "#B9CEE3",
    fontSize: 12,
    lineHeight: 16,
    fontStyle: "italic",
  },
  lockCta: {
    width: "100%",
    backgroundColor: "#48CAE4",
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
  },
  lockCtaText: {
    color: "#0B132B",
    fontSize: 14,
    fontWeight: "900",
    letterSpacing: 0.4,
  },
  capEditBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    borderRadius: radii.md,
    backgroundColor: "rgba(72,202,228,0.10)",
    borderWidth: 1,
    borderColor: theme.primary,
    minHeight: 36,
  },
  capEditText: { color: theme.primary, fontWeight: "800", fontSize: 12 },
  capLockedHint: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: radii.sm,
    backgroundColor: theme.bg3,
    maxWidth: 110,
  },
  capLockedText: { color: theme.textMute, fontSize: 10, fontWeight: "700" },
  // Phase E.3 — drift cone "Cap observé" badge + algo bearing transparency
  driftBadge: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 3,
    backgroundColor: "#FF7A1A",
    borderRadius: 999,
    marginLeft: 24,
    maxWidth: "95%",
  },
  driftBadgeText: {
    color: theme.bg,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.3,
  },
  driftAlgoNote: {
    color: theme.textMute,
    fontSize: 11,
    fontStyle: "italic",
    marginLeft: 24,
  },
  driftAlgoWarn: {
    color: "#FFB84D",
    fontSize: 11,
    fontStyle: "italic",
    marginLeft: 24,
    marginTop: 2,
  },
  idRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: 4, paddingTop: 6,
    borderTopWidth: 1, borderTopColor: theme.border,
    opacity: 0.7,
  },
  idText: {
    flex: 1, color: theme.textMute, fontSize: 11, fontWeight: "600",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    letterSpacing: 0.5,
  },
  descCard: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  descText: { color: theme.text, lineHeight: 20 },
  sectionTitle: {
    color: theme.textDim, fontWeight: "800", fontSize: 12, letterSpacing: 2,
    textTransform: "uppercase", marginTop: spacing.sm,
  },
  gallery: { width: 160, height: 160, borderRadius: radii.md, backgroundColor: theme.bg2 },
  galleryZoomBadge: {
    position: "absolute", top: 6, right: 6,
    width: 22, height: 22, borderRadius: 11,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.25)",
  },
  shareWatermark: {
    marginTop: 4, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4,
    opacity: 0.5,
  },
  shareWatermarkText: { color: theme.textDim, fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  actionsRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  // ── Posts « viraux » Instagram / Facebook / X ──
  socialRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    padding: spacing.sm, marginTop: spacing.sm,
  },
  socialTitle: { color: theme.text, fontWeight: "900", fontSize: 13 },
  socialSub: { color: theme.textMute, fontSize: 10.5, marginTop: 1 },
  socialBtn: {
    width: 44, height: 44, borderRadius: 22,
    alignItems: "center", justifyContent: "center",
  },
  socialCardOffscreen: { position: "absolute", left: -4000, top: 0 },
  justCreatedBanner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: spacing.md, borderRadius: radii.md,
    backgroundColor: "rgba(42,157,143,0.12)", borderWidth: 1, borderColor: theme.success,
    marginTop: spacing.sm,
  },
  justCreatedText: { color: theme.text, flex: 1, fontWeight: "700", fontSize: 13 },
  viewMapSecondary: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: spacing.sm, marginTop: 4,
  },
  viewMapSecondaryText: { color: theme.textDim, fontSize: 13, fontWeight: "700" },
  actionBtn: {
    flex: 1, backgroundColor: theme.primary, padding: 14, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 52,
  },
  actionBtnAlt: {
    flex: 1, backgroundColor: theme.bg2, padding: 14, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 52,
    borderWidth: 1, borderColor: theme.primary,
  },
  actionText: { color: theme.bg, fontWeight: "900", fontSize: 15 },
  emptyChat: {
    color: theme.textMute, textAlign: "center", padding: spacing.md, fontStyle: "italic",
  },
  msg: {
    padding: spacing.sm, borderRadius: radii.md, maxWidth: "85%",
  },
  msgMine: { alignSelf: "flex-end", backgroundColor: theme.primary + "22", borderColor: theme.primary, borderWidth: 1 },
  msgOther: { alignSelf: "flex-start", backgroundColor: theme.bg2, borderColor: theme.border, borderWidth: 1 },
  msgName: { color: theme.primary, fontSize: 11, fontWeight: "700", marginBottom: 2 },
  msgText: { color: theme.text, fontSize: 14, lineHeight: 18 },
  msgTime: { color: theme.textMute, fontSize: 10, marginTop: 4 },
  chatInput: {
    flexDirection: "row", padding: spacing.sm, gap: spacing.sm,
    borderTopWidth: 1, borderTopColor: theme.border, backgroundColor: theme.bg,
  },
  input: {
    flex: 1, backgroundColor: theme.bg2, color: theme.text, paddingHorizontal: spacing.md,
    paddingVertical: 12, borderRadius: radii.pill, borderWidth: 1, borderColor: theme.border,
    minHeight: 44,
  },
  sendBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  flagBanner: {
    flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1,
    padding: spacing.md, borderRadius: radii.md, marginTop: spacing.sm,
  },
  flagText: { color: theme.text, flex: 1, fontWeight: "700", fontSize: 13 },
  editCard: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, gap: 6,
  },
  editCardApplied: { borderColor: theme.success, backgroundColor: "rgba(42,157,143,0.10)" },
  editHeader: { flexDirection: "row", alignItems: "center", gap: 8, justifyContent: "space-between" },
  editKindPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radii.pill, borderWidth: 1,
  },
  editKindText: { fontWeight: "800", fontSize: 12 },
  appliedPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: radii.pill,
    backgroundColor: "rgba(42,157,143,0.18)",
  },
  appliedText: { color: theme.success, fontWeight: "800", fontSize: 11 },
  editAuthor: { color: theme.textDim, fontSize: 12 },
  editShift: { color: theme.warning, fontSize: 13, fontWeight: "700" },
  voteRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4, flexWrap: "wrap" },
  voteBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: radii.pill,
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg3, minHeight: 36,
  },
  voteText: { color: theme.text, fontWeight: "800", fontSize: 13 },
  netText: { color: theme.textMute, fontSize: 11, fontWeight: "700", flex: 1, textAlign: "right" },
  modalBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  modalSheet: {
    backgroundColor: theme.bg2, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: spacing.lg, gap: spacing.sm,
  },
  modalHandle: {
    alignSelf: "center", width: 40, height: 4, borderRadius: 2,
    backgroundColor: theme.textMute, marginBottom: spacing.sm,
  },
  modalTitle: { color: theme.text, fontWeight: "900", fontSize: 18 },
  modalSub: { color: theme.textDim, fontSize: 13, lineHeight: 18 },
  modalOption: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radii.md, borderWidth: 1,
    backgroundColor: theme.bg3, minHeight: 64,
  },
  modalIcon: {
    width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center",
  },
  modalOptLabel: { color: theme.text, fontWeight: "800", fontSize: 15 },
  modalOptDesc: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  modalClose: {
    alignItems: "center", padding: spacing.md, marginTop: spacing.sm,
  },
  modalCloseText: { color: theme.textDim, fontWeight: "700" },
  modalOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(11,19,43,0.5)",
    alignItems: "center", justifyContent: "center",
  },
});
