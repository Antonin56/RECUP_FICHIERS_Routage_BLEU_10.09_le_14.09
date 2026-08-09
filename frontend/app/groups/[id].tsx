/**
 * Phase 4.1 — Group detail screen.
 *
 * Shows the group header, member list, and management actions:
 *   - Owner: share invite / regenerate code / kick member / delete
 *   - Member: leave
 * Later phases (chat, tracking) will hook in more sections here.
 */
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { Stack, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, GroupMember, GroupSummary } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";

export default function GroupDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const groupId = String(id || "");
  const [group, setGroup] = useState<GroupSummary | null>(null);
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!groupId) return;
    try {
      setErr(null);
      const res = await api.groupDetail(groupId);
      setGroup(res.group);
      setMembers(res.members);
    } catch (e) {
      setErr((e as Error).message || "Impossible de charger le groupe");
    } finally {
      setLoading(false);
    }
  }, [groupId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const isOwner = group?.my_role === "owner";

  // « Partager l'invitation » → flux contacts + SMS groupé (recherche par
  // NOM), exactement comme le parrainage — mode groupe de /share-invite
  // (11/07). Le partage classique reste accessible via « Partager
  // autrement… » sur cet écran.
  const shareInvite = () => {
    if (!group) return;
    router.push({
      pathname: "/share-invite",
      params: { group_name: group.name, group_code: group.invite_code },
    });
  };

  const copyCode = async () => {
    if (!group) return;
    try {
      await Clipboard.setStringAsync(group.invite_code);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch { /* clipboard denied */ }
  };

  const regenerateCode = () => {
    if (!group) return;
    Alert.alert(
      "Générer un nouveau code ?",
      "L'ancien code cessera de fonctionner. Les membres actuels ne seront pas affectés.",
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Générer",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              const g = await api.groupRegenerateInvite(group.group_id);
              setGroup(g);
            } catch (e) {
              Alert.alert("Erreur", (e as Error).message);
            } finally { setBusy(false); }
          },
        },
      ],
    );
  };

  const kickMember = (member: GroupMember) => {
    if (!group) return;
    Alert.alert(
      `Retirer ${member.pseudo} ?`,
      "Ce marin sera exclu du groupe. Tu pourras le réinviter plus tard.",
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Retirer",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await api.groupKick(group.group_id, member.user_id);
              await load();
            } catch (e) {
              Alert.alert("Erreur", (e as Error).message);
            } finally { setBusy(false); }
          },
        },
      ],
    );
  };

  const leaveGroup = () => {
    if (!group) return;
    Alert.alert(
      "Quitter le groupe ?",
      "Tu ne verras plus les échanges de ce groupe. Il faudra un nouveau code pour revenir.",
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Quitter",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await api.groupLeave(group.group_id);
              router.replace("/groups");
            } catch (e) {
              Alert.alert("Erreur", (e as Error).message);
              setBusy(false);
            }
          },
        },
      ],
    );
  };

  const deleteGroup = () => {
    if (!group) return;
    Alert.alert(
      `Supprimer « ${group.name} » ?`,
      "Cette action est irréversible. Tous les membres perdront l'accès aux échanges et à l'historique.",
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Supprimer",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await api.groupDelete(group.group_id);
              router.replace("/groups");
            } catch (e) {
              Alert.alert("Erreur", (e as Error).message);
              setBusy(false);
            }
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.headerBtn} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle} numberOfLines={1}>{group?.name || "Groupe"}</Text>
        <View style={{ width: 36 }} />
      </View>

      {loading ? (
        <View style={styles.centered}><ActivityIndicator color={theme.primary} /></View>
      ) : err ? (
        <View style={styles.centered}>
          <Text style={styles.errText}>{err}</Text>
          <TouchableOpacity style={styles.retryBtn} onPress={load}>
            <Text style={styles.retryTxt}>Réessayer</Text>
          </TouchableOpacity>
        </View>
      ) : group ? (
        <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
          <View style={styles.heroCard}>
            {group.avatar_url ? (
              <Image source={{ uri: group.avatar_url }} style={styles.heroAvatar} />
            ) : (
              <View style={[styles.heroAvatar, styles.heroAvatarFallback]}>
                <Ionicons name="people" size={40} color={theme.primary} />
              </View>
            )}
            <Text style={styles.heroName}>{group.name}</Text>
            {!!group.description && <Text style={styles.heroDesc}>{group.description}</Text>}
            <View style={styles.heroMeta}>
              <Ionicons name="people" size={14} color={theme.textDim} />
              <Text style={styles.heroMetaTxt}>
                {group.member_count} / {group.max_members} membres
              </Text>
            </View>
          </View>

          {/* Invite card */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Inviter des marins</Text>
            <View style={styles.inviteCard}>
              <Text style={styles.inviteLabel}>Code d&apos;invitation</Text>
              <TouchableOpacity onPress={copyCode} style={styles.inviteCodeRow} testID="group-copy-code">
                <Text style={styles.inviteCode}>{group.invite_code}</Text>
                <Ionicons name="copy-outline" size={20} color={theme.primary} />
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.primaryBtn}
                onPress={shareInvite}
                testID="group-share-invite"
              >
                <Ionicons name="share-social" size={20} color={theme.bg} />
                <Text style={styles.primaryBtnTxt}>Partager l&apos;invitation</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.secondaryBtn}
                onPress={() =>
                  router.push({
                    pathname: "/groups/invite",
                    params: { groupId: group.group_id },
                  })
                }
                testID="group-open-invite-contacts"
              >
                <Ionicons name="people" size={16} color={theme.primary} />
                <Text style={styles.secondaryBtnTxt}>
                  Retrouver mes contacts
                </Text>
              </TouchableOpacity>
              {isOwner && (
                <TouchableOpacity
                  style={styles.secondaryBtn}
                  onPress={regenerateCode}
                  disabled={busy}
                  testID="group-regen-code"
                >
                  <Ionicons name="refresh" size={16} color={theme.primary} />
                  <Text style={styles.secondaryBtnTxt}>Générer un nouveau code</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>

          {/* Members */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Membres · {members.length}</Text>
            {members.map((m) => (
              <View key={m.user_id} style={styles.memberRow}>
                {m.picture ? (
                  <Image source={{ uri: m.picture }} style={styles.memberAvatar} />
                ) : (
                  <View style={[styles.memberAvatar, styles.memberAvatarFallback]}>
                    <Text style={{ color: theme.primary, fontWeight: "800" }}>
                      {(m.pseudo || "?").slice(0, 1).toUpperCase()}
                    </Text>
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.memberName}>{m.pseudo}</Text>
                    {m.role === "owner" && (
                      <View style={styles.ownerBadge}>
                        <Text style={styles.ownerBadgeTxt}>Propriétaire</Text>
                      </View>
                    )}
                  </View>
                  {!!m.rank_label && <Text style={styles.memberSub}>{m.rank_label}</Text>}
                </View>
                {isOwner && m.role !== "owner" && (
                  <TouchableOpacity
                    onPress={() => kickMember(m)}
                    hitSlop={12}
                    style={styles.kickBtn}
                    testID={`group-kick-${m.user_id}`}
                  >
                    <Ionicons name="person-remove-outline" size={18} color={theme.danger} />
                  </TouchableOpacity>
                )}
              </View>
            ))}
          </View>

          {/* Danger zone */}
          <View style={styles.section}>
            {isOwner ? (
              <TouchableOpacity
                style={styles.dangerBtn}
                onPress={deleteGroup}
                disabled={busy}
                testID="group-delete"
              >
                <Ionicons name="trash-outline" size={18} color={theme.danger} />
                <Text style={styles.dangerBtnTxt}>Supprimer le groupe</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={styles.dangerBtn}
                onPress={leaveGroup}
                disabled={busy}
                testID="group-leave"
              >
                <Ionicons name="exit-outline" size={18} color={theme.danger} />
                <Text style={styles.dangerBtnTxt}>Quitter le groupe</Text>
              </TouchableOpacity>
            )}
          </View>
        </ScrollView>
      ) : null}
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
  headerTitle: { color: theme.text, fontSize: 18, fontWeight: "800", flex: 1, textAlign: "center" },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg, gap: 12 },
  heroCard: {
    alignItems: "center", padding: spacing.lg, gap: 10,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  heroAvatar: { width: 84, height: 84, borderRadius: 42 },
  heroAvatarFallback: { backgroundColor: theme.bg2, alignItems: "center", justifyContent: "center" },
  heroName: { color: theme.text, fontSize: 22, fontWeight: "900", textAlign: "center" },
  heroDesc: { color: theme.textDim, fontSize: 13, textAlign: "center", lineHeight: 18 },
  heroMeta: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  heroMetaTxt: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  section: { padding: spacing.md },
  sectionTitle: {
    color: theme.textDim, fontSize: 12, fontWeight: "800",
    letterSpacing: 0.6, textTransform: "uppercase", marginBottom: 8,
  },
  inviteCard: {
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, padding: spacing.md, gap: 10,
  },
  inviteLabel: { color: theme.textDim, fontSize: 12, fontWeight: "800" },
  inviteCodeRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: theme.bg, borderRadius: radii.sm,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 14, paddingVertical: 12,
  },
  inviteCode: {
    color: theme.text, fontSize: 22, fontWeight: "900", letterSpacing: 4,
  },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.primary, paddingVertical: 12, borderRadius: radii.md,
  },
  primaryBtnTxt: { color: theme.bg, fontSize: 15, fontWeight: "800" },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.primary,
  },
  secondaryBtnTxt: { color: theme.primary, fontSize: 13, fontWeight: "700" },
  memberRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    padding: 10, marginBottom: 6,
  },
  memberAvatar: { width: 40, height: 40, borderRadius: 20 },
  memberAvatarFallback: {
    backgroundColor: theme.bg3, alignItems: "center", justifyContent: "center",
  },
  memberName: { color: theme.text, fontSize: 15, fontWeight: "800" },
  memberSub: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  ownerBadge: {
    backgroundColor: "rgba(233,196,106,0.16)", borderColor: "#E9C46A",
    borderWidth: 1, paddingHorizontal: 6, paddingVertical: 1, borderRadius: radii.sm,
  },
  ownerBadgeTxt: { color: "#E9C46A", fontSize: 10, fontWeight: "800" },
  kickBtn: { padding: 6 },
  dangerBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderWidth: 1, borderColor: theme.danger, borderRadius: radii.md,
    paddingVertical: 12,
  },
  dangerBtnTxt: { color: theme.danger, fontSize: 14, fontWeight: "800" },
  errText: { color: theme.textDim, fontSize: 14, textAlign: "center" },
  retryBtn: {
    paddingHorizontal: 20, paddingVertical: 8,
    borderRadius: radii.md, backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
  },
  retryTxt: { color: theme.text, fontWeight: "700" },
});
