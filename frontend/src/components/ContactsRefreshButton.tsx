// SignalMar — Bouton « Mettre à jour les contacts » (11/07/2026).
//
// Le carnet est mis en CACHE 30 jours (voir contact-sync.ts) car sa lecture
// est lente. Ce bouton (icône contact + flèche) force la relecture du
// téléphone et repart pour 30 jours. Réutilisé partout où l'on cherche
// dans les contacts : ContactNameSearch, /share-invite, /groups/invite.

import { useState } from "react";
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { loadLocalContacts, type LocalPhoneInfo } from "@/src/lib/contact-sync";
import { showToast } from "@/src/components/Toast";
import { theme } from "@/src/lib/theme";

export function ContactsRefreshButton({
  onRefreshed,
  compact = false,
  testID = "contacts-refresh",
}: {
  /** Reçoit la liste FRAÎCHE (peut être async : matching serveur, etc.). */
  onRefreshed: (contacts: LocalPhoneInfo[]) => void | Promise<void>;
  /** true = icône seule (headers) ; false = icône + libellé. */
  compact?: boolean;
  testID?: string;
}) {
  const [busy, setBusy] = useState(false);

  async function refresh() {
    if (busy) return;
    setBusy(true);
    try {
      const all = await loadLocalContacts({ forceRefresh: true });
      await onRefreshed(all);
      showToast("success", "Contacts mis à jour 👍");
    } catch {
      showToast("error", "Mise à jour des contacts impossible");
    } finally {
      setBusy(false);
    }
  }

  return (
    <TouchableOpacity
      style={[styles.btn, compact && styles.btnCompact]}
      onPress={refresh}
      disabled={busy}
      activeOpacity={0.85}
      testID={testID}
      accessibilityLabel="Mettre à jour les contacts"
    >
      {busy ? (
        <ActivityIndicator size="small" color={theme.primary} />
      ) : (
        <View style={styles.iconWrap}>
          <Ionicons name="people" size={17} color={theme.primary} />
          <View style={styles.arrowBadge}>
            <Ionicons name="refresh" size={9} color={theme.bg} />
          </View>
        </View>
      )}
      {!compact && <Text style={styles.label}>Mettre à jour</Text>}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg3,
    borderRadius: 10, paddingHorizontal: 10, minHeight: 40, minWidth: 44,
  },
  btnCompact: { paddingHorizontal: 0, width: 44 },
  iconWrap: { width: 22, height: 20, justifyContent: "center" },
  arrowBadge: {
    position: "absolute", right: -3, bottom: -3,
    width: 13, height: 13, borderRadius: 7, backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  label: { color: theme.textDim, fontSize: 11, fontWeight: "800" },
});
