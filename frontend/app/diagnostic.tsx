// SignalMar — Écran Diagnostic.
// Accessible depuis : Profil → "Diagnostic".
//
// Permet à n'importe quel utilisateur :
//   • de voir l'état réseau / GPS / backend en temps réel,
//   • de pinger le backend pour mesurer la latence,
//   • de consulter les logs persistants des 24 dernières heures,
//   • d'envoyer ces logs au support (contact@seaman.fr) via mail,
//   • de partager les logs en .txt (share sheet) ou de les transmettre
//     automatiquement au backend via /api/diagnostics.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import * as MailComposer from "expo-mail-composer";

import { theme, spacing, radii } from "@/src/lib/theme";
import {
  logger,
  type LogEntry,
  type LogCategory,
} from "@/src/lib/logger";
import {
  snapshot,
  pingBackend,
  type DiagnosticSnapshot,
  type PingResult,
} from "@/src/lib/diagnostics";
import { useAuth } from "@/src/auth/AuthContext";
import { api } from "@/src/api/client";
import { isTestAccount } from "@/src/lib/test-accounts";
import { showToast } from "@/src/components/Toast";
import {
  pickAndSendSupportRecording,
  pickAndSendSupportScreenshots,
} from "@/src/lib/support-upload";

const SUPPORT_EMAIL = "contact@seaman.fr";
const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

type Filter = "all" | "errors" | LogCategory;

/**
 * Bulletproof any value → readable string for a <Text> child.
 *
 * The diagnostic screen renders raw log entries — some of which may have
 * been produced BEFORE the logger's safeStringify was introduced, or come
 * from RN's own ErrorUtils / LogBox capture with an Error instance in the
 * `message`/`data` slot. Trying to render such an object directly crashes
 * with «Objects are not valid as a React child (found: [object Error])».
 * This helper normalises everything back to a string so the crash-report
 * screen itself can never crash — the user always keeps a way out.
 */
function stringifySafe(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean" || typeof v === "bigint") {
    return String(v);
  }
  if (v instanceof Error) {
    // Errors are the most frequent culprit — keep message + stack head.
    const stack = v.stack ? `\n${v.stack.split("\n").slice(0, 3).join("\n")}` : "";
    return `${v.name}: ${v.message}${stack}`;
  }
  try {
    const s = JSON.stringify(v);
    return s ?? String(v);
  } catch {
    return String(v);
  }
}

export default function DiagnosticScreen() {
  const router = useRouter();
  const { user } = useAuth();
  // 10/07/2026 — affichage complet (ping, partage .txt, logs, filtres…)
  // réservé aux comptes de test/QA ; l'utilisateur lambda voit uniquement
  // « État système » + un bouton d'envoi direct des logs au support.
  const advanced = isTestAccount(user?.email);

  const [snap, setSnap] = useState<DiagnosticSnapshot | null>(null);
  const [snapLoading, setSnapLoading] = useState(true);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [ping, setPing] = useState<PingResult | null>(null);
  const [pinging, setPinging] = useState(false);
  const [busy, setBusy] = useState<null | "share" | "mail" | "upload" | "clear" | "video" | "shot" | "inbox">(null);
  // Progression de l'upload vidéo/capture (0-100, null = inactif).
  const [videoPct, setVideoPct] = useState<number | null>(null);
  const [inbox, setInbox] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setSnapLoading(true);
    try {
      const [s, l] = await Promise.all([snapshot(), logger.getAll()]);
      setSnap(s);
      setLogs(l);
    } finally {
      setSnapLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Logs filtrés (ordre : plus récent en premier)
  const filteredLogs = useMemo(() => {
    const arr = filter === "all"
      ? logs
      : filter === "errors"
        ? logs.filter((e) => e.level === "error" || e.level === "warn")
        : logs.filter((e) => e.category === filter);
    return arr.slice().reverse();
  }, [logs, filter]);

  const errorsCount = useMemo(
    () => logs.filter((e) => e.level === "error").length,
    [logs],
  );

  // ── Actions ────────────────────────────────────────────────────────
  async function runPing() {
    setPinging(true);
    logger.event("net", "ping_start");
    const r = await pingBackend();
    logger.event("net", "ping_done", r);
    setPing(r);
    setPinging(false);
  }

  async function buildExport(): Promise<{ text: string; filename: string }> {
    const text = await logger.exportText({
      user_email: user?.email ?? null,
      user_id: user?.user_id ?? null,
      backend: BACKEND_URL,
      snapshot: snap,
      ping,
    });
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    return { text, filename: `signalmar-diagnostic-${stamp}.txt` };
  }

  async function writeTempFile(text: string, filename: string): Promise<string> {
    // Expo SDK 54 — utilise la nouvelle API File / Paths (l'API legacy
    // throw à l'exécution même si le typage l'expose encore).
    const file = new File(Paths.cache, filename);
    try { file.delete(); } catch { /* n'existait pas — OK */ }
    file.create({ overwrite: true, intermediates: true });
    file.write(text);
    return file.uri;
  }

  async function onShareTxt() {
    if (busy) return;
    setBusy("share");
    try {
      const { text, filename } = await buildExport();
      if (Platform.OS === "web") {
        // Sur le web, on télécharge le fichier via un blob
        const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      } else {
        const uri = await writeTempFile(text, filename);
        const can = await Sharing.isAvailableAsync();
        if (!can) {
          Alert.alert("Partage indisponible", "Aucune app de partage n'est disponible sur ce téléphone.");
          return;
        }
        await Sharing.shareAsync(uri, {
          mimeType: "text/plain",
          dialogTitle: "Partager les logs SignalMar",
          UTI: "public.plain-text",
        });
      }
    } catch (e) {
      logger.error("app", "share_failed", e);
      Alert.alert("Erreur", "Impossible de partager le fichier.");
    } finally {
      setBusy(null);
    }
  }

  async function onMailSupport() {
    if (busy) return;
    setBusy("mail");
    try {
      const { text, filename } = await buildExport();
      const available = await MailComposer.isAvailableAsync();
      if (!available) {
        Alert.alert(
          "Mail indisponible",
          `Configurez un compte mail sur le téléphone, ou copiez les logs et envoyez-les manuellement à ${SUPPORT_EMAIL}.`,
        );
        return;
      }
      const uri = await writeTempFile(text, filename);
      const summary = `Bonjour,\n\nVoici les logs de diagnostic SignalMar (24h) pour analyse.\n\n` +
        `Utilisateur : ${user?.email ?? "—"}\n` +
        `Date : ${new Date().toLocaleString("fr-FR")}\n` +
        `Plateforme : ${Platform.OS} ${Platform.Version ?? ""}\n\n` +
        `Description du problème :\n[ décris ici ce qu'il s'est passé ]\n\n` +
        `— Envoyé depuis l'app SignalMar`;
      await MailComposer.composeAsync({
        recipients: [SUPPORT_EMAIL],
        subject: `[SignalMar] Diagnostic — ${new Date().toLocaleDateString("fr-FR")}`,
        body: summary,
        isHtml: false,
        attachments: [uri],
      });
      logger.event("app", "mail_compose_opened");
      // Once the mail composer is dismissed, close the diagnostic screen so
      // the user is never stranded on the log page with no obvious exit.
      showToast(
        "success",
        "Merci ! Vous pouvez continuer à utiliser SignalMar.",
      );
      setTimeout(() => {
        if (router.canGoBack()) router.back();
        else router.replace("/(tabs)/map");
      }, 400);
    } catch (e) {
      logger.error("app", "mail_failed", e);
      Alert.alert("Erreur", "Impossible d'ouvrir l'app mail.");
    } finally {
      setBusy(null);
    }
  }

  async function onUploadToBackend() {
    if (busy) return;
    setBusy("upload");
    try {
      const { text } = await buildExport();
      // 02/08/2026 — passe par le client API (priorité haute + ré-essai sur
      // 429/50x de l'ingress) : un `fetch` brut perdait l'envoi dès qu'une
      // rafale de tuiles saturait le quota de la plateforme.
      const j = await api.sendDiagnostics({
        snapshot: snap,
        logs_text: text,
        user_email: user?.email ?? null,
        user_id: user?.user_id ?? null,
        note: null,
      });
      logger.event("app", "diagnostic_uploaded", { id: j.id });
      showToast("success", "Diagnostic transmis au support. Merci !");
      setTimeout(() => {
        if (router.canGoBack()) router.back();
        else router.replace("/(tabs)/map");
      }, 600);
    } catch (e) {
      logger.error("app", "upload_failed", e);
      Alert.alert(
        "Échec",
        "L'envoi au backend a échoué. Tu peux toujours utiliser « Envoyer par mail » ou « Partager le .txt ».",
      );
    } finally {
      setBusy(null);
    }
  }

  async function onSendRecording() {
    if (busy) return;
    setBusy("video");
    try {
      const sent = await pickAndSendSupportRecording((pct) => setVideoPct(pct));
      if (sent) {
        logger.event("app", "support_recording_uploaded");
        showToast("success", "Enregistrement transmis au support. Merci !");
      }
    } catch (e) {
      logger.error("app", "support_recording_failed", e);
      Alert.alert(
        "Échec de l'envoi",
        "L'envoi de l'enregistrement a échoué (réseau ?). Réessayez, ou envoyez les logs par mail.",
      );
    } finally {
      setBusy(null);
      setVideoPct(null);
    }
  }

  async function onSendScreenshots() {
    if (busy) return;
    setBusy("shot");
    try {
      const sent = await pickAndSendSupportScreenshots((pct) => setVideoPct(pct));
      if (sent > 0) {
        logger.event("app", "support_screenshots_uploaded", { count: sent });
        showToast(
          "success",
          sent > 1
            ? `${sent} captures transmises au support. Merci !`
            : "Capture transmise au support. Merci !",
        );
      }
    } catch (e) {
      logger.error("app", "support_screenshots_failed", e);
      Alert.alert(
        "Échec de l'envoi",
        "L'envoi des captures a échoué (réseau ?). Réessayez, ou envoyez les logs par mail.",
      );
    } finally {
      setBusy(null);
      setVideoPct(null);
    }
  }

  /** 03/08/2026 — dit à l'armateur ce que le serveur a RÉELLEMENT reçu. */
  async function onCheckInbox() {
    if (busy) return;
    setBusy("inbox");
    setInbox(null);
    try {
      const r = await api.supportInbox();
      const s = r.screenshots[0];
      const f = r.files[0];
      const l = r.logs[0];
      const fmt = (iso?: string | null) =>
        iso ? new Date(iso).toLocaleString("fr-FR") : "—";
      setInbox(
        `Reçu côté support :\n` +
          `• ${r.screenshots.length} capture(s) — dernière : ${s ? `${s.id} le ${fmt(s.created_at)}${s.has_image ? "" : " (contexte seul, sans image)"}` : "aucune"}\n` +
          `• ${r.files.length} fichier(s) — dernier : ${f ? `${f.filename} (${Math.round(f.size_bytes / 1024)} Ko) le ${fmt(f.modified_at)}` : "aucun"}\n` +
          `• ${r.logs.length} envoi(s) de logs — dernier : ${fmt(l?.created_at)}`,
      );
    } catch (e) {
      logger.error("app", "support_inbox_failed", e);
      setInbox("Impossible de joindre le support (réseau ?). Réessayez.");
    } finally {
      setBusy(null);
    }
  }

  function onClearLogs() {    Alert.alert(
      "Vider les logs ?",
      "Tous les logs locaux (24h) seront effacés. L'instantané système reste disponible.",
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Vider",
          style: "destructive",
          onPress: async () => {
            setBusy("clear");
            try {
              await logger.clear();
              setLogs([]);
              logger.event("app", "logs_cleared_by_user");
            } finally {
              setBusy(null);
            }
          },
        },
      ],
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Diagnostic", headerShown: false }} />

      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          hitSlop={{ top: 10, right: 10, bottom: 10, left: 10 }}
          testID="diag-back"
        >
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Diagnostic</Text>
        <TouchableOpacity
          onPress={refresh}
          hitSlop={{ top: 10, right: 10, bottom: 10, left: 10 }}
          testID="diag-refresh"
        >
          <Ionicons name="refresh" size={22} color={theme.primary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator>
        {/* État système */}
        <Text style={styles.sectionTitle}>État système</Text>
        {snapLoading || !snap ? (
          <View style={styles.card}><ActivityIndicator color={theme.primary} /></View>
        ) : (
          <View style={styles.card}>
            <Row label="Réseau">
              <StatusDot ok={snap.network.isConnected === true && snap.network.isInternetReachable !== false} />
              <Text style={styles.value}>
                {snap.network.isConnected === false
                  ? "Hors-ligne"
                  : snap.network.isInternetReachable === false
                    ? "Connecté sans Internet"
                    : "En ligne"}
                {snap.network.type ? ` · ${snap.network.type}` : ""}
              </Text>
            </Row>
            <Row label="GPS — permission">
              <StatusDot ok={snap.gps.permission === "granted"} />
              <Text style={styles.value}>{snap.gps.permission ?? "—"}</Text>
            </Row>
            <Row label="GPS — service activé">
              <StatusDot ok={snap.gps.servicesEnabled === true} />
              <Text style={styles.value}>{snap.gps.servicesEnabled === null ? "—" : (snap.gps.servicesEnabled ? "Oui" : "Non")}</Text>
            </Row>
            <Row label="Dernière position">
              <Text style={[styles.value, { flex: 1 }]} numberOfLines={2}>
                {snap.gps.lastFix
                  ? `${snap.gps.lastFix.lat.toFixed(5)}, ${snap.gps.lastFix.lng.toFixed(5)}  ` +
                    `(±${snap.gps.lastFix.accuracyM?.toFixed(0) ?? "?"} m, ${snap.gps.lastFix.ageS ?? "?"} s)`
                  : snap.gps.error ?? "—"}
              </Text>
            </Row>
            <Row label="App">
              <Text style={[styles.value, { flex: 1 }]} numberOfLines={1}>
                {snap.app.name} {snap.app.version ?? ""}{snap.app.build ? ` (${snap.app.build})` : ""}
              </Text>
            </Row>
            <Row label="Appareil">
              <Text style={[styles.value, { flex: 1 }]} numberOfLines={1}>
                {snap.device.brand ?? "?"} {snap.device.modelName ?? ""} — {snap.device.platform} {snap.device.osVersion ?? ""}
              </Text>
            </Row>
            <Row label="Backend">
              <Text style={[styles.value, { flex: 1 }]} numberOfLines={1}>{snap.backend.url || "—"}</Text>
            </Row>
          </View>
        )}

        {/* Ping backend — vue avancée (admin/QA) uniquement. */}
        {advanced && (
          <>
            <Text style={styles.sectionTitle}>Test backend</Text>
            <View style={styles.card}>
              <TouchableOpacity
                style={[styles.btn, styles.btnPrimary]}
                onPress={runPing}
                disabled={pinging}
                testID="diag-ping"
                activeOpacity={0.85}
              >
                {pinging
                  ? <ActivityIndicator color={theme.bg} />
                  : <>
                      <Ionicons name="pulse" size={16} color={theme.bg} />
                      <Text style={styles.btnPrimaryLabel}>Ping backend</Text>
                    </>}
              </TouchableOpacity>
              {ping && (
                <View style={[styles.pingResult, { borderColor: ping.ok ? theme.success : theme.danger }]}>
                  <Ionicons
                    name={ping.ok ? "checkmark-circle" : "close-circle"}
                    size={18}
                    color={ping.ok ? theme.success : theme.danger}
                  />
                  <Text style={[styles.value, { flex: 1 }]} numberOfLines={2}>
                    {ping.ok ? `HTTP ${ping.status} en ${ping.latencyMs} ms` : `${ping.error} (${ping.latencyMs} ms)`}
                  </Text>
                </View>
              )}
            </View>
          </>
        )}

        {/* Envoi d'une capture vidéo / d'écran au support (13/07/2026).
            Visible pour TOUS : c'est le moyen le plus simple de montrer un
            bug. Upload chunké 512 Ko + barre de progression. */}
        <Text style={styles.sectionTitle}>Capture vidéo / écran</Text>
        <View style={styles.card}>
          <TouchableOpacity
            style={[styles.btn, styles.btnPrimary]}
            onPress={onSendRecording}
            disabled={!!busy}
            testID="diag-send-recording"
            activeOpacity={0.85}
          >
            {busy === "video"
              ? <ActivityIndicator color={theme.bg} />
              : <>
                  <Ionicons name="videocam" size={16} color={theme.bg} />
                  <Text style={styles.btnPrimaryLabel}>{"Envoyer un enregistrement d'écran"}</Text>
                </>}
          </TouchableOpacity>
          <View style={{ height: spacing.xs }} />
          <TouchableOpacity
            style={[styles.btn, styles.btnPrimary]}
            onPress={onSendScreenshots}
            disabled={!!busy}
            testID="diag-send-screenshot"
            activeOpacity={0.85}
          >
            {busy === "shot"
              ? <ActivityIndicator color={theme.bg} />
              : <>
                  <Ionicons name="image" size={16} color={theme.bg} />
                  <Text style={styles.btnPrimaryLabel}>{"Envoyer des captures d'écran (max 5)"}</Text>
                </>}
          </TouchableOpacity>
          {videoPct != null && (
            <View style={styles.progressWrap} testID="diag-upload-progress">
              <View style={styles.progressTrack}>
                <View style={[styles.progressFill, { width: `${videoPct}%` }]} />
              </View>
              <Text style={styles.progressLabel}>
                {videoPct < 100 ? `Envoi en cours… ${videoPct} %` : "Finalisation…"}
              </Text>
            </View>
          )}
          <Text style={styles.helpText}>
            {"Vidéo : 100 Mo max. Captures d'écran : jusqu'à 5 photos en une fois. Les fichiers sont transmis au support pour analyse, puis supprimés automatiquement après 12 h."}
          </Text>
          {/* 03/08/2026 (demande armateur : « hier je t'ai envoyé les captures
              et tu n'as rien reçu ») — CONTRÔLE DE RÉCEPTION : on interroge le
              serveur pour afficher ce qu'il a RÉELLEMENT enregistré. Plus
              besoin de deviner si un envoi est passé. */}
          <View style={{ height: spacing.xs }} />
          <TouchableOpacity
            style={[styles.btn, styles.btnSecondary]}
            onPress={onCheckInbox}
            disabled={!!busy}
            testID="diag-check-inbox"
            activeOpacity={0.85}
          >
            {busy === "inbox"
              ? <ActivityIndicator color={theme.primary} />
              : <>
                  <Ionicons name="checkmark-done" size={16} color={theme.primary} />
                  <Text style={styles.btnSecondaryLabel}>{"Vérifier la réception côté support"}</Text>
                </>}
          </TouchableOpacity>
          {inbox != null && (
            <Text style={styles.helpText} testID="diag-inbox-result">{inbox}</Text>
          )}
        </View>

        {/* Actions de partage */}
        <Text style={styles.sectionTitle}>Envoyer les logs</Text>
        <View style={styles.card}>
          <TouchableOpacity
            style={[styles.btn, styles.btnPrimary]}
            onPress={onMailSupport}
            disabled={!!busy}
            testID="diag-mail"
            activeOpacity={0.85}
          >
            {busy === "mail"
              ? <ActivityIndicator color={theme.bg} />
              : <>
                  <Ionicons name="mail" size={16} color={theme.bg} />
                  <Text style={styles.btnPrimaryLabel}>Envoyer par mail au support</Text>
                </>}
          </TouchableOpacity>
          <Text style={styles.helpText}>{`Destinataire pré-rempli : ${SUPPORT_EMAIL}`}</Text>

          {/* Partage .txt + upload backend — vue avancée uniquement.
              L'utilisateur standard n'a que le bouton mail ci-dessus. */}
          {advanced && (
            <>
              <View style={{ height: spacing.sm }} />

              <View style={styles.row2}>
                <TouchableOpacity
                  style={[styles.btn, styles.btnSecondary, { flex: 1 }]}
                  onPress={onShareTxt}
                  disabled={!!busy}
                  testID="diag-share"
                  activeOpacity={0.85}
                >
                  {busy === "share"
                    ? <ActivityIndicator color={theme.primary} />
                    : <>
                        <Ionicons name="share-outline" size={16} color={theme.primary} />
                        <Text style={styles.btnSecondaryLabel}>Partager .txt</Text>
                      </>}
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.btn, styles.btnSecondary, { flex: 1 }]}
                  onPress={onUploadToBackend}
                  disabled={!!busy}
                  testID="diag-upload"
                  activeOpacity={0.85}
                >
                  {busy === "upload"
                    ? <ActivityIndicator color={theme.primary} />
                    : <>
                        <Ionicons name="cloud-upload-outline" size={16} color={theme.primary} />
                        <Text style={styles.btnSecondaryLabel}>Envoyer au support</Text>
                      </>}
                </TouchableOpacity>
              </View>
            </>
          )}
        </View>

        {/* Logs + filtres + purge — vue avancée (admin/QA) uniquement.
            L'utilisateur standard envoie ses logs par mail sans les voir. */}
        {advanced && (<>
        <View style={styles.logsHeader}>
          <Text style={styles.sectionTitle}>Logs ({logs.length})</Text>
          {errorsCount > 0 && (
            <View style={styles.errorPill}>
              <Ionicons name="alert-circle" size={12} color="#fff" />
              <Text style={styles.errorPillText}>{errorsCount} erreurs</Text>
            </View>
          )}
        </View>
        <View style={styles.filterRow}>
          {(["all", "errors", "nav", "gps", "api", "net", "auth", "push"] as Filter[]).map((f) => (
            <TouchableOpacity
              key={f}
              style={[styles.chip, filter === f && styles.chipOn]}
              onPress={() => setFilter(f)}
              testID={`diag-filter-${f}`}
              activeOpacity={0.8}
            >
              <Text style={[styles.chipLabel, filter === f && { color: theme.bg }]}>
                {f === "all" ? "Tous" : f === "errors" ? "Erreurs" : f}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {filteredLogs.length === 0 ? (
          <View style={styles.card}>
            <Text style={styles.helpText}>Aucune entrée pour ce filtre.</Text>
          </View>
        ) : (
          filteredLogs.slice(0, 200).map((e, i) => {
            const color =
              e.level === "error" ? theme.danger :
              e.level === "warn"  ? theme.warning :
              theme.textDim;
            return (
              <View key={`${e.ts}-${i}`} style={styles.logCard}>
                <View style={styles.logHead}>
                  <Text style={[styles.logLevel, { color }]}>{String(e.level).toUpperCase()}</Text>
                  <Text style={styles.logCat}>{String(e.category)}</Text>
                  <Text style={styles.logTs}>{new Date(e.ts).toLocaleTimeString("fr-FR")}</Text>
                </View>
                {/* Guarantee text-only children (Phase K.16 hardening) — some
                    legacy log entries may carry non-string `message`/`data`
                    payloads (e.g. Error objects captured by ErrorUtils) that
                    would crash RN's Text with
                    "Objects are not valid as a React child (found: [object Error])".
                    `stringifySafe` normalises Errors → readable message + stack,
                    plain objects → JSON, primitives → String, so the screen
                    never crashes even on hostile input. */}
                <Text style={styles.logMsg}>{stringifySafe(e.message)}</Text>
                {e.data != null && e.data !== "" ? (
                  <Text style={styles.logData} numberOfLines={4}>{stringifySafe(e.data)}</Text>
                ) : null}
              </View>
            );
          })
        )}
        {filteredLogs.length > 200 && (
          <Text style={styles.helpText}>… {filteredLogs.length - 200} entrées supplémentaires (export complet via partage).</Text>
        )}

        <TouchableOpacity
          style={[styles.btn, styles.btnDanger, { marginTop: spacing.md }]}
          onPress={onClearLogs}
          disabled={!!busy}
          testID="diag-clear"
          activeOpacity={0.85}
        >
          <Ionicons name="trash-outline" size={16} color={theme.danger} />
          <Text style={styles.btnDangerLabel}>Vider les logs locaux</Text>
        </TouchableOpacity>
        </>)}

        {/* Explicit return CTA — avoids leaving the user stranded on the
            diagnostic page after sending / sharing / consulting logs. */}
        <TouchableOpacity
          style={[styles.btn, styles.btnReturn, { marginTop: spacing.lg }]}
          onPress={() => {
            if (router.canGoBack()) router.back();
            else router.replace("/(tabs)/map");
          }}
          testID="diag-return"
          activeOpacity={0.85}
        >
          <Ionicons name="chevron-back" size={18} color={theme.bg} />
          <Text style={styles.btnReturnLabel}>Retour à SignalMar</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.rowItem}>
      <Text style={styles.rowLabel}>{label}</Text>
      <View style={styles.rowVal}>{children}</View>
    </View>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <View style={[styles.dot, { backgroundColor: ok ? theme.success : theme.danger }]} />
  );
}

// ── Styles ──────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  headerTitle: { color: theme.text, fontWeight: "900", fontSize: 16 },
  scroll: { padding: spacing.md, gap: spacing.sm, paddingBottom: spacing.xl },

  sectionTitle: {
    color: theme.text, fontWeight: "900", fontSize: 12,
    letterSpacing: 0.4, marginTop: spacing.sm, textTransform: "uppercase",
  },

  card: {
    backgroundColor: theme.bg2,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: theme.border,
    padding: spacing.sm,
    gap: spacing.xs,
  },
  rowItem: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 6,
    gap: spacing.sm,
  },
  rowLabel: { color: theme.textDim, fontSize: 12, width: 110, fontWeight: "700" },
  rowVal: { flex: 1, flexDirection: "row", alignItems: "center", gap: 6 },
  value: { color: theme.text, fontSize: 13 },
  dot: { width: 8, height: 8, borderRadius: 4 },

  btn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: spacing.md,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: "transparent",
  },
  btnPrimary: { backgroundColor: theme.primary },
  btnPrimaryLabel: { color: theme.bg, fontWeight: "900", fontSize: 13 },
  btnSecondary: { backgroundColor: theme.bg, borderColor: theme.primary + "66" },
  btnSecondaryLabel: { color: theme.primary, fontWeight: "800", fontSize: 12 },
  btnDanger: { backgroundColor: theme.bg, borderColor: theme.danger + "55" },
  btnDangerLabel: { color: theme.danger, fontWeight: "800", fontSize: 12 },
  // V1.2 — persistent "Retour à SignalMar" CTA at the bottom of the screen.
  btnReturn: { backgroundColor: theme.primary, borderColor: theme.primary, minHeight: 48 },
  btnReturnLabel: { color: theme.bg, fontWeight: "900", fontSize: 14 },
  row2: { flexDirection: "row", gap: spacing.sm },

  pingResult: {
    marginTop: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: spacing.sm,
    paddingVertical: 10,
    borderRadius: radii.md,
    borderWidth: 1,
  },

  helpText: { color: theme.textMute, fontSize: 11, fontStyle: "italic" },

  // Barre de progression de l'upload vidéo/capture au support.
  progressWrap: { marginTop: spacing.xs, gap: 4 },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: theme.bg,
    borderWidth: 1,
    borderColor: theme.border,
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    borderRadius: 4,
    backgroundColor: theme.primary,
  },
  progressLabel: { color: theme.textDim, fontSize: 11, fontWeight: "700" },

  logsHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  errorPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: theme.danger,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radii.pill,
  },
  errorPillText: { color: "#fff", fontWeight: "900", fontSize: 11 },

  filterRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginBottom: spacing.xs,
  },
  chip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radii.pill,
    backgroundColor: theme.bg2,
    borderWidth: 1,
    borderColor: theme.border,
  },
  chipOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  chipLabel: { color: theme.text, fontWeight: "800", fontSize: 11 },

  logCard: {
    backgroundColor: theme.bg2,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 8,
  },
  logHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  logLevel: { fontSize: 10, fontWeight: "900" },
  logCat: { color: theme.textDim, fontSize: 10, fontWeight: "700", textTransform: "uppercase" },
  logTs: { color: theme.textMute, fontSize: 10, marginLeft: "auto" },
  logMsg: { color: theme.text, fontSize: 12, marginTop: 4 },
  logData: { color: theme.textDim, fontSize: 10, marginTop: 2, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" },
});
