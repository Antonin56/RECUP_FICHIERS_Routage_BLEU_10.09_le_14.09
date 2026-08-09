/**
 * Écran « Parrainer par SMS » (10/07/2026) — mécanique unique de partage.
 *
 * Remplace le partage générique (WhatsApp & co) partout où l'on partage
 * SignalMar : on choisit un ou plusieurs contacts du téléphone (recherche
 * par NOM), on valide, et UN SMS GROUPÉ prérempli s'ouvre dans l'app
 * Messages avec l'URL d'affiliation parrain-filleul (/api/join?ref=CODE).
 * iOS/Android interdisent l'envoi automatique : l'utilisateur appuie
 * lui-même sur Envoyer — le SMS part de SON numéro (confiance maximale).
 *
 * Modes (via params expo-router) :
 *   • défaut                → message de parrainage de l'app (shareAppMessage).
 *   • type_label/coords     → partage d'un signalement (shareReportMessage).
 *   • group_name/group_code → invitation à un GROUPE privé (shareGroupMessage,
 *     branché sur « Partager l'invitation » du détail de groupe, 11/07).
 *
 * Contrat permissions respecté : intro contextuelle → demande → refus
 * (retry si canAskAgain, sinon « Ouvrir les Réglages ») — et à chaque état
 * un lien « Partager autrement… » (feuille de partage classique) pour ne
 * jamais bloquer. Sur web (preview), les contacts n'existent pas → carte
 * fallback avec partage classique uniquement.
 */
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Linking,
  Platform,
  Share,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import * as SMS from "expo-sms";
import * as Haptics from "expo-haptics";

import { useAuth } from "@/src/auth/AuthContext";
import { api } from "@/src/api/client";
import {
  loadLocalContacts,
  requestContactsPermission,
  type LocalPhoneInfo,
} from "@/src/lib/contact-sync";
import { shareAppMessage, shareGroupMessage, shareReportMessage } from "@/src/lib/share-app";
import { ContactsRefreshButton } from "@/src/components/ContactsRefreshButton";
import { showToast } from "@/src/components/Toast";
import { logger } from "@/src/lib/logger";
import { radii, spacing, theme } from "@/src/lib/theme";

type PermState = "idle" | "granted" | "denied_retry" | "denied_settings";

/** Minuscules sans accents pour la recherche par nom. */
function normalizeName(s: string): string {
  return s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

export default function ShareInviteScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{
    type_label?: string;
    coords?: string;
    description?: string;
    group_name?: string;
    group_code?: string;
  }>();
  const isReport = !!params.type_label;
  const isGroup = !!params.group_code;

  const message = useMemo(() => {
    if (isGroup) {
      return shareGroupMessage({
        groupName: String(params.group_name || "Mon groupe"),
        inviteCode: String(params.group_code),
        refCode: user?.referral_code,
      });
    }
    if (isReport) {
      return shareReportMessage({
        typeLabel: String(params.type_label),
        coords: params.coords ? String(params.coords) : undefined,
        description: params.description ? String(params.description) : undefined,
        refCode: user?.referral_code,
      });
    }
    return shareAppMessage(user?.referral_code);
  }, [isGroup, params.group_name, params.group_code, isReport, params.type_label, params.coords, params.description, user?.referral_code]);

  const [perm, setPerm] = useState<PermState>("idle");
  const [scanning, setScanning] = useState(false);
  const [contacts, setContacts] = useState<LocalPhoneInfo[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sending, setSending] = useState(false);

  // ── Partage classique (feuille native WhatsApp & co) — jamais bloqué. ──
  const shareClassic = useCallback(async () => {
    try {
      await Share.share({ message });
    } catch { /* user dismissed */ }
  }, [message]);

  // 1 ligne par CONTACT (pas par numéro) : on garde le premier numéro.
  const dedupeByContact = useCallback((all: LocalPhoneInfo[]): LocalPhoneInfo[] => {
    const byContact = new Map<string, LocalPhoneInfo>();
    for (const c of all) {
      if (!byContact.has(c.contactId)) byContact.set(c.contactId, c);
    }
    return Array.from(byContact.values())
      .sort((a, b) => a.displayName.localeCompare(b.displayName, "fr"));
  }, []);

  const loadContacts = useCallback(async () => {
    setScanning(true);
    try {
      // Cache 30 j (contact-sync) — instantané après la 1ʳᵉ lecture.
      const all = await loadLocalContacts();
      const list = dedupeByContact(all);
      setContacts(list);
      logger.event("app", "referral_contacts_loaded", { count: list.length });
    } catch (e) {
      logger.error("app", "referral_contacts_failed", { error: (e as Error).message });
      showToast("error", "Impossible de lire les contacts");
    } finally {
      setScanning(false);
    }
  }, [dedupeByContact]);

  const askPermission = useCallback(async () => {
    const { granted, canAskAgain } = await requestContactsPermission();
    if (granted) {
      setPerm("granted");
      await loadContacts();
    } else {
      setPerm(canAskAgain ? "denied_retry" : "denied_settings");
    }
  }, [loadContacts]);

  const openSettings = () => {
    Linking.openSettings().catch(() => {
      Alert.alert(
        "Ouverture impossible",
        "Ouvre les réglages de ton téléphone → SignalMar → Contacts.",
      );
    });
  };

  const toggle = (contactId: string) => {
    Haptics.selectionAsync().catch(() => {});
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(contactId)) next.delete(contactId);
      else next.add(contactId);
      return next;
    });
  };

  // ── Envoi : UN SMS groupé à tous les contacts choisis. ──
  const sendSms = async () => {
    if (selected.size === 0 || sending) return;
    setSending(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    try {
      const chosen = contacts.filter((c) => selected.has(c.contactId));
      const numbers = chosen.map((c) => c.e164);
      // Enregistre les invitations côté serveur (hashes uniquement) pour que
      // le filleul retrouve automatiquement son parrain à l'inscription.
      if (!isReport) {
        api.referralInvitationsCreate(chosen.map((c) => c.hash)).catch(() => {});
      }
      const available = await SMS.isAvailableAsync();
      if (!available) {
        // Pas de messagerie SMS (tablette wifi, simulateur…) → classique.
        await shareClassic();
        return;
      }
      const { result } = await SMS.sendSMSAsync(numbers, message);
      logger.event("app", "referral_sms_composed", {
        recipients: numbers.length, result, report: isReport,
      });
      if (result !== "cancelled") {
        showToast("success", "SMS prêt dans ta messagerie 📨");
        router.back();
      }
    } catch (e) {
      showToast("error", (e as Error).message || "Envoi impossible");
    } finally {
      setSending(false);
    }
  };

  const filtered = useMemo(() => {
    const q = normalizeName(query.trim());
    if (!q) return contacts;
    return contacts.filter((c) => normalizeName(c.displayName).includes(q));
  }, [contacts, query]);

  const title = isGroup
    ? "Inviter au groupe"
    : isReport
      ? "Partager ce signalement"
      : "Parrainer des contacts";

  // ── Lien secondaire discret, présent sur tous les états. ──
  const classicLink = (
    <TouchableOpacity
      style={styles.classicLink}
      onPress={shareClassic}
      testID="share-classic-link"
    >
      <Ionicons name="ellipsis-horizontal-circle-outline" size={16} color={theme.textDim} />
      <Text style={styles.classicLinkTxt}>Partager autrement… (WhatsApp, e-mail…)</Text>
    </TouchableOpacity>
  );

  const renderIntro = () => (
    <View style={styles.introCard}>
      <Ionicons name="chatbubbles" size={60} color={theme.primary} />
      <Text style={styles.introTitle}>
        {isGroup
          ? `Invite tes contacts dans « ${params.group_name || "ton groupe"} »`
          : isReport
            ? "Envoie ce signalement par SMS"
            : "Invite tes contacts par SMS"}
      </Text>
      <Text style={styles.introBody}>
        {isGroup
          ? "Choisis un ou plusieurs contacts (recherche par nom) : un SMS prérempli s'ouvrira avec le code du groupe et ton lien — il part de TON numéro, tes proches savent que c'est toi."
          : `Choisis un ou plusieurs contacts : un SMS prérempli s'ouvrira avec ton lien personnel${!isReport ? " de parrainage" : ""} — il part de TON numéro, tes proches savent que c'est toi.`}
      </Text>
      {!isReport && (
        <View style={styles.bonusBox}>
          <Ionicons name="sparkles" size={15} color="#FFD166" />
          <Text style={styles.bonusTxt}>
            Chaque filleul actif = +1 mois de Premium pour toi
          </Text>
        </View>
      )}
      <TouchableOpacity
        style={styles.primaryBtn}
        onPress={askPermission}
        testID="referral-grant-contacts"
      >
        <Ionicons name="people" size={18} color={theme.bg} />
        <Text style={styles.primaryBtnTxt}>Choisir dans mes contacts</Text>
      </TouchableOpacity>
      {classicLink}
    </View>
  );

  const renderDenied = (canRetry: boolean) => (
    <View style={styles.introCard}>
      <Ionicons name="lock-closed" size={54} color={theme.warning} />
      <Text style={styles.introTitle}>Accès aux contacts refusé</Text>
      <Text style={styles.introBody}>
        {canRetry
          ? "Tu peux réessayer, ou utiliser le partage classique."
          : "Ouvre les réglages de ton téléphone et autorise l'accès aux contacts pour SignalMar."}
      </Text>
      <TouchableOpacity
        style={styles.primaryBtn}
        onPress={canRetry ? askPermission : openSettings}
      >
        <Ionicons name={canRetry ? "refresh" : "settings-outline"} size={18} color={theme.bg} />
        <Text style={styles.primaryBtnTxt}>
          {canRetry ? "Réessayer" : "Ouvrir les Réglages"}
        </Text>
      </TouchableOpacity>
      {classicLink}
    </View>
  );

  const renderWebFallback = () => (
    <View style={styles.introCard}>
      <Ionicons name="phone-portrait-outline" size={54} color={theme.primary} />
      <Text style={styles.introTitle}>Disponible sur téléphone</Text>
      <Text style={styles.introBody}>
        La sélection de contacts et l&apos;envoi de SMS fonctionnent depuis
        l&apos;app sur ton téléphone. Tu peux quand même partager ton lien :
      </Text>
      <TouchableOpacity style={styles.primaryBtn} onPress={shareClassic}>
        <Ionicons name="share-social" size={18} color={theme.bg} />
        <Text style={styles.primaryBtnTxt}>Partager mon lien</Text>
      </TouchableOpacity>
    </View>
  );

  const renderContactRow = ({ item }: { item: LocalPhoneInfo }) => {
    const isSelected = selected.has(item.contactId);
    return (
      <TouchableOpacity
        style={[styles.row, isSelected && styles.rowSelected]}
        onPress={() => toggle(item.contactId)}
        activeOpacity={0.85}
        testID={`referral-contact-${item.contactId}`}
      >
        <View style={[styles.checkbox, isSelected && styles.checkboxOn]}>
          {isSelected ? <Ionicons name="checkmark" size={16} color={theme.bg} /> : null}
        </View>
        {item.image ? (
          <Image source={{ uri: item.image }} style={styles.avatar} />
        ) : (
          <View style={[styles.avatar, styles.avatarFallback]}>
            <Text style={{ color: theme.primary, fontWeight: "800" }}>
              {item.displayName.slice(0, 1).toUpperCase()}
            </Text>
          </View>
        )}
        <View style={{ flex: 1 }}>
          <Text style={styles.contactName} numberOfLines={1}>{item.displayName}</Text>
          <Text style={styles.contactPhone} numberOfLines={1}>{item.e164}</Text>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.headerBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle} numberOfLines={1}>{title}</Text>
        {Platform.OS !== "web" && perm === "granted" && !scanning ? (
          <ContactsRefreshButton
            compact
            onRefreshed={(all) => setContacts(dedupeByContact(all))}
            testID="referral-contacts-refresh"
          />
        ) : (
          <View style={{ width: 44 }} />
        )}
      </View>

      {Platform.OS === "web" ? (
        renderWebFallback()
      ) : perm === "idle" ? (
        renderIntro()
      ) : perm === "denied_retry" ? (
        renderDenied(true)
      ) : perm === "denied_settings" ? (
        renderDenied(false)
      ) : scanning ? (
        <View style={styles.centered}>
          <ActivityIndicator color={theme.primary} size="large" />
          <Text style={styles.centerTxt}>Lecture de tes contacts…</Text>
        </View>
      ) : (
        <>
          {/* Recherche par NOM (jamais par numéro). */}
          <View style={styles.searchWrap}>
            <Ionicons name="search" size={16} color={theme.textDim} />
            <TextInput
              style={styles.searchInput}
              value={query}
              onChangeText={setQuery}
              placeholder="Rechercher un nom…"
              placeholderTextColor={theme.textMute}
              autoCorrect={false}
              clearButtonMode="while-editing"
              testID="referral-search"
            />
            {query.length > 0 && (
              <TouchableOpacity onPress={() => setQuery("")} hitSlop={8}>
                <Ionicons name="close-circle" size={18} color={theme.textDim} />
              </TouchableOpacity>
            )}
          </View>

          <FlatList
            data={filtered}
            keyExtractor={(c) => c.contactId}
            renderItem={renderContactRow}
            ItemSeparatorComponent={() => <View style={styles.separator} />}
            contentContainerStyle={{ padding: spacing.md, paddingBottom: 170 }}
            keyboardShouldPersistTaps="handled"
            ListEmptyComponent={
              <View style={{ alignItems: "center", paddingTop: 40, gap: 8 }}>
                <Ionicons name="sad-outline" size={40} color={theme.textMute} />
                <Text style={styles.centerTxt}>
                  {query ? "Aucun contact ne correspond." : "Aucun contact avec numéro."}
                </Text>
              </View>
            }
          />

          {/* Footer sticky : CTA SMS groupé + partage classique discret. */}
          <View style={styles.footer} pointerEvents="box-none">
            <TouchableOpacity
              style={[styles.sendBtn, (selected.size === 0 || sending) && styles.sendBtnDisabled]}
              onPress={sendSms}
              disabled={selected.size === 0 || sending}
              activeOpacity={0.85}
              testID="referral-send-sms"
            >
              {sending ? (
                <ActivityIndicator color={theme.bg} />
              ) : (
                <Ionicons name="chatbubble-ellipses" size={18} color={theme.bg} />
              )}
              <Text style={[styles.sendBtnTxt, (selected.size === 0 || sending) && { color: theme.textMute }]}>
                {selected.size === 0
                  ? "Sélectionne des contacts"
                  : selected.size === 1
                    ? "Envoyer le SMS"
                    : `Envoyer le SMS groupé (${selected.size})`}
              </Text>
            </TouchableOpacity>
            {classicLink}
          </View>
        </>
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
  headerBtn: { padding: 4, minWidth: 44, alignItems: "center" },
  headerTitle: { color: theme.text, fontSize: 17, fontWeight: "800", flex: 1, textAlign: "center" },
  centered: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.lg, gap: 12,
  },
  centerTxt: { color: theme.textDim, fontSize: 14, textAlign: "center" },
  introCard: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.lg, gap: 14,
  },
  introTitle: {
    color: theme.text, fontSize: 22, fontWeight: "900",
    textAlign: "center", marginTop: 4,
  },
  introBody: { color: theme.textDim, fontSize: 14, lineHeight: 20, textAlign: "center" },
  bonusBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(255,209,102,0.10)",
    borderColor: "rgba(255,209,102,0.4)", borderWidth: 1,
    paddingHorizontal: 12, paddingVertical: 9, borderRadius: radii.md,
  },
  bonusTxt: { color: "#FFD166", fontSize: 13, fontWeight: "800" },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.primary, paddingHorizontal: 22, paddingVertical: 13,
    borderRadius: radii.md, marginTop: 6, minWidth: 220, justifyContent: "center",
    minHeight: 48,
  },
  primaryBtnTxt: { color: theme.bg, fontSize: 15, fontWeight: "800" },
  classicLink: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, minHeight: 40,
  },
  classicLinkTxt: { color: theme.textDim, fontSize: 13, fontWeight: "600" },
  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: spacing.md, marginTop: spacing.sm,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 12, minHeight: 44,
  },
  searchInput: { flex: 1, color: theme.text, fontSize: 15, paddingVertical: 10 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingVertical: 10, paddingHorizontal: 6, borderRadius: radii.md,
    minHeight: 56,
  },
  rowSelected: { backgroundColor: "rgba(72,202,228,0.10)" },
  checkbox: {
    width: 22, height: 22, borderRadius: 11,
    borderWidth: 2, borderColor: theme.border,
    alignItems: "center", justifyContent: "center",
  },
  checkboxOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  avatar: { width: 42, height: 42, borderRadius: 21 },
  avatarFallback: {
    backgroundColor: theme.bg3, alignItems: "center", justifyContent: "center",
  },
  contactName: { color: theme.text, fontSize: 15, fontWeight: "700" },
  contactPhone: { color: theme.textMute, fontSize: 12, marginTop: 2 },
  separator: { height: 1, backgroundColor: theme.border, marginLeft: 56 },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    padding: spacing.md, gap: 2,
    borderTopWidth: 1, borderTopColor: theme.border,
    backgroundColor: theme.bg,
    paddingBottom: Platform.OS === "ios" ? 24 : spacing.md,
  },
  sendBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.primary,
    paddingHorizontal: 20, paddingVertical: 14,
    borderRadius: radii.md, minHeight: 52,
  },
  sendBtnDisabled: {
    backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
  },
  sendBtnTxt: { color: theme.bg, fontSize: 15, fontWeight: "800" },
});
