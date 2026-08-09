/**
 * Phase 4.2b — Invite marins from address book (multi-select redesign).
 *
 * NEW FLOW (replaces the code copy/paste era) :
 *   1. User grants Contacts permission (pre-permission intro card).
 *   2. App scans the address book locally, hashes phone numbers with
 *      SHA-256 over the E.164 form, and asks the backend which of them
 *      correspond to an existing SignalMar user.
 *   3. The matches are shown as CHECKABLE rows — multi-selection is the
 *      default, because you rarely invite a single friend to a group.
 *   4. « Envoyer X invitations » posts one `group_invitations` doc per
 *      selected user_id (server-side), then sequentially opens the SMS
 *      or WhatsApp composer for each contact with the message pre-filled.
 *      The DB source-of-truth is written *before* any messenger opens, so
 *      even if the admin cancels every SMS/WhatsApp draft, the invitees
 *      will still see the invitation at their next app launch. No code
 *      to copy/paste ever again.
 *
 * Contract with `handle_permissions_contract` respected end-to-end:
 *   idle → intro card, denied+canRetry → « Réessayer », denied+!canRetry
 *   → « Ouvrir les Réglages ». At every state a fallback "Partager le
 *   code d'invitation" button stays available so the flow never
 *   dead-ends.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
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
import * as Haptics from "expo-haptics";

import { api, type GroupMember, type GroupSummary } from "@/src/api/client";
import {
  loadLocalContacts,
  matchContactsAgainstServer,
  requestContactsPermission,
  type LocalPhoneInfo,
  type MergedContactMatch,
} from "@/src/lib/contact-sync";
import { normalizeName } from "@/src/components/ContactNameSearch";
import { ContactsRefreshButton } from "@/src/components/ContactsRefreshButton";
import {
  openInvitationChannels,
} from "@/src/lib/invite-message";
import { logger } from "@/src/lib/logger";
import { radii, spacing, theme } from "@/src/lib/theme";
import { useAuth } from "@/src/auth/AuthContext";

type PermState = "idle" | "granted" | "denied_retry" | "denied_settings";

export default function InviteContactsScreen() {
  const router = useRouter();
  const { groupId } = useLocalSearchParams<{ groupId?: string }>();
  const gid = String(groupId || "");
  const { user: me } = useAuth();

  const [group, setGroup] = useState<GroupSummary | null>(null);
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [perm, setPerm] = useState<PermState>("idle");
  const [scanning, setScanning] = useState(false);
  const [matches, setMatches] = useState<MergedContactMatch[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Recherche par NOM dans les résultats (11/07) — filtre nom du carnet + pseudo.
  const [query, setQuery] = useState("");

  const memberIds = useMemo(
    () => new Set(members.map((m) => m.user_id)),
    [members],
  );

  // Load group meta so we can display header + detect already-in-group.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!gid) return;
      try {
        const res = await api.groupDetail(gid);
        if (!cancelled) {
          setGroup(res.group);
          setMembers(res.members);
        }
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, [gid]);

  const runSync = useCallback(async (localOverride?: LocalPhoneInfo[]) => {
    setScanning(true);
    setErr(null);
    try {
      // Cache 30 j (contact-sync) — instantané après la 1ʳᵉ lecture.
      const local = localOverride ?? await loadLocalContacts();
      logger.event("app", "contacts_scanned", { count: local.length });
      const found = await matchContactsAgainstServer(local);
      // Filter out the caller themselves (edge case: user in own contacts).
      const filtered = me
        ? found.filter((m) => m.user_id !== me.user_id)
        : found;
      setMatches(filtered);
    } catch (e) {
      const msg = (e as Error).message || "Impossible de scanner les contacts";
      setErr(msg);
      logger.error("app", "contacts_sync_failed", { error: msg });
    } finally {
      setScanning(false);
    }
  }, [me]);

  const askPermission = useCallback(async () => {
    const { granted, canAskAgain } = await requestContactsPermission();
    if (granted) {
      setPerm("granted");
      await runSync();
    } else {
      setPerm(canAskAgain ? "denied_retry" : "denied_settings");
    }
  }, [runSync]);

  const openSettings = () => {
    Linking.openSettings().catch(() => {
      Alert.alert(
        "Ouverture impossible",
        "Ouvre les réglages de ton téléphone → SignalMar → Contacts.",
      );
    });
  };

  const toggle = (uid: string) => {
    Haptics.selectionAsync().catch(() => {});
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  };

  // Fallback path — the admin has no matches OR prefers the old code
  // share. We still expose the Share sheet so the flow never dead-ends.
  const shareInviteCodeFallback = async () => {
    if (!group) return;
    try {
      await Share.share({
        message:
          `🌊 Rejoins mon groupe SignalMar « ${group.name} » !\n` +
          `Code : ${group.invite_code}\n` +
          `App gratuite : https://signalmar.app`,
        title: `Rejoins ${group.name} sur SignalMar`,
      });
    } catch { /* user cancelled */ }
  };

  const doSendInvitations = async () => {
    if (!group || !me || selected.size === 0) return;
    // Copy the current selection into an array in the SAME order the
    // matches are displayed, so the SMS composers pop up in a predictable
    // "top-down" order.
    const chosen = matches.filter((m) => selected.has(m.user_id));
    if (chosen.length === 0) return;

    setSending(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    try {
      const res = await api.invitationsCreate(
        group.group_id,
        chosen.map((c) => c.user_id),
      );
      logger.event("app", "invitations_created", {
        group_id: group.group_id,
        count: res.created,
        already: res.already_member,
      });

      // Sequentially open a messenger for each invitee. The DB write
      // is already done, so if the user aborts we still keep the
      // invitations pending.
      let opened = 0;
      let closed = 0;
      for (const c of chosen) {
        const channel = await openInvitationChannels({
          contactDisplayName: c.local.displayName,
          contactPhoneE164: c.local.e164,
          groupName: group.name,
          inviterPseudo: me.pseudo || me.name || "Marin",
          inviterReferralCode: me.referral_code || null,
        });
        if (channel) opened += 1;
        else closed += 1;
      }

      // Final feedback : we ALWAYS confirm invites are queued in DB
      // even when no messenger was opened, because the invitee will
      // see them at their next app launch (source of truth is Mongo).
      const parts: string[] = [];
      parts.push(
        res.created === 1
          ? `1 invitation créée`
          : `${res.created} invitations créées`,
      );
      if (opened > 0) parts.push(`${opened} message${opened > 1 ? "s" : ""} pré-rempli${opened > 1 ? "s" : ""}`);
      if (closed > 0) parts.push(`${closed} sans messagerie compatible`);
      Alert.alert(
        "Invitations envoyées",
        parts.join(" • ") +
          "\n\nTes contacts verront l'invitation directement dans SignalMar dès leur prochain lancement.",
        [{ text: "OK", onPress: () => router.back() }],
      );
    } catch (e) {
      Alert.alert(
        "Erreur",
        (e as Error).message || "Impossible d'envoyer les invitations.",
      );
    } finally {
      setSending(false);
    }
  };

  // ── Renderers ──────────────────────────────────────────────────────
  const renderIntro = () => (
    <View style={styles.introCard}>
      <Ionicons name="people-circle" size={64} color={theme.primary} />
      <Text style={styles.introTitle}>Invite tes contacts</Text>
      <Text style={styles.introBody}>
        SignalMar peut détecter les marins de tes contacts déjà inscrits et
        leur envoyer une invitation directe — plus besoin de partager un
        code.
      </Text>
      <View style={styles.privacyBox}>
        <Ionicons name="shield-checkmark" size={16} color={theme.primary} />
        <Text style={styles.privacyTxt}>
          Aucun numéro ne quitte ton téléphone : seule une empreinte
          irréversible (SHA-256) est envoyée pour la comparaison.
        </Text>
      </View>
      <TouchableOpacity
        style={styles.primaryBtn}
        onPress={askPermission}
        testID="contacts-grant-permission"
      >
        <Ionicons name="lock-open" size={18} color={theme.bg} />
        <Text style={styles.primaryBtnTxt}>Autoriser les contacts</Text>
      </TouchableOpacity>
      <TouchableOpacity
        style={styles.linkBtn}
        onPress={shareInviteCodeFallback}
        disabled={!group}
      >
        <Text style={styles.linkTxt}>Utiliser le code d&apos;invitation</Text>
      </TouchableOpacity>
    </View>
  );

  const renderDenied = (canRetry: boolean) => (
    <View style={styles.introCard}>
      <Ionicons name="lock-closed" size={54} color={theme.warning} />
      <Text style={styles.introTitle}>Accès aux contacts refusé</Text>
      <Text style={styles.introBody}>
        {canRetry
          ? "Tu peux réessayer ou continuer via le code d'invitation."
          : "Ouvre les réglages de ton téléphone et autorise l'accès aux contacts pour SignalMar."}
      </Text>
      <TouchableOpacity
        style={styles.primaryBtn}
        onPress={canRetry ? askPermission : openSettings}
      >
        <Ionicons
          name={canRetry ? "refresh" : "settings-outline"}
          size={18} color={theme.bg}
        />
        <Text style={styles.primaryBtnTxt}>
          {canRetry ? "Réessayer" : "Ouvrir les Réglages"}
        </Text>
      </TouchableOpacity>
      <TouchableOpacity style={styles.linkBtn} onPress={shareInviteCodeFallback} disabled={!group}>
        <Text style={styles.linkTxt}>Utiliser le code d&apos;invitation</Text>
      </TouchableOpacity>
    </View>
  );

  const renderMatchRow = ({ item }: { item: MergedContactMatch }) => {
    const isMember = memberIds.has(item.user_id);
    const isSelected = selected.has(item.user_id);
    const disabled = isMember;
    return (
      <TouchableOpacity
        style={[
          styles.matchRow,
          isSelected && styles.matchRowSelected,
          disabled && styles.matchRowDisabled,
        ]}
        onPress={() => !disabled && toggle(item.user_id)}
        activeOpacity={0.85}
        disabled={disabled}
        testID={`contacts-row-${item.user_id}`}
      >
        {/* Checkbox */}
        <View
          style={[
            styles.checkbox,
            isSelected && styles.checkboxOn,
            disabled && { opacity: 0.3 },
          ]}
        >
          {isSelected ? (
            <Ionicons name="checkmark" size={16} color={theme.bg} />
          ) : null}
        </View>
        {item.picture ? (
          <Image source={{ uri: item.picture }} style={styles.avatar} />
        ) : (
          <View style={[styles.avatar, styles.avatarFallback]}>
            <Text style={{ color: theme.primary, fontWeight: "800" }}>
              {item.pseudo.slice(0, 1).toUpperCase()}
            </Text>
          </View>
        )}
        <View style={{ flex: 1 }}>
          <Text style={styles.contactName} numberOfLines={1}>
            {item.local.displayName}
          </Text>
          <Text style={styles.pseudoLine} numberOfLines={1}>
            <Ionicons name="boat" size={11} color={theme.primary} />{" "}
            {item.pseudo}
            {item.rank_label ? ` · ${item.rank_label}` : ""}
          </Text>
        </View>
        {isMember ? (
          <View style={styles.memberChip}>
            <Ionicons name="checkmark-circle" size={14} color={theme.primary} />
            <Text style={styles.memberChipTxt}>Déjà dedans</Text>
          </View>
        ) : null}
      </TouchableOpacity>
    );
  };

  const invitableCount = matches.filter((m) => !memberIds.has(m.user_id)).length;

  // Filtre par NOM (insensible casse/accents) : nom du carnet OU pseudo marin.
  const filteredMatches = useMemo(() => {
    const q = normalizeName(query.trim());
    if (!q) return matches;
    return matches.filter(
      (m) =>
        normalizeName(m.local.displayName).includes(q) ||
        normalizeName(m.pseudo || "").includes(q),
    );
  }, [matches, query]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.headerBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.headerTitle} numberOfLines={1}>Inviter des marins</Text>
          {group ? (
            <Text style={styles.headerSub} numberOfLines={1}>{group.name}</Text>
          ) : null}
        </View>
        {perm === "granted" && matches.length > 0 && invitableCount > 0 ? (
          <TouchableOpacity
            onPress={() => {
              const next = new Set<string>();
              if (selected.size < invitableCount) {
                matches.forEach((m) => { if (!memberIds.has(m.user_id)) next.add(m.user_id); });
              }
              setSelected(next);
            }}
            style={styles.headerBtn}
            hitSlop={12}
          >
            <Text style={styles.allTxt}>
              {selected.size < invitableCount ? "Tout" : "Aucun"}
            </Text>
          </TouchableOpacity>
        ) : (
          <View style={{ width: 44 }} />
        )}
      </View>

      {/* Body */}
      {perm === "idle" ? (
        renderIntro()
      ) : perm === "denied_retry" ? (
        renderDenied(true)
      ) : perm === "denied_settings" ? (
        renderDenied(false)
      ) : scanning ? (
        <View style={styles.centered}>
          <ActivityIndicator color={theme.primary} size="large" />
          <Text style={styles.centerTxt}>Recherche de tes amis marins…</Text>
        </View>
      ) : err ? (
        <View style={styles.centered}>
          <Ionicons name="cloud-offline-outline" size={40} color={theme.textMute} />
          <Text style={styles.errText}>{err}</Text>
          <TouchableOpacity style={styles.retryBtn} onPress={() => runSync()}>
            <Text style={styles.retryTxt}>Réessayer</Text>
          </TouchableOpacity>
        </View>
      ) : matches.length === 0 ? (
        <View style={styles.centered}>
          <Ionicons name="sad-outline" size={48} color={theme.textMute} />
          <Text style={styles.introTitle}>Aucun ami sur SignalMar</Text>
          <Text style={styles.introBody}>
            Aucun de tes contacts n&apos;est encore inscrit. Partage le code
            pour les faire monter à bord.
          </Text>
          <TouchableOpacity
            style={styles.primaryBtn}
            onPress={shareInviteCodeFallback}
            disabled={!group}
          >
            <Ionicons name="share-social" size={18} color={theme.bg} />
            <Text style={styles.primaryBtnTxt}>Partager le code</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <>
          <FlatList
            data={filteredMatches}
            keyExtractor={(m) => m.user_id}
            renderItem={renderMatchRow}
            ItemSeparatorComponent={() => <View style={styles.separator} />}
            contentContainerStyle={{ padding: spacing.md, paddingBottom: 140 }}
            keyboardShouldPersistTaps="handled"
            ListHeaderComponent={
              <View style={styles.listHeader}>
                <Text style={styles.sectionTitle}>
                  {matches.length} contact{matches.length > 1 ? "s" : ""} sur SignalMar
                </Text>
                <Text style={styles.sectionSub}>
                  Sélectionne ceux à inviter — ils recevront un SMS/WhatsApp
                  et verront l&apos;invitation dans l&apos;app.
                </Text>
                {/* Recherche par NOM + relecture du carnet (cache 30 j). */}
                <View style={styles.searchRow}>
                  <View style={styles.searchWrap}>
                    <Ionicons name="search" size={15} color={theme.textDim} />
                    <TextInput
                      style={styles.searchInput}
                      value={query}
                      onChangeText={setQuery}
                      placeholder="Rechercher un nom…"
                      placeholderTextColor={theme.textMute}
                      autoCorrect={false}
                      testID="group-invite-search"
                    />
                    {query.length > 0 && (
                      <TouchableOpacity onPress={() => setQuery("")} hitSlop={8}>
                        <Ionicons name="close-circle" size={16} color={theme.textDim} />
                      </TouchableOpacity>
                    )}
                  </View>
                  <ContactsRefreshButton
                    compact
                    onRefreshed={(all) => runSync(all)}
                    testID="group-invite-contacts-refresh"
                  />
                </View>
              </View>
            }
            ListEmptyComponent={
              query ? (
                <View style={{ alignItems: "center", paddingTop: 30, gap: 8 }}>
                  <Ionicons name="sad-outline" size={36} color={theme.textMute} />
                  <Text style={styles.centerTxt}>Aucun contact ne correspond.</Text>
                </View>
              ) : null
            }
          />

          {/* Sticky footer with the CTA */}
          <View style={styles.footer} pointerEvents="box-none">
            <TouchableOpacity
              style={[
                styles.sendBtn,
                (selected.size === 0 || sending) && styles.sendBtnDisabled,
              ]}
              onPress={doSendInvitations}
              disabled={selected.size === 0 || sending}
              activeOpacity={0.85}
              testID="contacts-send-batch"
            >
              {sending ? (
                <ActivityIndicator color={theme.bg} />
              ) : (
                <Ionicons name="paper-plane" size={18} color={theme.bg} />
              )}
              <Text style={styles.sendBtnTxt}>
                {sending
                  ? "Envoi…"
                  : selected.size === 0
                    ? "Sélectionne des contacts"
                    : selected.size === 1
                      ? "Envoyer 1 invitation"
                      : `Envoyer ${selected.size} invitations`}
              </Text>
            </TouchableOpacity>
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
  allTxt: { color: theme.primary, fontWeight: "800", fontSize: 13 },
  headerTitle: { color: theme.text, fontSize: 17, fontWeight: "800" },
  headerSub: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  centered: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.lg, gap: 12,
  },
  centerTxt: { color: theme.textDim, fontSize: 14 },
  introCard: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.lg, gap: 14,
  },
  introTitle: {
    color: theme.text, fontSize: 22, fontWeight: "900",
    textAlign: "center", marginTop: 4,
  },
  introBody: {
    color: theme.textDim, fontSize: 14, lineHeight: 20, textAlign: "center",
  },
  privacyBox: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    backgroundColor: "rgba(46,196,182,0.08)",
    borderColor: "rgba(46,196,182,0.35)", borderWidth: 1,
    padding: 12, borderRadius: radii.md,
  },
  privacyTxt: { color: theme.text, fontSize: 12, flex: 1, lineHeight: 17 },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.primary, paddingHorizontal: 22, paddingVertical: 12,
    borderRadius: radii.md, marginTop: 6, minWidth: 200, justifyContent: "center",
  },
  primaryBtnTxt: { color: theme.bg, fontSize: 15, fontWeight: "800" },
  linkBtn: { paddingVertical: 8 },
  linkTxt: { color: theme.textDim, fontSize: 13, fontWeight: "600" },
  errText: { color: theme.textDim, fontSize: 14, textAlign: "center" },
  retryBtn: {
    paddingHorizontal: 20, paddingVertical: 8,
    borderRadius: radii.md, backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
  },
  retryTxt: { color: theme.text, fontWeight: "700" },
  listHeader: { paddingBottom: 12 },
  searchRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 },
  searchWrap: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 12, minHeight: 42,
  },
  searchInput: { flex: 1, color: theme.text, fontSize: 14, paddingVertical: 9 },
  sectionTitle: {
    color: theme.textDim, fontSize: 12, fontWeight: "800",
    letterSpacing: 0.6, textTransform: "uppercase",
  },
  sectionSub: { color: theme.textMute, fontSize: 12, marginTop: 4 },
  matchRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingVertical: 10, paddingHorizontal: 6,
    borderRadius: radii.md,
  },
  matchRowSelected: { backgroundColor: "rgba(72,202,228,0.10)" },
  matchRowDisabled: { opacity: 0.55 },
  checkbox: {
    width: 22, height: 22, borderRadius: 11,
    borderWidth: 2, borderColor: theme.border,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "transparent",
  },
  checkboxOn: {
    backgroundColor: theme.primary, borderColor: theme.primary,
  },
  avatar: { width: 44, height: 44, borderRadius: 22 },
  avatarFallback: {
    backgroundColor: theme.bg3, alignItems: "center", justifyContent: "center",
  },
  contactName: { color: theme.text, fontSize: 15, fontWeight: "700" },
  pseudoLine: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  memberChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(46,196,182,0.12)",
    borderColor: "rgba(46,196,182,0.4)", borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: radii.sm,
  },
  memberChipTxt: { color: theme.primary, fontSize: 11, fontWeight: "800" },
  separator: { height: 1, backgroundColor: theme.border, marginLeft: 56 },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    padding: spacing.md,
    borderTopWidth: 1, borderTopColor: theme.border,
    backgroundColor: theme.bg,
    paddingBottom: Platform.OS === "ios" ? 28 : spacing.md,
  },
  sendBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.primary,
    paddingHorizontal: 20, paddingVertical: 14,
    borderRadius: radii.md,
  },
  sendBtnDisabled: {
    backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
  },
  sendBtnTxt: {
    color: theme.bg, fontSize: 15, fontWeight: "800",
    ...(Platform.OS === "android" ? { includeFontPadding: false } : {}),
  },
});
