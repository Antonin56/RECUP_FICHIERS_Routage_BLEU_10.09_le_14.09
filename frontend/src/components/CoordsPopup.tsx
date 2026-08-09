// SignalMar — Popup d'affichage des coordonnées GPS.
//
// Ouverte par un tap sur le badge GPS en haut de la carte.
// Affiche les deux formats les plus utiles (DM Navionics + DD Google Maps),
// chacun avec un bouton "Copier" et une icône de partage globale.

import { useState } from "react";
import * as Clipboard from "expo-clipboard";
import {
  Modal,
  Platform,
  Pressable,
  Share,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { formatDD, formatDM } from "@/src/lib/coords";
import { radii, spacing, theme } from "@/src/lib/theme";

type Props = {
  visible: boolean;
  lat: number | null;
  lng: number | null;
  onClose: () => void;
};

export function CoordsPopup({ visible, lat, lng, onClose }: Props) {
  const [copied, setCopied] = useState<"dm" | "dd" | null>(null);

  const dm = lat != null && lng != null ? formatDM(lat, lng) : "—";
  const dd = lat != null && lng != null ? formatDD(lat, lng) : "—";

  async function copy(value: string, which: "dm" | "dd") {
    await Clipboard.setStringAsync(value);
    setCopied(which);
    setTimeout(() => setCopied((c) => (c === which ? null : c)), 1500);
  }

  async function share() {
    if (lat == null || lng == null) return;
    // Lien Google Maps universel — cliquable depuis WhatsApp, SMS, Mail, etc.
    // Sur iOS il ouvre Plans, sur Android il ouvre Google Maps / l'app par
    // défaut, sur les navigateurs il ouvre Maps web. Navionics intercepte
    // aussi automatiquement les `geo:` URIs sur Android quand l'app est
    // installée.
    const mapsUrl = `https://www.google.com/maps?q=${lat},${lng}`;
    // Message en TEXTE BRUT — le destinataire pourra le sélectionner /
    // copier dans son app (WhatsApp / SMS / Mail), et le lien sera
    // rendu cliquable automatiquement par l'app de messagerie.
    const message =
      `📍 Ma position SignalMar\n` +
      `${dm}\n` +
      `${dd}\n` +
      `${mapsUrl}`;
    if (Platform.OS === "web") {
      try {
        if (typeof navigator !== "undefined" && (navigator as Navigator & { share?: (data: ShareData) => Promise<void> }).share) {
          await (navigator as Navigator & { share: (data: ShareData) => Promise<void> }).share({ title: "Ma position SignalMar", text: message });
        } else {
          await Clipboard.setStringAsync(message);
        }
      } catch { /* user cancelled */ }
      return;
    }
    try {
      // L'API Share native de React Native ouvre la share sheet OS avec un
      // MESSAGE TEXTE (pas un fichier .txt). Les apps de messagerie
      // reçoivent le texte sélectionnable + détectent automatiquement le
      // lien Google Maps.
      await Share.share(
        {
          message,
          title: "Ma position SignalMar",
        },
        {
          dialogTitle: "Partager ma position",
          subject: "Ma position SignalMar",
        },
      );
    } catch { /* user cancelled / no apps */ }
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={styles.card} onPress={() => { /* swallow */ }}>
          <View style={styles.header}>
            <Ionicons name="locate" size={18} color={theme.primary} />
            <Text style={styles.title}>Ma position</Text>
            <TouchableOpacity
              onPress={share}
              hitSlop={{ top: 12, right: 12, bottom: 12, left: 12 }}
              style={styles.shareBtn}
              testID="coords-share"
              activeOpacity={0.7}
            >
              <Ionicons name="share-outline" size={20} color={theme.primary} />
            </TouchableOpacity>
            <TouchableOpacity
              onPress={onClose}
              hitSlop={{ top: 12, right: 12, bottom: 12, left: 12 }}
              testID="coords-close"
            >
              <Ionicons name="close" size={22} color={theme.textDim} />
            </TouchableOpacity>
          </View>

          {/* DM — format principal nautique */}
          <View style={styles.block}>
            <View style={styles.row}>
              <Text style={styles.value} selectable testID="coords-dm-value">{dm}</Text>
              <TouchableOpacity
                style={styles.copyBtn}
                onPress={() => copy(dm, "dm")}
                hitSlop={{ top: 10, right: 10, bottom: 10, left: 10 }}
                testID="coords-copy-dm"
                activeOpacity={0.7}
              >
                <Ionicons
                  name={copied === "dm" ? "checkmark" : "copy-outline"}
                  size={18}
                  color={copied === "dm" ? theme.success : theme.textDim}
                />
              </TouchableOpacity>
            </View>
            <Text style={styles.hint}>Navionics — format degrés / minutes</Text>
          </View>

          {/* DD — format Google Maps */}
          <View style={styles.block}>
            <View style={styles.row}>
              <Text style={styles.value} selectable testID="coords-dd-value">{dd}</Text>
              <TouchableOpacity
                style={styles.copyBtn}
                onPress={() => copy(dd, "dd")}
                hitSlop={{ top: 10, right: 10, bottom: 10, left: 10 }}
                testID="coords-copy-dd"
                activeOpacity={0.7}
              >
                <Ionicons
                  name={copied === "dd" ? "checkmark" : "copy-outline"}
                  size={18}
                  color={copied === "dd" ? theme.success : theme.textDim}
                />
              </TouchableOpacity>
            </View>
            <Text style={styles.hint}>Google Maps — format décimal</Text>
          </View>

          {copied && (
            <Text style={styles.feedback}>Coordonnées copiées dans le presse-papier</Text>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  card: {
    width: "100%",
    maxWidth: 460,
    backgroundColor: theme.bg2,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: theme.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  title: {
    flex: 1,
    color: theme.text,
    fontWeight: "900",
    fontSize: 15,
  },
  shareBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.primary + "22",
  },
  block: {
    backgroundColor: theme.bg3,
    borderRadius: radii.md,
    padding: spacing.sm,
    gap: 4,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  value: {
    flex: 1,
    color: theme.text,
    fontSize: 18,
    fontWeight: "900",
    letterSpacing: 0.3,
    fontVariant: ["tabular-nums"],
  },
  copyBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
  },
  hint: {
    color: theme.textMute,
    fontSize: 10,
    fontStyle: "italic",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  feedback: {
    color: theme.success,
    fontSize: 11,
    fontWeight: "700",
    textAlign: "center",
    marginTop: 2,
  },
});
