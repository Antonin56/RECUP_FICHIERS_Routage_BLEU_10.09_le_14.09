/**
 * Phase 4.1 — Groups list screen.
 *
 * Displays every group the current user has joined, newest first.
 * Actions:
 *   - Tap a group → detail
 *   - FAB "+" → create screen
 *   - Header link → join via code screen
 * Empty state guides the user to either create or join a group.
 */
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, type GroupSummary, type PendingInvitation } from "@/src/api/client";
import { logger } from "@/src/lib/logger";
import { theme, spacing, radii } from "@/src/lib/theme";

export default function GroupsListScreen() {
  const router = useRouter();
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [invites, setInvites] = useState<PendingInvitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyInvite, setBusyInvite] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setErr(null);
      // Fetch groups + pending invitations in parallel — invitations
      // come first visually so the user sees them the moment they open
      // the tab (Phase 4.2b requirement: no code copy/paste).
      const [{ groups: list }, { invitations }] = await Promise.all([
        api.groupsList(),
        api.invitationsMine().catch(() => ({ invitations: [] as PendingInvitation[] })),
      ]);
      setGroups(list);
      setInvites(invitations);
    } catch (e) {
      setErr((e as Error).message || "Impossible de charger les groupes");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  /**
   * Accept a pending invitation and refresh the list. On success we
   * jump directly to the freshly-joined group so the user lands
   * exactly where they wanted to go — the whole redesign is about
   * eliminating friction here.
   */
  const acceptInvite = async (inv: PendingInvitation) => {
    if (busyInvite) return;
    setBusyInvite(inv.invite_id);
    try {
      const g = await api.invitationAccept(inv.invite_id);
      logger.event("app", "invitation_accepted", { group_id: g.group_id });
      // Trim locally for instant feedback.
      setInvites((prev) => prev.filter((i) => i.invite_id !== inv.invite_id));
      router.push(`/groups/${g.group_id}`);
    } catch (e) {
      Alert.alert(
        "Impossible de rejoindre",
        (e as Error).message || "Le groupe est peut-être plein ou l'invitation a expiré.",
      );
      await load();
    } finally {
      setBusyInvite(null);
    }
  };

  const declineInvite = async (inv: PendingInvitation) => {
    if (busyInvite) return;
    Alert.alert(
      "Décliner l'invitation ?",
      `Tu ne recevras plus d'invitation pour « ${inv.group_name} ».`,
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Décliner", style: "destructive",
          onPress: async () => {
            setBusyInvite(inv.invite_id);
            try {
              await api.invitationDecline(inv.invite_id);
              setInvites((prev) => prev.filter((i) => i.invite_id !== inv.invite_id));
            } catch (e) {
              Alert.alert("Erreur", (e as Error).message || "Réessaye plus tard.");
            } finally {
              setBusyInvite(null);
            }
          },
        },
      ],
    );
  };

  const renderInviteCard = (inv: PendingInvitation) => {
    const busy = busyInvite === inv.invite_id;
    return (
      <View
        key={inv.invite_id}
        style={styles.inviteCard}
        testID={`invite-card-${inv.invite_id}`}
      >
        <View style={styles.inviteHeader}>
          <View style={styles.inviteLabel}>
            <Ionicons name="mail-unread" size={12} color={theme.primary} />
            <Text style={styles.inviteLabelTxt}>Invitation en attente</Text>
          </View>
        </View>
        <View style={styles.inviteBody}>
          {inv.group_avatar_url ? (
            <Image source={{ uri: inv.group_avatar_url }} style={styles.avatar} />
          ) : (
            <View style={[styles.avatar, styles.avatarFallback]}>
              <Ionicons name="people" size={22} color={theme.primary} />
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Text style={styles.inviteGroupName} numberOfLines={1}>{inv.group_name}</Text>
            {inv.group_description ? (
              <Text style={styles.inviteGroupDesc} numberOfLines={2}>{inv.group_description}</Text>
            ) : null}
            <View style={styles.inviteFrom}>
              {inv.inviter_picture ? (
                <Image source={{ uri: inv.inviter_picture }} style={styles.inviterAvatar} />
              ) : (
                <View style={[styles.inviterAvatar, styles.inviterAvatarFallback]} />
              )}
              <Text style={styles.inviteFromTxt} numberOfLines={1}>
                Par <Text style={{ color: theme.text, fontWeight: "800" }}>{inv.inviter_pseudo}</Text>
                {"  ·  "}
                {inv.group_member_count}/{inv.group_max_members} marins
              </Text>
            </View>
          </View>
        </View>
        <View style={styles.inviteActions}>
          <TouchableOpacity
            style={[styles.declineBtn, busy && { opacity: 0.5 }]}
            onPress={() => declineInvite(inv)}
            disabled={busy}
            testID={`invite-decline-${inv.invite_id}`}
          >
            <Text style={styles.declineTxt}>Décliner</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.joinBtn, busy && { opacity: 0.5 }]}
            onPress={() => acceptInvite(inv)}
            disabled={busy}
            testID={`invite-accept-${inv.invite_id}`}
          >
            {busy ? (
              <ActivityIndicator color={theme.bg} />
            ) : (
              <>
                <Ionicons name="checkmark-circle" size={16} color={theme.bg} />
                <Text style={styles.joinTxt}>Rejoindre</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.headerBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Groupes privés</Text>
        <TouchableOpacity
          onPress={() => router.push("/groups/join")}
          style={styles.headerBtn}
          hitSlop={12}
          testID="groups-open-join"
        >
          <Ionicons name="enter-outline" size={24} color={theme.primary} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.centered}><ActivityIndicator color={theme.primary} /></View>
      ) : err ? (
        <View style={styles.centered}>
          <Ionicons name="cloud-offline-outline" size={40} color={theme.textMute} />
          <Text style={styles.errText}>{err}</Text>
          <TouchableOpacity style={styles.retryBtn} onPress={load}>
            <Text style={styles.retryTxt}>Réessayer</Text>
          </TouchableOpacity>
        </View>
      ) : groups.length === 0 && invites.length === 0 ? (
        <View style={styles.centered}>
          <Ionicons name="people-outline" size={54} color={theme.textMute} />
          <Text style={styles.emptyTitle}>Aucun groupe pour l&apos;instant</Text>
          <Text style={styles.emptyBody}>
            Crée un groupe privé pour naviguer et discuter à plusieurs, ou rejoins-en un via un lien d&apos;invitation.
          </Text>
          <TouchableOpacity
            style={styles.primaryBtn}
            onPress={() => router.push("/groups/new")}
            testID="groups-empty-create"
          >
            <Ionicons name="add-circle" size={22} color={theme.bg} />
            <Text style={styles.primaryBtnTxt}>Créer un groupe</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.secondaryBtn}
            onPress={() => router.push("/groups/join")}
          >
            <Ionicons name="enter-outline" size={20} color={theme.primary} />
            <Text style={styles.secondaryBtnTxt}>Rejoindre avec un code</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={groups}
          keyExtractor={(g) => g.group_id}
          contentContainerStyle={{ padding: spacing.md, paddingBottom: 120 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.primary} />
          }
          ListHeaderComponent={
            invites.length > 0 ? (
              <View style={{ marginBottom: spacing.md }}>
                <Text style={styles.pendingSectionTitle}>
                  {invites.length === 1
                    ? "1 invitation reçue"
                    : `${invites.length} invitations reçues`}
                </Text>
                {invites.map(renderInviteCard)}
                {groups.length > 0 && (
                  <Text style={[styles.pendingSectionTitle, { marginTop: 6 }]}>
                    Mes groupes
                  </Text>
                )}
              </View>
            ) : null
          }
          ListEmptyComponent={
            invites.length > 0 ? (
              <View style={{ marginTop: 8, alignItems: "center" }}>
                <Text style={styles.emptyBody}>
                  Rejoins une invitation ci-dessus, ou crée ton propre groupe.
                </Text>
              </View>
            ) : null
          }
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.card}
              onPress={() => router.push(`/groups/${item.group_id}`)}
              testID={`group-card-${item.group_id}`}
              activeOpacity={0.85}
            >
              {item.avatar_url ? (
                <Image source={{ uri: item.avatar_url }} style={styles.avatar} />
              ) : (
                <View style={[styles.avatar, styles.avatarFallback]}>
                  <Ionicons name="people" size={22} color={theme.primary} />
                </View>
              )}
              <View style={{ flex: 1 }}>
                <View style={styles.rowBetween}>
                  <Text style={styles.cardName} numberOfLines={1}>{item.name}</Text>
                  {item.my_role === "owner" && (
                    <View style={styles.ownerBadge}>
                      <Text style={styles.ownerBadgeTxt}>Propriétaire</Text>
                    </View>
                  )}
                </View>
                {!!item.description && (
                  <Text style={styles.cardDesc} numberOfLines={1}>{item.description}</Text>
                )}
                <View style={styles.metaRow}>
                  <Ionicons name="person" size={12} color={theme.textDim} />
                  <Text style={styles.metaTxt}>{item.member_count} / {item.max_members}</Text>
                </View>
              </View>
              <Ionicons name="chevron-forward" size={22} color={theme.textMute} />
            </TouchableOpacity>
          )}
        />
      )}

      {!loading && groups.length > 0 && (
        <TouchableOpacity
          style={styles.fab}
          onPress={() => router.push("/groups/new")}
          testID="groups-fab-create"
          accessibilityLabel="Créer un groupe"
        >
          <Ionicons name="add" size={30} color={theme.bg} />
        </TouchableOpacity>
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
  headerBtn: { padding: 4, minWidth: 36, alignItems: "center" },
  headerTitle: { color: theme.text, fontSize: 18, fontWeight: "800" },
  centered: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.lg, gap: 12,
  },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: "800", marginTop: 8 },
  emptyBody: { color: theme.textDim, fontSize: 14, textAlign: "center", lineHeight: 20 },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.primary, paddingHorizontal: 22, paddingVertical: 12,
    borderRadius: radii.md, marginTop: 12,
  },
  primaryBtnTxt: { color: theme.bg, fontSize: 15, fontWeight: "800" },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 18, paddingVertical: 10, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.primary,
  },
  secondaryBtnTxt: { color: theme.primary, fontSize: 14, fontWeight: "700" },
  errText: { color: theme.textDim, fontSize: 14, textAlign: "center" },
  retryBtn: {
    marginTop: 4, paddingHorizontal: 20, paddingVertical: 8,
    borderRadius: radii.md, backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
  },
  retryTxt: { color: theme.text, fontWeight: "700" },

  // Phase 4.2b — Pending invitation cards, distinct cyan-tinted style so
  // they can't be missed when the user lands on the tab.
  pendingSectionTitle: {
    color: theme.textDim, fontSize: 11, fontWeight: "800",
    letterSpacing: 0.6, textTransform: "uppercase",
    marginBottom: 8,
  },
  inviteCard: {
    borderRadius: radii.md,
    backgroundColor: "rgba(72,202,228,0.06)",
    borderWidth: 1, borderColor: theme.primary,
    padding: 12, marginBottom: 10,
  },
  inviteHeader: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between", marginBottom: 8,
  },
  inviteLabel: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(72,202,228,0.12)",
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: radii.sm,
  },
  inviteLabelTxt: {
    color: theme.primary, fontSize: 10, fontWeight: "800",
    letterSpacing: 0.5, textTransform: "uppercase",
  },
  inviteBody: { flexDirection: "row", alignItems: "center", gap: 12 },
  inviteGroupName: { color: theme.text, fontSize: 16, fontWeight: "800" },
  inviteGroupDesc: { color: theme.textDim, fontSize: 12, marginTop: 2, lineHeight: 16 },
  inviteFrom: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  inviterAvatar: { width: 16, height: 16, borderRadius: 8 },
  inviterAvatarFallback: { backgroundColor: theme.bg3 },
  inviteFromTxt: { color: theme.textDim, fontSize: 11, flex: 1 },
  inviteActions: {
    flexDirection: "row", gap: 8, marginTop: 12,
  },
  declineBtn: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingVertical: 10, borderRadius: radii.sm,
    borderWidth: 1, borderColor: theme.border,
  },
  declineTxt: { color: theme.textDim, fontSize: 13, fontWeight: "700" },
  joinBtn: {
    flex: 2, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: radii.sm,
    backgroundColor: theme.primary,
  },
  joinTxt: { color: theme.bg, fontSize: 13, fontWeight: "800" },

  card: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    padding: 12, marginBottom: 8,
  },
  avatar: { width: 48, height: 48, borderRadius: 24 },
  avatarFallback: {
    backgroundColor: theme.bg3, alignItems: "center", justifyContent: "center",
  },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  cardName: { color: theme.text, fontSize: 16, fontWeight: "800", flex: 1 },
  cardDesc: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  metaTxt: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  ownerBadge: {
    backgroundColor: "rgba(233,196,106,0.16)",
    borderColor: "#E9C46A", borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: radii.sm,
  },
  ownerBadgeTxt: { color: "#E9C46A", fontSize: 10, fontWeight: "800" },
  fab: {
    position: "absolute", right: 20, bottom: 30,
    width: 60, height: 60, borderRadius: 30,
    backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
    shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 8, shadowOffset: { width: 0, height: 3 },
    elevation: 6,
  },
});
