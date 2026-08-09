// SignalMar — « Visuel principal » de partage (10/07/2026).
//
// Bloc réutilisable partout où l'on incite au partage de l'app :
//   • titre « Partagez l'app ! » (grossi, avec pastille mégaphone) ;
//   • tagline « Plus nous serons nombreux… » ;
//   • gros bouton « Partager SignalMar » → écran /share-invite (choix de
//     contacts + SMS groupé prérempli avec l'URL d'affiliation) ;
//   • ligne bonus « … et gagnez des points ! » (étoiles dorées) ;
//   • lien discret « Partager autrement… » (feuille de partage classique).
//
// Utilisé sur : la carte profil (onglet Profil) et la page Réglages.

import { Share, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth/AuthContext";
import { theme, radii } from "@/src/lib/theme";
import { shareAppMessage } from "@/src/lib/share-app";

export function ShareAppVisual() {
  const { user } = useAuth();
  const router = useRouter();
  return (
    <View style={styles.wrap}>
      {/* Titre « Partagez l'app ! » — plus gros, avec un petit visuel. */}
      <View style={styles.titleRow}>
        <View style={styles.titleIconWrap}>
          <Ionicons name="megaphone" size={16} color={theme.bg} />
        </View>
        <Text style={styles.titleText}>Partagez l&apos;app !</Text>
      </View>
      <Text style={styles.tagline}>
        Plus nous serons nombreux,{"\n"}plus nous serons en sécurité sur l&apos;eau
      </Text>
      <TouchableOpacity
        style={styles.shareBtn}
        onPress={() => router.push("/share-invite")}
        activeOpacity={0.85}
        testID="share-app-button"
      >
        <Ionicons name="share-social" size={20} color={theme.primary} />
        <Text style={styles.shareBtnText}>Partager SignalMar</Text>
      </TouchableOpacity>
      <View style={styles.bonusRow}>
        <Ionicons name="sparkles" size={14} color="#FFD166" />
        <Text style={styles.bonusText}>… et gagnez des points !</Text>
        <Ionicons name="sparkles" size={14} color="#FFD166" />
      </View>
      <TouchableOpacity
        style={styles.classicLink}
        onPress={async () => {
          try {
            await Share.share({ message: shareAppMessage(user?.referral_code) });
          } catch { /* user dismissed */ }
        }}
        testID="share-app-classic"
      >
        <Text style={styles.classicLinkTxt}>Partager autrement…</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignSelf: "stretch", alignItems: "center", gap: 10 },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  titleIconWrap: {
    width: 26, height: 26, borderRadius: 13, backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  titleText: {
    color: theme.text, fontSize: 17, fontWeight: "900",
    textTransform: "uppercase", letterSpacing: 1,
  },
  tagline: {
    color: theme.textDim, fontSize: 11.5, fontWeight: "700",
    textAlign: "center", textTransform: "uppercase", letterSpacing: 0.6,
    lineHeight: 17, marginTop: -2,
  },
  shareBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    alignSelf: "stretch", minHeight: 54, borderRadius: radii.lg,
    borderWidth: 1.5, borderColor: theme.primary,
    backgroundColor: "rgba(72,202,228,0.06)",
  },
  shareBtnText: { color: theme.primary, fontSize: 18, fontWeight: "900" },
  bonusRow: { flexDirection: "row", alignItems: "center", gap: 7 },
  bonusText: {
    color: "#FFD166", fontSize: 13, fontWeight: "800",
    letterSpacing: 0.4,
  },
  classicLink: { paddingVertical: 6, minHeight: 32, justifyContent: "center", marginTop: -6 },
  classicLinkTxt: {
    color: theme.textMute, fontSize: 12, fontWeight: "600",
    textDecorationLine: "underline",
  },
});
