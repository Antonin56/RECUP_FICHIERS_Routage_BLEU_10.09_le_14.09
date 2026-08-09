/**
 * Page Réglages — refonte 10/07/2026 (maquette utilisateur).
 *
 * Structure (de haut en bas) :
 *   • Visuel « Réglages avancés » (hero engrenage + satellites).
 *   • Section « Zone de veille & alertes » — panneau complet
 *     (zones Vigie/Nav, types de notification, répétitions, voix & vibration).
 *   • Visuel principal de partage (composant ShareAppVisual, réutilisé
 *     depuis la carte profil : tagline + gros bouton + « gagnez des points »).
 *   • Rangées : Abonnement & parrainage · Diagnostic & logs · Comptes de
 *     test (whitelist QA).
 *   • Se déconnecter (rouge) en toute fin.
 *
 * L'historique, les stats, « Revoir l'intro » et le disclaimer vivent
 * désormais sur l'onglet Profil (plus de doublon).
 */
import { useEffect, useRef, useState } from "react";
import {
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { useAuth } from "@/src/auth/AuthContext";
import { api } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";
import { AccordionSection } from "@/src/components/AccordionSection";
import { AlertSettingsPanel } from "@/src/components/AlertSettingsPanel";
import { AnchorPanel } from "@/src/components/AnchorPanel";
import { RouteGuardPanel } from "@/src/components/RouteGuardPanel";
import { RoutingEnginePanel } from "@/src/components/RoutingEnginePanel";
import { ShareAppVisual } from "@/src/components/ShareAppVisual";
import { PseudoEditRow } from "@/src/components/PseudoEditRow";

/** 20/07/2026 — familles de réglages (choix armateur : ACCORDÉONS). */
type SettingsFamily = "veille" | "nav" | "boat" | "anchor" | "account";

export default function SettingsScreen() {
  const { signOut, demoMode, user: authUser } = useAuth();
  const router = useRouter();
  // Deep-link « Régler » depuis la bannière de bascule auto de la carte :
  // scroll direct sur la section « Zone de veille & alertes » + surbrillance
  // de la rangée « Bascule auto Vigie ⇄ Navigation ».
  const { focus } = useLocalSearchParams<{ focus?: string }>();
  // 19/07/2026 — la rangée « Comptes de test » n'apparaît que pour les
  // bêta-testeurs déclarés (ou comptes dev/admin).
  const [isTester, setIsTester] = useState(false);
  // 20/07/2026 — accordéons : une seule famille ouverte à la fois.
  // 23/07/2026 (demande armateur) — TOUS les blocs repliés par défaut.
  const [openSection, setOpenSection] = useState<SettingsFamily | null>(null);
  const toggleSection = (f: SettingsFamily) =>
    setOpenSection((cur) => (cur === f ? null : f));
  useEffect(() => {
    api.betaStatus().then((s) => setIsTester(s.is_tester)).catch(() => setIsTester(false));
  }, [authUser?.user_id]);
  const scrollRef = useRef<ScrollView>(null);
  const alertSectionYRef = useRef(0);
  useEffect(() => {
    if (focus !== "autoswitch") return;
    const t = setTimeout(() => {
      scrollRef.current?.scrollTo({ y: Math.max(0, alertSectionYRef.current - 8), animated: true });
    }, 450);
    return () => clearTimeout(t);
  }, [focus]);

  async function logout() {
    await signOut();
    router.replace("/(auth)/welcome");
  }

  // Demo mode without account: show a CTA panel.
  if (demoMode && !authUser) {
    return (
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        <View style={styles.demoEmpty}>
          <View style={styles.avatarFallback}>
            <Ionicons name="eye" size={42} color={theme.bg} />
          </View>
          <Text style={styles.name}>Mode démo</Text>
          <Text style={styles.demoText}>
            Connectez-vous ou créez un compte pour publier des signalements,
            confirmer les alertes, gagner des points et accéder au temps réel.
          </Text>
          <TouchableOpacity
            style={styles.primaryBtn}
            onPress={() => router.push("/(auth)/login")}
            testID="demo-login-cta"
          >
            <Ionicons name="log-in" size={20} color={theme.bg} />
            <Text style={styles.primaryBtnText}>Se connecter / Créer un compte</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.exitDemo} onPress={logout} testID="demo-exit">
            <Text style={styles.exitDemoText}>Quitter le mode démo</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.menuRow, { marginTop: spacing.md, alignSelf: "stretch" }]}
            onPress={() => router.push("/diagnostic")}
            testID="demo-diagnostic"
            activeOpacity={0.85}
          >
            <Ionicons name="bug-outline" size={18} color={theme.textDim} />
            <Text style={styles.menuRowText}>Diagnostic & logs (signaler un bug)</Text>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={styles.topBarTitle}>Paramètres</Text>
      </View>
      <ScrollView ref={scrollRef} contentContainerStyle={styles.scroll}>
        {/* ── Visuel « Réglages avancés » ── */}
        <View style={styles.settingsHero} testID="settings-hero">
          <View style={styles.heroWaveTop} />
          <View style={styles.heroIconCluster}>
            <View style={styles.heroRingOuter} />
            <View style={styles.heroRingInner} />
            <View style={styles.heroGearWrap}>
              <Ionicons name="settings-sharp" size={40} color={theme.bg} />
            </View>
            <View style={[styles.heroSatellite, styles.heroSatTL]}>
              <Ionicons name="radio" size={15} color="#F4A261" />
            </View>
            <View style={[styles.heroSatellite, styles.heroSatTR]}>
              <Ionicons name="notifications" size={15} color={theme.primary} />
            </View>
            <View style={[styles.heroSatellite, styles.heroSatBL]}>
              <Ionicons name="boat" size={15} color={theme.primary} />
            </View>
            <View style={[styles.heroSatellite, styles.heroSatBR]}>
              <Ionicons name="volume-high" size={15} color="#F4A261" />
            </View>
          </View>
          <Text style={styles.heroTitle}>Réglages avancés</Text>
          <Text style={styles.heroSubtitle}>
            Zones de veille, alertes sonores et notifications —
            personnalisez SignalMar à votre navigation.
          </Text>
        </View>

        {/* ── Familles de réglages en ACCORDÉONS (20/07/2026) ── */}
        <View
          style={styles.section}
          onLayout={(e) => { alertSectionYRef.current = e.nativeEvent.layout.y; }}
        >
          <AccordionSection
            icon="eye"
            title="Zones de veille & alertes"
            subtitle="Vigie/Navigation, sons, voix, vibrations, répétitions"
            open={openSection === "veille"}
            onToggle={() => toggleSection("veille")}
            testID="settings-family-veille"
          >
            <AlertSettingsPanel variant="full" highlightAutoSwitch={focus === "autoswitch"} />
          </AccordionSection>
        </View>

        <AccordionSection
          icon="git-branch"
          iconColor="#2EC4B6"
          title="Navigation & routes"
          subtitle="Moteur de calcul, alerte d'écart de route, seuil du corridor"
          open={openSection === "nav"}
          onToggle={() => toggleSection("nav")}
          testID="settings-family-nav"
        >
          <RoutingEnginePanel />
          <View style={{ height: 12 }} />
          <RouteGuardPanel />
        </AccordionSection>

        {/* 28/07 (demande armateur) — « Mon bateau » ouvre DIRECTEMENT la
            page complète (plus d'accordéon ni de clic intermédiaire). */}
        <TouchableOpacity
          style={styles.boatDirectRow}
          onPress={() => router.push("/profile/boat")}
          testID="settings-family-boat"
          activeOpacity={0.85}
        >
          <View style={styles.boatDirectIcon}>
            <Ionicons name="boat" size={18} color="#F4A261" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.boatDirectTitle}>Mon bateau</Text>
            <Text style={styles.boatDirectSub}>
              Réglages de sécurité (routes sûres) & fiche du bateau
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
        </TouchableOpacity>

        <AccordionSection
          icon="lock-closed"
          iconColor="#2EC4B6"
          title="Alarme de mouillage"
          subtitle="Rayon de garde à l'ancre (alarme si le bateau dérive)"
          open={openSection === "anchor"}
          onToggle={() => toggleSection("anchor")}
          testID="settings-family-anchor"
        >
          <AnchorPanel />
        </AccordionSection>

        <AccordionSection
          icon="person-circle"
          title="Compte & application"
          subtitle="Pseudo, abonnement, diagnostic, comptes de test"
          open={openSection === "account"}
          onToggle={() => toggleSection("account")}
          testID="settings-family-account"
        >
          <PseudoEditRow />
          <TouchableOpacity
            style={styles.menuRow}
            onPress={() => router.push("/profile/subscription")}
            testID="profile-subscription"
            activeOpacity={0.85}
          >
            <Ionicons name="diamond-outline" size={18} color="#F4A261" />
            <Text style={[styles.menuRowText, { color: theme.text }]}>Abonnement &amp; parrainage</Text>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.menuRow}
            onPress={() => router.push("/diagnostic")}
            testID="profile-diagnostic"
            activeOpacity={0.85}
          >
            <Ionicons name="bug-outline" size={18} color={theme.textDim} />
            <Text style={styles.menuRowText}>Diagnostic &amp; logs (signaler un bug)</Text>
            <Ionicons name="chevron-forward" size={18} color={theme.textMute} />
          </TouchableOpacity>
          {/* 19/07/2026 — bascule réservée aux bêta-testeurs déclarés
              (règle appliquée aussi côté backend). */}
          {isTester && (
            <TouchableOpacity
              style={[styles.menuRow, styles.testSwitchRow]}
              onPress={() => router.push("/profile/test-switch")}
              testID="settings-test-switch"
              activeOpacity={0.85}
            >
              <Ionicons name="flask" size={18} color={theme.primary} />
              <Text style={[styles.menuRowText, { color: theme.primary }]}>
                Comptes de test — bascule rapide
              </Text>
              <Ionicons name="chevron-forward" size={18} color={theme.primary} />
            </TouchableOpacity>
          )}
        </AccordionSection>

        {/* ── Visuel principal de partage ── */}
        <View style={styles.shareCard}>
          <ShareAppVisual />
        </View>

        {/* ── Déconnexion — en toute fin de page ── */}
        <TouchableOpacity style={styles.logout} onPress={logout} testID="profile-logout-button">
          <Ionicons name="log-out-outline" size={20} color={theme.danger} />
          <Text style={styles.logoutText}>Se déconnecter</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  topBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  topBarTitle: { color: theme.text, fontSize: 17, fontWeight: "800", flex: 1 },
  scroll: { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xxl },

  // ── Visuel « Réglages avancés » ──
  settingsHero: {
    backgroundColor: theme.bg2, padding: spacing.lg, borderRadius: radii.lg,
    alignItems: "center", gap: 6, borderWidth: 1, borderColor: theme.border,
    overflow: "hidden",
  },
  heroWaveTop: {
    position: "absolute", top: -70, left: -40, right: -40, height: 140,
    borderRadius: 999, backgroundColor: "rgba(72,202,228,0.08)",
  },
  heroIconCluster: {
    width: 120, height: 120, alignItems: "center", justifyContent: "center",
    marginBottom: 4,
  },
  heroRingOuter: {
    position: "absolute", width: 118, height: 118, borderRadius: 59,
    borderWidth: 1, borderColor: "rgba(72,202,228,0.25)",
  },
  heroRingInner: {
    position: "absolute", width: 92, height: 92, borderRadius: 46,
    borderWidth: 1, borderColor: "rgba(244,162,97,0.35)",
  },
  heroGearWrap: {
    width: 68, height: 68, borderRadius: 34, backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
    shadowColor: theme.primary, shadowOpacity: 0.45, shadowRadius: 14,
    shadowOffset: { width: 0, height: 0 }, elevation: 8,
  },
  heroSatellite: {
    position: "absolute", width: 30, height: 30, borderRadius: 15,
    backgroundColor: theme.bg3, borderWidth: 1, borderColor: theme.border,
    alignItems: "center", justifyContent: "center",
  },
  heroSatTL: { top: 2, left: 2 },
  heroSatTR: { top: 2, right: 2 },
  heroSatBL: { bottom: 2, left: 2 },
  heroSatBR: { bottom: 2, right: 2 },
  heroTitle: { color: theme.text, fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  heroSubtitle: {
    color: theme.textDim, fontSize: 12, lineHeight: 17, textAlign: "center",
    paddingHorizontal: spacing.sm,
  },

  // ── Sections ──
  section: { gap: spacing.sm },
  familyHint: { color: theme.textMute, fontSize: 11, lineHeight: 15 },
  // 28/07 — rangée directe « Mon bateau » (même gabarit que l'en-tête des
  // accordéons pour rester homogène).
  boatDirectRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md, minHeight: 56,
  },
  boatDirectIcon: {
    width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(244,162,97,0.14)",
  },
  boatDirectTitle: { color: theme.text, fontSize: 14.5, fontWeight: "800" },
  boatDirectSub: { color: theme.textMute, fontSize: 11.5, marginTop: 1 },

  // ── Visuel principal de partage ──
  shareCard: {
    backgroundColor: theme.bg2, padding: spacing.lg, borderRadius: radii.lg,
    borderWidth: 1, borderColor: theme.border,
    marginTop: spacing.sm,
  },

  // ── Rangées + déconnexion ──
  menuRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md, padding: spacing.md,
    borderWidth: 1, borderColor: theme.border, minHeight: 52,
  },
  menuRowText: { color: theme.textDim, fontWeight: "700", fontSize: 14, flex: 1 },
  testSwitchRow: {
    borderColor: theme.primary,
    backgroundColor: "rgba(72,202,228,0.06)",
  },
  logout: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderWidth: 1, borderColor: theme.danger, minHeight: 52,
    marginTop: spacing.sm,
  },
  logoutText: { color: theme.danger, fontWeight: "800", fontSize: 15 },

  // ── Mode démo ──
  demoEmpty: {
    flex: 1, alignItems: "center", justifyContent: "center",
    padding: spacing.lg, gap: spacing.md,
  },
  avatarFallback: {
    width: 96, height: 96, borderRadius: 48, backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center", borderWidth: 3, borderColor: theme.accent,
  },
  name: { color: theme.text, fontSize: 22, fontWeight: "900" },
  demoText: { color: theme.textDim, textAlign: "center", lineHeight: 20 },
  primaryBtn: {
    backgroundColor: theme.primary, paddingHorizontal: spacing.lg, paddingVertical: 14,
    borderRadius: radii.md, flexDirection: "row", alignItems: "center", gap: 8,
    minHeight: 52, justifyContent: "center", alignSelf: "stretch",
  },
  primaryBtnText: { color: theme.bg, fontWeight: "900", fontSize: 16 },
  exitDemo: { padding: spacing.sm },
  exitDemoText: { color: theme.textMute, fontSize: 13 },
});
