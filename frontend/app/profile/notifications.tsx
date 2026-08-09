import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, FlatList, StyleSheet, Text,
  TouchableOpacity, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";
import { formatTimeAgo } from "@/src/lib/coords";
import { showToast } from "@/src/components/Toast";

type Notif = {
  id: string; kind: string; title: string; message: string;
  action_url: string | null; created_at: string; read_at: string | null;
};

/** Phase 3c — In-app notifications drawer (full-screen for now). */
export default function NotificationsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Notif[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const r = await api.notifications(50);
      setItems(r.items);
    } catch (e) { showToast("error", (e as Error).message); }
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));
  useEffect(() => { void load(); }, [load]);

  async function openNotif(n: Notif) {
    if (!n.read_at) {
      try { await api.notificationRead(n.id); } catch { /* silent */ }
      setItems((xs) => xs.map((x) => x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x));
    }
    // FIX 11/07 : route protégée par try/catch — une action_url invalide ne
    // doit jamais faire tomber l'app (le détail gère lui-même l'introuvable).
    if (n.action_url) {
      try { router.push(n.action_url as never); }
      catch { showToast("error", "Ce contenu n'est plus disponible."); }
    }
  }
  async function markAllRead() {
    try { await api.notificationsReadAll(); showToast("success", "Toutes marquées comme lues."); void load(); }
    catch (e) { showToast("error", (e as Error).message); }
  }
  async function clearAll() {
    Alert.alert(
      "Vider les notifications",
      "Cette action supprime définitivement toutes vos notifications.",
      [
        { text: "Annuler", style: "cancel" },
        {
          text: "Vider", style: "destructive",
          onPress: async () => {
            try { await api.notificationsClearAll(); setItems([]); showToast("success", "Notifications vidées."); }
            catch (e) { showToast("error", (e as Error).message); }
          },
        },
      ],
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="notif-back">
          <Ionicons name="chevron-back" size={24} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Notifications</Text>
        <View style={styles.iconBtn} />
      </View>

      {!loading && items.length > 0 && (
        <View style={styles.actions}>
          <TouchableOpacity style={styles.actionBtn} onPress={markAllRead} testID="notif-read-all">
            <Ionicons name="checkmark-done" size={16} color={theme.primary} />
            <Text style={styles.actionText}>Tout marquer lu</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.actionBtn, styles.actionDanger]} onPress={clearAll} testID="notif-clear-all">
            <Ionicons name="trash-outline" size={16} color="#FF6B6B" />
            <Text style={[styles.actionText, { color: "#FF6B6B" }]}>Vider</Text>
          </TouchableOpacity>
        </View>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={theme.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="notifications-off-outline" size={48} color={theme.textDim} />
          <Text style={styles.emptyTitle}>Aucune notification</Text>
          <Text style={styles.emptyBody}>Vos alertes apparaîtront ici.</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(n) => n.id}
          contentContainerStyle={styles.list}
          renderItem={({ item }) => (
            <TouchableOpacity
              style={[styles.card, !item.read_at && styles.cardUnread]}
              onPress={() => openNotif(item)}
              testID={`notif-${item.id}`}
              activeOpacity={0.85}
            >
              <View style={[styles.badge, { backgroundColor: iconColor(item.kind) + "22" }]}>
                <Ionicons name={iconFor(item.kind) as never} size={20} color={iconColor(item.kind)} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle} numberOfLines={1}>{item.title}</Text>
                <Text style={styles.cardMsg} numberOfLines={2}>{item.message}</Text>
                <Text style={styles.cardWhen}>{formatTimeAgo(item.created_at)}</Text>
              </View>
              {!item.read_at && <View style={styles.dot} />}
            </TouchableOpacity>
          )}
        />
      )}
    </SafeAreaView>
  );
}

function iconFor(kind: string): string {
  if (kind.includes("friend_req")) return "person-add";
  if (kind.includes("friend_acc") || kind === "friend_accepted") return "people";
  if (kind.includes("confirm")) return "checkmark-done";
  if (kind.includes("referral")) return "gift";
  if (kind.includes("proxim")) return "location";
  return "notifications";
}
function iconColor(kind: string): string {
  if (kind.includes("referral")) return "#FFD166";
  if (kind.includes("friend_acc")) return theme.success;
  if (kind.includes("confirm")) return theme.primary;
  return theme.primary;
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
  actions: { flexDirection: "row", gap: spacing.sm, padding: spacing.md, paddingBottom: 0 },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radii.md, backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
  },
  actionDanger: { borderColor: "#FF6B6B" },
  actionText: { color: theme.primary, fontWeight: "700", fontSize: 12 },
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
  cardUnread: { borderColor: theme.primary, backgroundColor: theme.bg2 },
  badge: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  cardTitle: { color: theme.text, fontWeight: "800", fontSize: 14 },
  cardMsg: { color: theme.textDim, fontSize: 12, marginTop: 2, lineHeight: 16 },
  cardWhen: { color: theme.textMute, fontSize: 10, marginTop: 4 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#FF6B6B" },
});
