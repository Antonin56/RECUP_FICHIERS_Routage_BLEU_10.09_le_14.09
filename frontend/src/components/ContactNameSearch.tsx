// SignalMar — Recherche UNIFIÉE dans le carnet d'adresses par NOM (10/07/2026).
//
// Bloc réutilisé partout où l'on cherche une personne : ajout d'ami,
// recherche de parrain à l'inscription, etc. Comportement identique :
//   • permission contacts demandée au montage (états denied gérés) ;
//   • champ de recherche par NOM (insensible à la casse et aux accents) ;
//   • une ligne par CONTACT (numéros regroupés), 6 résultats max ;
//   • onSelect(contact) — le parent décide quoi en faire (résoudre un
//     compte SignalMar, envoyer une demande d'ami, remplir un code…).

import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import {
  loadLocalContacts,
  requestContactsPermission,
  type LocalPhoneInfo,
} from "@/src/lib/contact-sync";
import { ContactsRefreshButton } from "@/src/components/ContactsRefreshButton";
import { theme, radii } from "@/src/lib/theme";

export interface PickedContact {
  contactId: string;
  displayName: string;
  /** Tous les numéros E.164 du contact. */
  e164s: string[];
  /** Hashes SHA-256 correspondants (pour les endpoints privacy-first). */
  hashes: string[];
}

/** Minuscules sans accents — recherche par nom uniforme dans toute l'app. */
export function normalizeName(s: string): string {
  return s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

export function ContactNameSearch({
  onSelect,
  busy = false,
  placeholder = "Nom du contact…",
  testIDPrefix = "contact-search",
  maxResults = 6,
  onFocusInput,
}: {
  onSelect: (contact: PickedContact) => void;
  /** Le parent résout une sélection (spinner sur les lignes). */
  busy?: boolean;
  placeholder?: string;
  testIDPrefix?: string;
  maxResults?: number;
  onFocusInput?: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [contacts, setContacts] = useState<LocalPhoneInfo[]>([]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { granted } = await requestContactsPermission();
        if (!granted) {
          if (alive) setDenied(true);
          return;
        }
        const all = await loadLocalContacts();
        if (alive) setContacts(all);
      } catch {
        if (alive) setDenied(true);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // Regroupe les numéros par contact, filtre par NOM.
  const results = useMemo<PickedContact[]>(() => {
    const byId = new Map<string, PickedContact>();
    for (const c of contacts) {
      const cur = byId.get(c.contactId);
      if (cur) {
        cur.e164s.push(c.e164);
        cur.hashes.push(c.hash);
      } else {
        byId.set(c.contactId, {
          contactId: c.contactId,
          displayName: c.displayName,
          e164s: [c.e164],
          hashes: [c.hash],
        });
      }
    }
    const q = normalizeName(query.trim());
    const list = Array.from(byId.values()).filter(
      (c) => !q || normalizeName(c.displayName).includes(q),
    );
    return list
      .sort((a, b) => a.displayName.localeCompare(b.displayName, "fr"))
      .slice(0, maxResults);
  }, [contacts, query, maxResults]);

  if (loading) {
    return (
      <View style={styles.box}>
        <ActivityIndicator color={theme.primary} style={{ padding: 12 }} />
      </View>
    );
  }

  if (denied) {
    return (
      <View style={styles.box}>
        <Text style={styles.deniedTxt}>
          Accès aux contacts refusé — autorisez SignalMar dans les réglages
          du téléphone, ou continuez sans.
        </Text>
        <TouchableOpacity
          style={styles.settingsBtn}
          onPress={() => Linking.openSettings().catch(() => {})}
          testID={`${testIDPrefix}-open-settings`}
        >
          <Ionicons name="settings-outline" size={14} color={theme.primary} />
          <Text style={styles.settingsBtnTxt}>Ouvrir les Réglages</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.box}>
      <View style={styles.topRow}>
        <View style={styles.inputWrap}>
          <Ionicons name="search" size={14} color={theme.textDim} />
          <TextInput
            style={styles.input}
            value={query}
            onChangeText={setQuery}
            onFocus={onFocusInput}
            placeholder={placeholder}
            placeholderTextColor={theme.textMute}
            autoCorrect={false}
            testID={`${testIDPrefix}-query`}
          />
          {query.length > 0 && (
            <TouchableOpacity onPress={() => setQuery("")} hitSlop={8}>
              <Ionicons name="close-circle" size={16} color={theme.textDim} />
            </TouchableOpacity>
          )}
        </View>
        {/* Cache 30 j → bouton de relecture manuelle du carnet. */}
        <ContactsRefreshButton
          compact
          onRefreshed={setContacts}
          testID={`${testIDPrefix}-refresh`}
        />
      </View>
      {results.map((c) => (
        <TouchableOpacity
          key={c.contactId}
          style={styles.row}
          onPress={() => onSelect(c)}
          disabled={busy}
          testID={`${testIDPrefix}-row-${c.contactId}`}
        >
          <View style={styles.avatar}>
            <Text style={styles.avatarTxt}>{c.displayName.slice(0, 1).toUpperCase()}</Text>
          </View>
          <Text style={styles.name} numberOfLines={1}>{c.displayName}</Text>
          {busy ? (
            <ActivityIndicator size="small" color={theme.primary} />
          ) : (
            <Ionicons name="chevron-forward" size={15} color={theme.textDim} />
          )}
        </TouchableOpacity>
      ))}
      {results.length === 0 && (
        <Text style={styles.noResult}>
          {query ? "Aucun contact trouvé." : "Tapez un nom pour chercher."}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    padding: 10, gap: 6,
  },
  inputWrap: {
    flex: 1,
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.bg, borderRadius: radii.sm,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 10, minHeight: 40,
  },
  topRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  input: { flex: 1, color: theme.text, fontSize: 14, paddingVertical: 8 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 6, paddingVertical: 8, minHeight: 44,
  },
  avatar: {
    width: 30, height: 30, borderRadius: 15, backgroundColor: theme.bg3,
    alignItems: "center", justifyContent: "center",
  },
  avatarTxt: { color: theme.primary, fontWeight: "800", fontSize: 13 },
  name: { color: theme.text, fontSize: 14, fontWeight: "600", flex: 1 },
  noResult: { color: theme.textMute, fontSize: 12, textAlign: "center", paddingVertical: 8 },
  deniedTxt: { color: theme.textDim, fontSize: 12, lineHeight: 17 },
  settingsBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    alignSelf: "flex-start", paddingVertical: 8, minHeight: 36,
  },
  settingsBtnTxt: { color: theme.primary, fontSize: 13, fontWeight: "700" },
});
