import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, FlatList, Modal, Pressable, ScrollView, StyleSheet,
  Text, TextInput, TouchableOpacity, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";
import { ContactNameSearch, type PickedContact } from "@/src/components/ContactNameSearch";

type FriendRow = {
  user_id: string; pseudo: string; picture: string; rank_label: string;
  points: number; reliability_score: number;
  referral_bonus_paid?: boolean; created_at?: string | null; last_open_day?: string | null;
};
type PendingRow = {
  id: string; from_user_id: string; to_user_id: string; created_at: string;
  user: FriendRow;
};

/**
 * Phase 3b — Friends screen with two tabs (Amis / Demandes) and an in-app
 * search modal to add friends by email / phone / referral code.
 */
export default function FriendsScreen() {
  const router = useRouter();
  const [tab, setTab] = useState<"friends" | "requests">("friends");
  const [friends, setFriends] = useState<FriendRow[]>([]);
  const [incoming, setIncoming] = useState<PendingRow[]>([]);
  const [outgoing, setOutgoing] = useState<PendingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [f, p] = await Promise.all([
        api.friendsList(), api.friendsPending(),
      ]);
      setFriends(f.items);
      setIncoming(p.incoming);
      setOutgoing(p.outgoing);
    } catch (e) {
      showToast("error", (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));
  useEffect(() => { void load(); }, [load]);

  async function acceptReq(id: string) {
    try {
      await api.friendsAccept(id);
      showToast("success", "Demande acceptée !");
      void load();
    } catch (e) { showToast("error", (e as Error).message); }
  }
  async function rejectReq(id: string) {
    try {
      await api.friendsReject(id);
      showToast("success", "Demande refusée.");
      void load();
    } catch (e) { showToast("error", (e as Error).message); }
  }

  const totalPending = incoming.length;

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="friends-back">
          <Ionicons name="chevron-back" size={24} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Mes amis</Text>
        <TouchableOpacity onPress={() => setSearchOpen(true)} style={styles.iconBtn} testID="friends-open-search">
          <Ionicons name="person-add" size={22} color={theme.primary} />
        </TouchableOpacity>
      </View>

      {/* Tabs */}
      <View style={styles.tabs}>
        <TabButton label={`Amis (${friends.length})`} active={tab === "friends"} onPress={() => setTab("friends")} />
        <TabButton
          label={`Demandes${totalPending > 0 ? ` (${totalPending})` : ""}`}
          active={tab === "requests"}
          onPress={() => setTab("requests")}
          badge={totalPending}
        />
      </View>

      {/* V3b — big primary CTA replaces the referral-code share card. The
          old code-based invite lives in the header \u002B for power users
          but the main flow is now search by phone / email. */}
      {tab === "friends" && (
        <TouchableOpacity
          style={styles.bigCta}
          onPress={() => setSearchOpen(true)}
          testID="friends-big-add"
          activeOpacity={0.85}
        >
          <View style={styles.bigCtaIcon}>
            <Ionicons name="person-add" size={20} color={theme.bg} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.bigCtaTitle}>Ajouter un ami</Text>
            <Text style={styles.bigCtaSub}>Recherche par téléphone, email ou code parrain.</Text>
          </View>
          <Ionicons name="chevron-forward" size={22} color={theme.bg} />
        </TouchableOpacity>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={theme.primary} /></View>
      ) : tab === "friends" ? (
        friends.length === 0 ? (
          <EmptyState icon="people-outline" title="Aucun ami" body={"Ajoutez un ami avec le \u002B ci-dessus, ou partagez votre code."} />
        ) : (
          <FlatList
            data={friends}
            keyExtractor={(f) => f.user_id}
            contentContainerStyle={styles.list}
            renderItem={({ item }) => (
              <FriendCard
                friend={item}
                onPress={() => router.push(`/profile/friends/${item.user_id}`)}
              />
            )}
          />
        )
      ) : (
        <FlatList
          data={incoming}
          keyExtractor={(r) => r.id}
          contentContainerStyle={styles.list}
          ListEmptyComponent={
            <EmptyState icon="mail-open-outline" title="Aucune demande" body="Les demandes reçues apparaîtront ici." />
          }
          renderItem={({ item }) => (
            <View style={styles.reqCard} testID={`req-${item.id}`}>
              <View style={styles.avatar}>
                <Ionicons name="person" size={22} color={theme.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.pseudo}>{item.user.pseudo}</Text>
                <Text style={styles.subline}>{item.user.rank_label} · {item.user.points} pts</Text>
              </View>
              <TouchableOpacity style={styles.accept} onPress={() => acceptReq(item.id)} testID={`req-accept-${item.id}`}>
                <Ionicons name="checkmark" size={18} color="#0B132B" />
              </TouchableOpacity>
              <TouchableOpacity style={styles.reject} onPress={() => rejectReq(item.id)} testID={`req-reject-${item.id}`}>
                <Ionicons name="close" size={18} color="#FF6B6B" />
              </TouchableOpacity>
            </View>
          )}
          ListFooterComponent={
            outgoing.length > 0 ? (
              <View style={{ marginTop: spacing.md }}>
                <Text style={styles.sectionTitle}>Demandes envoyées</Text>
                {outgoing.map((r) => (
                  <View key={r.id} style={styles.reqCard}>
                    <View style={styles.avatar}><Ionicons name="person" size={22} color={theme.textDim} /></View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.pseudo}>{r.user.pseudo}</Text>
                      <Text style={styles.subtle}>En attente…</Text>
                    </View>
                    <TouchableOpacity
                      style={styles.cancelBtn}
                      onPress={() => rejectReq(r.id)}
                      testID={`req-cancel-${r.id}`}
                    >
                      <Ionicons name="close-circle-outline" size={16} color="#FF6B6B" />
                      <Text style={styles.cancelBtnText}>Annuler</Text>
                    </TouchableOpacity>
                  </View>
                ))}
              </View>
            ) : null
          }
        />
      )}

      {/* Search modal */}
      <SearchModal
        visible={searchOpen}
        onClose={() => setSearchOpen(false)}
        onDone={() => { setSearchOpen(false); void load(); }}
      />
    </SafeAreaView>
  );
}

function TabButton({ label, active, onPress, badge }: { label: string; active: boolean; onPress: () => void; badge?: number }) {
  return (
    <TouchableOpacity style={[styles.tabBtn, active && styles.tabBtnActive]} onPress={onPress} activeOpacity={0.85}>
      <Text style={[styles.tabLabel, active && styles.tabLabelActive]}>{label}</Text>
      {(badge ?? 0) > 0 && <View style={styles.dot} />}
    </TouchableOpacity>
  );
}

function FriendCard({ friend, onPress }: { friend: FriendRow; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.85}>
      <View style={styles.avatar}><Ionicons name="person" size={22} color={theme.primary} /></View>
      <View style={{ flex: 1 }}>
        <Text style={styles.pseudo}>{friend.pseudo}</Text>
        <Text style={styles.subline}>{friend.rank_label} · {friend.points} pts · fiab. {friend.reliability_score}%</Text>
      </View>
      <Ionicons name="chevron-forward" size={20} color={theme.textDim} />
    </TouchableOpacity>
  );
}

function EmptyState({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <View style={styles.empty}>
      <Ionicons name={icon as never} size={44} color={theme.textDim} />
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyBody}>{body}</Text>
    </View>
  );
}

function SearchModal({ visible, onClose, onDone }: { visible: boolean; onClose: () => void; onDone: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.friendsSearch>> | null>(null);
  // Contact/recherche sans compte SignalMar → on PROPOSE DE L'INVITER
  // (carte dédiée) au lieu d'afficher une erreur rouge (retour user 11/07 :
  // « un ami que j'invite n'est évidemment pas déjà sur SignalMar »).
  const [notFound, setNotFound] = useState<{ name: string } | null>(null);

  async function doSearch() {
    setBusy(true); setResult(null); setNotFound(null);
    try {
      const r = await api.friendsSearch(q.trim());
      setResult(r);
      if (!r.found) setNotFound({ name: q.trim() });
    } catch (e) { showToast("error", (e as Error).message); }
    finally { setBusy(false); }
  }

  // Recherche UNIFIÉE par nom dans le carnet (10/07/2026) : on essaie chaque
  // numéro du contact choisi jusqu'à trouver son compte SignalMar.
  async function pickContact(contact: PickedContact) {
    setBusy(true); setResult(null); setNotFound(null);
    try {
      for (const e164 of contact.e164s) {
        const r = await api.friendsSearch(e164);
        if (r.found) { setResult(r); setBusy(false); return; }
      }
      setNotFound({ name: contact.displayName });
    } catch (e) { showToast("error", (e as Error).message); }
    finally { setBusy(false); }
  }

  async function sendReq() {
    if (!result?.found) return;
    setBusy(true);
    try {
      const r = await api.friendsRequest(result.found.user_id);
      if (r.already_friends) showToast("success", "Vous êtes déjà amis !");
      else showToast("success", "Demande envoyée !");
      setQ(""); setResult(null); onDone();
    } catch (e) { showToast("error", (e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.modalBackdrop} onPress={onClose}>
        <Pressable style={styles.modalCard} onPress={(e) => e.stopPropagation()}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Ajouter un ami</Text>
            <TouchableOpacity onPress={onClose}><Ionicons name="close" size={22} color={theme.textDim} /></TouchableOpacity>
          </View>
          <ScrollView
            style={{ maxHeight: 480 }}
            contentContainerStyle={{ gap: spacing.sm }}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
          {/* Recherche UNIFIÉE par NOM dans le carnet (composant partagé). */}
          <Text style={styles.modalHint}>Recherchez un contact par son nom :</Text>
          <ContactNameSearch
            onSelect={pickContact}
            busy={busy}
            placeholder="Nom du contact…"
            testIDPrefix="friends-contact-search"
          />
          <Text style={styles.modalHint}>…ou par email, téléphone ou code parrain :</Text>
          <TextInput
            style={styles.searchInput}
            value={q}
            onChangeText={setQ}
            placeholder="ex. ami@mail.com, 0760071445, MARIN42"
            placeholderTextColor={theme.textMute}
            autoCorrect={false}
            autoCapitalize="none"
            onSubmitEditing={doSearch}
            testID="friends-search-input"
          />
          <TouchableOpacity
            style={[styles.searchBtn, (busy || q.trim().length < 3) && { opacity: 0.5 }]}
            onPress={doSearch}
            disabled={busy || q.trim().length < 3}
            testID="friends-search-submit"
          >
            {busy ? <ActivityIndicator color={theme.bg} /> : <Text style={styles.searchBtnText}>Rechercher</Text>}
          </TouchableOpacity>

          {result?.found && (
            <View style={styles.resultCard}>
              <View style={styles.avatar}><Ionicons name="person" size={22} color={theme.primary} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.pseudo}>{result.found.pseudo}</Text>
                <Text style={styles.subline}>{result.found.rank_label} · {result.found.points} pts</Text>
              </View>
              {result.relationship === "friends" ? (
                <Text style={styles.tagFriends}>Déjà amis</Text>
              ) : result.relationship === "outgoing_pending" ? (
                <TouchableOpacity
                  style={styles.cancelBtn}
                  onPress={async () => {
                    if (!result.request_id) return;
                    try {
                      await api.friendsReject(result.request_id);
                      showToast("success", "Demande annulée.");
                      setQ(""); setResult(null); onDone();
                    } catch (e) { showToast("error", (e as Error).message); }
                  }}
                  testID="friends-cancel-outgoing"
                >
                  <Ionicons name="close-circle-outline" size={16} color="#FF6B6B" />
                  <Text style={styles.cancelBtnText}>Annuler</Text>
                </TouchableOpacity>
              ) : result.relationship === "incoming_pending" ? (
                <TouchableOpacity
                  style={styles.tagAccept}
                  onPress={async () => {
                    if (result.request_id) {
                      await api.friendsAccept(result.request_id);
                      showToast("success", "Demande acceptée !");
                      onDone();
                    }
                  }}
                >
                  <Text style={styles.tagAcceptText}>Accepter</Text>
                </TouchableOpacity>
              ) : (
                <TouchableOpacity style={styles.addBtn} onPress={sendReq} disabled={busy} testID="friends-add-submit">
                  <Ionicons name="person-add" size={16} color={theme.bg} />
                  <Text style={styles.addBtnText}>Ajouter</Text>
                </TouchableOpacity>
              )}
            </View>
          )}

          {/* Pas de compte SignalMar → carte INVITATION (jamais d'erreur rouge :
              c'est un cas NORMAL, on transforme la recherche en parrainage). */}
          {notFound && !result?.found && (
            <View style={styles.inviteCard} testID="friends-invite-card">
              <View style={styles.inviteHead}>
                <Ionicons name="paper-plane" size={18} color="#FFD166" />
                <Text style={styles.inviteTitle} numberOfLines={2}>
                  {notFound.name} n{"\u2019"}est pas encore sur SignalMar
                </Text>
              </View>
              <Text style={styles.inviteBody}>
                Invitez-le par SMS : dès qu{"\u2019"}il crée son compte avec votre
                lien, vous pourrez l{"\u2019"}ajouter en ami — et il devient votre
                filleul (points + Premium à la clé 🎁).
              </Text>
              <TouchableOpacity
                style={styles.inviteBtn}
                onPress={() => { onClose(); router.push("/share-invite"); }}
                activeOpacity={0.85}
                testID="friends-invite-btn"
              >
                <Ionicons name="chatbubble-ellipses" size={16} color="#0B132B" />
                <Text style={styles.inviteBtnText}>Inviter par SMS</Text>
              </TouchableOpacity>
            </View>
          )}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
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
  title: { color: theme.text, fontWeight: "800", fontSize: 16 },
  tabs: { flexDirection: "row", padding: spacing.sm, gap: spacing.sm },
  tabBtn: {
    flex: 1, paddingVertical: 10, borderRadius: radii.md,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg2,
    flexDirection: "row", gap: 6,
  },
  tabBtnActive: { backgroundColor: theme.primary, borderColor: theme.primary },
  tabLabel: { color: theme.textDim, fontWeight: "700", fontSize: 13 },
  tabLabelActive: { color: theme.bg, fontWeight: "900" },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#FF6B6B" },
  shareCard: {
    margin: spacing.md, marginTop: 0, padding: spacing.sm,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: "#FFD166", gap: 6,
  },
  shareTop: { flexDirection: "row", alignItems: "center", gap: 6 },
  shareTitle: { color: "#FFD166", fontWeight: "900", fontSize: 13 },
  shareRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  codeBox: {
    flex: 1, paddingVertical: 8, paddingHorizontal: 12,
    backgroundColor: theme.bg, borderRadius: radii.sm,
    borderWidth: 1, borderColor: "#FFD166", borderStyle: "dashed", alignItems: "center",
  },
  codeText: { color: "#FFD166", fontFamily: "monospace", fontWeight: "900", fontSize: 16, letterSpacing: 3 },
  shareBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: theme.primary, paddingHorizontal: 10, paddingVertical: 8, borderRadius: radii.sm },
  shareBtnText: { color: theme.bg, fontWeight: "900", fontSize: 12 },
  shareBody: { color: theme.textDim, fontSize: 11 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg, gap: spacing.sm },
  emptyTitle: { color: theme.text, fontWeight: "800", fontSize: 15 },
  emptyBody: { color: theme.textDim, fontSize: 13, textAlign: "center", maxWidth: 280 },
  list: { padding: spacing.md, gap: 8 },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.sm, backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  reqCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.sm, backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, marginBottom: 8,
  },
  avatar: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.border,
  },
  pseudo: { color: theme.text, fontWeight: "800", fontSize: 14 },
  subline: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  subtle: { color: theme.textMute, fontSize: 11, marginTop: 2 },
  sectionTitle: { color: theme.textDim, fontSize: 12, fontWeight: "700", marginBottom: 8, letterSpacing: 0.4 },
  accept: { width: 40, height: 40, borderRadius: 20, backgroundColor: "#4ADE80", alignItems: "center", justifyContent: "center" },
  reject: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.bg, borderWidth: 1, borderColor: "#FF6B6B", alignItems: "center", justifyContent: "center", marginLeft: 6 },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center", padding: spacing.lg },
  modalCard: { width: "100%", maxWidth: 440, backgroundColor: theme.bg2, borderRadius: radii.lg, padding: spacing.lg, borderWidth: 1, borderColor: theme.border, gap: spacing.sm },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  modalTitle: { color: theme.text, fontWeight: "900", fontSize: 16 },
  modalHint: { color: theme.textDim, fontSize: 12, marginBottom: 4 },
  searchInput: { backgroundColor: theme.bg, color: theme.text, borderWidth: 1, borderColor: theme.primary, borderRadius: radii.md, paddingHorizontal: 12, paddingVertical: 12, fontSize: 14 },
  searchBtn: { minHeight: 44, borderRadius: radii.md, backgroundColor: theme.primary, alignItems: "center", justifyContent: "center", marginTop: 4 },
  searchBtnText: { color: theme.bg, fontWeight: "900" },
  resultCard: {
    flexDirection: "row", alignItems: "center", gap: 10, marginTop: spacing.sm,
    padding: spacing.sm, backgroundColor: theme.bg, borderRadius: radii.md, borderWidth: 1, borderColor: theme.border,
  },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: theme.primary, paddingHorizontal: 10, paddingVertical: 8, borderRadius: radii.sm },
  addBtnText: { color: theme.bg, fontWeight: "900", fontSize: 12 },
  tagFriends: { color: theme.success, fontWeight: "800", fontSize: 11 },
  tagPending: { color: theme.textMute, fontWeight: "700", fontSize: 11, fontStyle: "italic" },
  tagAccept: { backgroundColor: theme.success, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radii.sm },
  tagAcceptText: { color: "#0B132B", fontWeight: "900", fontSize: 12 },
  // "Annuler" button for outgoing pending requests (both in the search modal
  // and in the Demandes tab).
  cancelBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.bg, paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: radii.sm, borderWidth: 1, borderColor: "#FF6B6B",
  },
  cancelBtnText: { color: "#FF6B6B", fontWeight: "800", fontSize: 12 },
  // Carte « Inviter » — contact/recherche sans compte SignalMar (11/07).
  inviteCard: {
    marginTop: spacing.sm, padding: spacing.sm, gap: 8,
    backgroundColor: "rgba(255,209,102,0.08)", borderRadius: radii.md,
    borderWidth: 1, borderColor: "rgba(255,209,102,0.45)",
  },
  inviteHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  inviteTitle: { color: "#FFD166", fontWeight: "900", fontSize: 14, flex: 1 },
  inviteBody: { color: theme.textDim, fontSize: 12, lineHeight: 17 },
  inviteBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#FFD166", borderRadius: radii.md, minHeight: 44,
  },
  inviteBtnText: { color: "#0B132B", fontWeight: "900", fontSize: 14 },
  // V3b — big "Ajouter un ami" primary CTA replaces the referral share card.
  bigCta: {
    marginHorizontal: spacing.md, marginBottom: spacing.md,
    padding: spacing.md, borderRadius: radii.lg,
    backgroundColor: theme.primary,
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 3,
  },
  bigCtaIcon: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "rgba(11,19,43,0.15)",
    alignItems: "center", justifyContent: "center",
  },
  bigCtaTitle: { color: theme.bg, fontWeight: "900", fontSize: 16 },
  bigCtaSub: { color: theme.bg, fontSize: 12, opacity: 0.85, marginTop: 2 },
});
