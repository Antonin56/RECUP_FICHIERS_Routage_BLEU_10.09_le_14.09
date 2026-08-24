import { useEffect, useMemo, useRef, useState } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Image,
  ImageBackground,
  Platform,
  ActivityIndicator,
  ScrollView,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";

import { useAuth } from "@/src/auth/AuthContext";
import { api, type SponsorInvitation } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";
import { readPendingRef, clearPendingRef } from "@/src/lib/referral-link";
import { ContactNameSearch, type PickedContact } from "@/src/components/ContactNameSearch";

const HERO =
  "https://images.unsplash.com/photo-1543140313-318677635120?crop=entropy&cs=srgb&fm=jpg&q=85";

/** Formatte "0612345678" → "06 12 34 56 78" pour l'affichage. */
function prettyPhone(digits: string): string {
  return digits.replace(/(\d{2})(?=\d)/g, "$1 ").trim();
}

/** Formatte "0612345678" → "6 12 34 56 78" (affichage après +33). */
function prettyIntl(digits: string): string {
  const d = digits.replace(/^0/, "");
  return d ? `${d[0]} ${d.slice(1).replace(/(\d{2})(?=\d)/g, "$1 ")}`.trim() : "";
}

/** Minuscules sans accents pour la recherche de contact par NOM. */
function normalizeName(s: string): string {
  return s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

export default function Login() {
  const { requestOtp, verifyOtp, loginWithEmail } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState(""); // format local 06/07, chiffres seuls
  const [code, setCode] = useState("");
  // 14/08/2026 (audit QA FND-009) — connexion email + mot de passe.
  const [emailMode, setEmailMode] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pseudo, setPseudo] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [accountExists, setAccountExists] = useState(true);
  const [isMock, setIsMock] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [busy, setBusy] = useState(false);
  const codeRef = useRef<TextInput | null>(null);
  const pseudoRef = useRef<TextInput | null>(null);
  const scrollRef = useRef<ScrollView | null>(null);

  // ── Parrainage (10/07/2026) ──
  // Invitations en cours détectées sur ce numéro (SMS envoyés par des parrains).
  const [invitations, setInvitations] = useState<SponsorInvitation[]>([]);
  // Parrain choisi (invitation ou contact) — affichage de confirmation.
  const [sponsorName, setSponsorName] = useState<string | null>(null);
  // Recherche du parrain dans le carnet (composant unifié ContactNameSearch).
  const [contactSearchOpen, setContactSearchOpen] = useState(false);
  const [resolvingSponsor, setResolvingSponsor] = useState(false);
  const sponsorBoxRef = useRef<View | null>(null);
  const scrollOffset = useRef(0);

  /** Correctif 10/07 — scrolle PRÉCISÉMENT sur le bloc de recherche parrain
   *  (utilisé à l'OUVERTURE du bloc, avant que le clavier ne s'ouvre — le
   *  suivi du champ actif est ensuite géré par KeyboardAwareScrollView). */
  function scrollToSponsorBox() {
    setTimeout(() => {
      sponsorBoxRef.current?.measureInWindow((_x, y) => {
        scrollRef.current?.scrollTo({
          y: Math.max(0, scrollOffset.current + y - 130),
          animated: true,
        });
      });
    }, 250);
  }

  /** Cherche les invitations de parrains en cours sur ce numéro. */
  async function fetchInvitations(forPhone: string) {
    try {
      const r = await api.referralPending(forPhone);
      setInvitations(r.invitations || []);
    } catch { /* silencieux — le champ manuel reste disponible */ }
  }

  function chooseSponsor(inv: SponsorInvitation) {
    setReferralCode(inv.referral_code);
    setSponsorName(inv.pseudo);
    setContactSearchOpen(false);
    showToast("success", `${inv.pseudo} sera votre parrain ⚓`);
  }

  /** Bouton « Rechercher dans mes contacts » : recherche unifiée par nom. */
  function openContactSearch() {
    setContactSearchOpen((v) => {
      if (!v) scrollToSponsorBox();
      return !v;
    });
  }

  /** Le filleul a choisi un contact → on cherche son compte SignalMar. */
  async function pickSponsorContact(contact: PickedContact) {
    if (resolvingSponsor) return;
    setResolvingSponsor(true);
    try {
      const r = await api.referralResolveSponsor(contact.hashes);
      const sponsor = r.sponsors?.[0];
      if (sponsor) {
        chooseSponsor(sponsor);
      } else {
        showToast("error", `${contact.displayName} n'est pas encore sur SignalMar`);
      }
    } catch {
      showToast("error", "Recherche impossible — réessayez");
    } finally {
      setResolvingSponsor(false);
    }
  }

  // Phase B — pré-remplit le code parrain capturé via deep-link (?ref=CODE).
  useEffect(() => {
    (async () => {
      try {
        const pending = await readPendingRef();
        if (pending) setReferralCode(pending);
      } catch { /* ignore */ }
    })();
  }, []);

  // Compte à rebours avant de pouvoir renvoyer un SMS.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const phoneValid = /^0[67]\d{8}$/.test(phone);

  async function sendCode() {
    if (!phoneValid) {
      showToast("error", "Entrez un mobile français valide (06 ou 07).");
      return;
    }
    setBusy(true);
    try {
      const r = await requestOtp(phone);
      setAccountExists(r.account_exists);
      setIsMock(r.mock);
      setCooldown(r.cooldown);
      setCode("");
      setStep("code");
      // Nouveau compte → détection des invitations de parrains en cours.
      if (!r.account_exists) void fetchInvitations(phone);
      setTimeout(() => codeRef.current?.focus(), 350);
    } catch (e) {
      showToast("error", (e as Error).message || "Envoi du code impossible");
    } finally {
      setBusy(false);
    }
  }

  async function verify(input?: string) {
    const theCode = (input ?? code).trim();
    if (theCode.length !== 6) {
      showToast("error", "Entrez le code à 6 chiffres reçu par SMS.");
      return;
    }
    if (!accountExists && pseudo.trim().length < 3) {
      showToast("error", "Choisissez un pseudo (3 caractères minimum).");
      return;
    }
    setBusy(true);
    try {
      await verifyOtp(
        phone,
        theCode,
        !accountExists ? pseudo.trim() : undefined,
        !accountExists ? referralCode.trim() || undefined : undefined,
      );
      await clearPendingRef();
      router.replace("/(tabs)/map");
    } catch (e) {
      showToast("error", (e as Error).message || "Vérification impossible");
    } finally {
      setBusy(false);
    }
  }

  function onCodeChange(t: string) {
    const digits = t.replace(/[^0-9]/g, "").slice(0, 6);
    setCode(digits);
    // Connexion (compte existant) : auto-validation dès le 6ᵉ chiffre.
    if (digits.length === 6 && accountExists && !busy) void verify(digits);
    // Inscription : on enchaîne directement sur le champ pseudo (visible
    // au-dessus du clavier — correctif 10/07).
    if (digits.length === 6 && !accountExists) {
      setTimeout(() => pseudoRef.current?.focus(), 150);
    }
  }

  return (
    <ImageBackground source={{ uri: HERO }} style={styles.bg} resizeMode="cover">
      <LinearGradient
        colors={["rgba(11,19,43,0.6)", "rgba(11,19,43,0.95)", "#0B132B"]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView style={{ flex: 1 }} edges={["top", "bottom"]}>
        {/* P0 clavier (11/07/2026) — KeyboardAwareScrollView
            (react-native-keyboard-controller, inclus dans Expo Go SDK 54) :
            garde TOUJOURS le champ focalisé visible au-dessus du clavier,
            y compris la recherche de parrain en bas du formulaire. */}
        <KeyboardAwareScrollView
          ref={scrollRef}
          style={{ flex: 1 }}
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          bottomOffset={24}
          onScroll={(e) => { scrollOffset.current = e.nativeEvent.contentOffset.y; }}
          scrollEventThrottle={64}
        >
            <View style={styles.brand}>
              <View style={styles.logo}>
                <Ionicons name="navigate" size={32} color={theme.bg} />
              </View>
              <Text style={styles.title}>SignalMar</Text>
              <Text style={styles.tag}>La sécurité en mer, ensemble.</Text>
            </View>

            {step === "phone" && emailMode ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Connexion par email</Text>
                <Text style={styles.cardSub}>
                  {"Réservée aux comptes disposant déjà d'un mot de passe."}
                </Text>
                <Text style={styles.label}>Email</Text>
                <TextInput
                  style={styles.input}
                  value={email}
                  onChangeText={setEmail}
                  placeholder="vous@exemple.fr"
                  placeholderTextColor={theme.textMute}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoComplete="email"
                  testID="login-email"
                />
                <Text style={[styles.label, { marginTop: spacing.sm }]}>Mot de passe</Text>
                <TextInput
                  style={styles.input}
                  value={password}
                  onChangeText={setPassword}
                  placeholder="••••••••"
                  placeholderTextColor={theme.textMute}
                  secureTextEntry
                  autoComplete="password"
                  testID="login-password"
                />
                <TouchableOpacity
                  style={[styles.primary, (busy || !email.includes("@") || password.length < 4) && { opacity: 0.6 }]}
                  onPress={async () => {
                    setBusy(true);
                    try {
                      await loginWithEmail(email, password);
                      router.replace("/(tabs)/map");
                    } catch (e) {
                      showToast("error", e instanceof Error ? e.message : "Identifiants invalides");
                    } finally {
                      setBusy(false);
                    }
                  }}
                  disabled={busy || !email.includes("@") || password.length < 4}
                  testID="login-email-submit"
                >
                  {busy ? (
                    <ActivityIndicator color={theme.bg} />
                  ) : (
                    <>
                      <Ionicons name="log-in" size={18} color={theme.bg} />
                      <Text style={styles.primaryText}>Se connecter</Text>
                    </>
                  )}
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.modeSwitch}
                  onPress={() => setEmailMode(false)}
                  testID="login-mode-phone"
                >
                  <Ionicons name="chatbubble-ellipses-outline" size={14} color={theme.textDim} />
                  <Text style={styles.modeSwitchText}>Se connecter par SMS</Text>
                </TouchableOpacity>
              </View>
            ) : step === "phone" ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Connexion / Inscription</Text>
                <Text style={styles.cardSub}>
                  Entrez votre numéro de mobile : vous recevrez un code par SMS.
                  Pas de mot de passe à retenir.
                </Text>
                <Text style={styles.label}>Numéro de mobile</Text>
                <View style={styles.phoneRow}>
                  <View style={styles.phoneCC}>
                    <Text style={styles.phoneCCText}>🇫🇷 +33</Text>
                  </View>
                  <TextInput
                    style={[styles.input, { flex: 1 }]}
                    value={prettyPhone(phone)}
                    onChangeText={(t) => setPhone(t.replace(/[^0-9]/g, "").slice(0, 10))}
                    placeholder="06 12 34 56 78"
                    placeholderTextColor={theme.textMute}
                    keyboardType="phone-pad"
                    textContentType="telephoneNumber"
                    autoComplete="tel"
                    testID="login-phone"
                  />
                </View>
                <Text style={styles.hint}>
                  {"Votre numéro n'est jamais partagé publiquement ni utilisé à des fins commerciales. Il sert uniquement à sécuriser votre compte et à être retrouvé par vos amis."}
                </Text>
                <TouchableOpacity
                  style={[styles.primary, (busy || !phoneValid) && { opacity: 0.6 }]}
                  onPress={sendCode}
                  disabled={busy || !phoneValid}
                  testID="login-send-code"
                >
                  {busy ? (
                    <ActivityIndicator color={theme.bg} />
                  ) : (
                    <>
                      <Ionicons name="chatbubble-ellipses" size={18} color={theme.bg} />
                      <Text style={styles.primaryText}>Recevoir mon code</Text>
                    </>
                  )}
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.modeSwitch}
                  onPress={() => setEmailMode(true)}
                  testID="login-mode-email"
                >
                  <Ionicons name="mail-outline" size={14} color={theme.textDim} />
                  <Text style={styles.modeSwitchText}>Se connecter par email et mot de passe</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <View style={styles.card}>
                <TouchableOpacity
                  style={styles.backRow}
                  onPress={() => { setStep("phone"); setCode(""); }}
                  testID="otp-back"
                >
                  <Ionicons name="arrow-back" size={16} color={theme.textDim} />
                  <Text style={styles.backText}>Modifier le numéro</Text>
                </TouchableOpacity>
                <Text style={styles.cardTitle}>
                  {accountExists ? "Bon retour à bord !" : "Bienvenue à bord !"}
                </Text>
                <Text style={styles.cardSub}>
                  Code envoyé par SMS au{" "}
                  <Text style={{ color: theme.text, fontWeight: "800" }}>
                    +33 {prettyIntl(phone)}
                  </Text>
                </Text>

                {isMock ? (
                  <View style={styles.mockPill}>
                    <Ionicons name="flask" size={13} color="#FFD166" />
                    <Text style={styles.mockText}>Mode test : utilisez le code 123456</Text>
                  </View>
                ) : null}

                <Text style={styles.label}>Code de vérification</Text>
                <TextInput
                  ref={codeRef}
                  style={styles.otpInput}
                  value={code}
                  onChangeText={onCodeChange}
                  placeholder="••••••"
                  placeholderTextColor={theme.textMute}
                  keyboardType="number-pad"
                  textContentType="oneTimeCode"
                  autoComplete={Platform.OS === "android" ? "sms-otp" : "one-time-code"}
                  maxLength={6}
                  testID="login-otp"
                />

                {!accountExists ? (
                  <>
                    <View style={styles.newBadge}>
                      <Ionicons name="sparkles" size={13} color="#48CAE4" />
                      <Text style={styles.newBadgeText}>
                        Nouveau numéro — on crée votre compte
                      </Text>
                    </View>
                    <Text style={styles.label}>Votre pseudo</Text>
                    <TextInput
                      ref={pseudoRef}
                      style={styles.input}
                      value={pseudo}
                      onChangeText={(t) => setPseudo(t.slice(0, 24))}
                      placeholder="ex. Skipper Léo"
                      placeholderTextColor={theme.textMute}
                      autoCorrect={false}
                      returnKeyType="next"
                      testID="register-pseudo"
                    />
                    <Text style={styles.label}>Code parrain (optionnel)</Text>

                    {/* Invitations de parrains détectées sur ce numéro. */}
                    {invitations.length > 0 && !sponsorName && (
                      <View style={styles.invitationsBox} testID="sponsor-invitations">
                        <Text style={styles.invitationsTitle}>
                          💌 {invitations.length > 1
                            ? `${invitations.length} marins vous ont invité — choisissez votre parrain :`
                            : "Un marin vous a invité :"}
                        </Text>
                        {invitations.map((inv) => (
                          <TouchableOpacity
                            key={inv.referral_code}
                            style={styles.invitationRow}
                            onPress={() => chooseSponsor(inv)}
                            testID={`sponsor-invite-${inv.referral_code}`}
                          >
                            {inv.picture ? (
                              <Image source={{ uri: inv.picture }} style={styles.invitationAvatar} />
                            ) : (
                              <View style={[styles.invitationAvatar, styles.invitationAvatarFallback]}>
                                <Ionicons name="person" size={14} color={theme.bg} />
                              </View>
                            )}
                            <Text style={styles.invitationName} numberOfLines={1}>{inv.pseudo}</Text>
                            <Text style={styles.invitationChoose}>Choisir ⚓</Text>
                          </TouchableOpacity>
                        ))}
                      </View>
                    )}

                    {sponsorName ? (
                      <View style={styles.sponsorChosen} testID="sponsor-chosen">
                        <Ionicons name="checkmark-circle" size={18} color="#2EC4B6" />
                        <Text style={styles.sponsorChosenTxt}>
                          Parrain : <Text style={{ color: theme.text }}>{sponsorName}</Text> ({referralCode})
                        </Text>
                        <TouchableOpacity
                          onPress={() => { setSponsorName(null); setReferralCode(""); }}
                          hitSlop={8}
                        >
                          <Ionicons name="close-circle" size={18} color={theme.textMute} />
                        </TouchableOpacity>
                      </View>
                    ) : (
                      <TextInput
                        style={styles.input}
                        value={referralCode}
                        onChangeText={(t) =>
                          setReferralCode(t.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8))
                        }
                        onFocus={() => {
                          // Re-vérifie les invitations au focus (le SMS du
                          // parrain a pu arriver entre-temps). Le scroll est
                          // géré par KeyboardAwareScrollView.
                          void fetchInvitations(phone);
                        }}
                        placeholder="ex. MARIN42"
                        placeholderTextColor={theme.textMute}
                        autoCapitalize="characters"
                        autoCorrect={false}
                        testID="register-referral"
                      />
                    )}

                    {/* Recherche du parrain dans le carnet du filleul. */}
                    {!sponsorName && (
                      <TouchableOpacity
                        style={styles.contactSearchBtn}
                        onPress={openContactSearch}
                        testID="sponsor-search-contacts"
                      >
                        <Ionicons
                          name={contactSearchOpen ? "chevron-up" : "people-outline"}
                          size={15}
                          color={theme.primary}
                        />
                        <Text style={styles.contactSearchBtnTxt}>
                          {contactSearchOpen ? "Fermer la recherche" : "Rechercher mon parrain dans mes contacts"}
                        </Text>
                      </TouchableOpacity>
                    )}
                    {contactSearchOpen && !sponsorName && (
                      <View ref={sponsorBoxRef} collapsable={false}>
                        <ContactNameSearch
                          onSelect={pickSponsorContact}
                          busy={resolvingSponsor}
                          placeholder="Nom du contact…"
                          testIDPrefix="sponsor-contact"
                        />
                      </View>
                    )}
                  </>
                ) : null}

                <TouchableOpacity
                  style={[styles.primary, busy && { opacity: 0.6 }]}
                  onPress={() => verify()}
                  disabled={busy}
                  testID="login-verify-button"
                >
                  {busy ? (
                    <ActivityIndicator color={theme.bg} />
                  ) : (
                    <Text style={styles.primaryText}>
                      {accountExists ? "Se connecter" : "Créer mon compte"}
                    </Text>
                  )}
                </TouchableOpacity>

                <TouchableOpacity
                  style={styles.resend}
                  onPress={sendCode}
                  disabled={busy || cooldown > 0}
                  testID="login-resend"
                >
                  <Text style={[styles.resendText, cooldown > 0 && { color: theme.textMute }]}>
                    {cooldown > 0
                      ? `Renvoyer le code (${cooldown} s)`
                      : "Je n'ai rien reçu — renvoyer le code"}
                  </Text>
                </TouchableOpacity>
              </View>
            )}
          </KeyboardAwareScrollView>
      </SafeAreaView>
    </ImageBackground>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: theme.bg },
  scroll: { padding: spacing.lg, paddingTop: spacing.xl, gap: spacing.xl },
  brand: { alignItems: "center", marginTop: spacing.lg },
  logo: {
    width: 64, height: 64, borderRadius: radii.lg,
    backgroundColor: theme.primary, alignItems: "center", justifyContent: "center",
    shadowColor: theme.primary, shadowOpacity: 0.5, shadowRadius: 18, shadowOffset: { width: 0, height: 8 },
  },
  title: { color: theme.text, fontSize: 40, fontWeight: "900", marginTop: spacing.md, letterSpacing: -1 },
  tag: { color: theme.textDim, fontSize: 14, marginTop: 4 },
  card: {
    backgroundColor: theme.bg2, padding: spacing.lg, borderRadius: radii.lg,
    borderWidth: 1, borderColor: theme.border, gap: spacing.sm,
  },
  cardTitle: { color: theme.text, fontSize: 20, fontWeight: "900", letterSpacing: -0.5 },
  cardSub: { color: theme.textDim, fontSize: 13, lineHeight: 18 },
  label: { color: theme.textDim, fontWeight: "600", fontSize: 13, marginTop: spacing.sm, textTransform: "uppercase", letterSpacing: 1 },
  phoneRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  phoneCC: {
    paddingHorizontal: 12, paddingVertical: 14, borderRadius: radii.md,
    backgroundColor: theme.bg3, borderWidth: 1, borderColor: theme.border,
  },
  phoneCCText: { color: theme.text, fontWeight: "800", fontSize: 15 },
  input: {
    backgroundColor: theme.bg3, color: theme.text, fontSize: 16,
    paddingVertical: 14, paddingHorizontal: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  otpInput: {
    backgroundColor: theme.bg3, color: theme.text, fontSize: 28, fontWeight: "800",
    letterSpacing: 12, textAlign: "center",
    paddingVertical: 14, paddingHorizontal: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  hint: { color: theme.textMute, fontSize: 11, lineHeight: 15, fontStyle: "italic" },
  modeSwitch: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, marginTop: 14, minHeight: 44,
  },
  modeSwitchText: {
    color: theme.textDim, fontSize: 12.5, fontWeight: "700",
    textDecorationLine: "underline",
  },
  primary: {
    backgroundColor: theme.primary, paddingVertical: 16, borderRadius: radii.md,
    alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 8,
    marginTop: spacing.md, minHeight: 52,
  },
  primaryText: { color: theme.bg, fontWeight: "900", fontSize: 17, letterSpacing: 0.5 },
  backRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 2 },
  backText: { color: theme.textDim, fontSize: 13, fontWeight: "600" },
  mockPill: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    backgroundColor: "rgba(255,209,102,0.15)", paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, borderWidth: 1, borderColor: "#FFD166", marginTop: 4,
  },
  mockText: { color: "#FFD166", fontWeight: "700", fontSize: 12 },
  newBadge: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    backgroundColor: "rgba(72,202,228,0.12)", paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, borderWidth: 1, borderColor: "#48CAE4", marginTop: spacing.sm,
  },
  newBadgeText: { color: "#48CAE4", fontWeight: "700", fontSize: 12 },
  resend: { alignItems: "center", marginTop: spacing.sm, padding: spacing.sm, minHeight: 44, justifyContent: "center" },
  resendText: { color: theme.primary, fontWeight: "700", fontSize: 14 },
  // ── Parrainage à l'inscription (10/07/2026) ──
  invitationsBox: {
    backgroundColor: "rgba(72,202,228,0.08)", borderWidth: 1,
    borderColor: "rgba(72,202,228,0.35)", borderRadius: radii.md,
    padding: spacing.sm, gap: 6, marginBottom: 8,
  },
  invitationsTitle: { color: theme.text, fontSize: 13, fontWeight: "800", lineHeight: 18 },
  invitationRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.bg2, borderRadius: radii.sm,
    paddingHorizontal: 10, paddingVertical: 8, minHeight: 44,
    borderWidth: 1, borderColor: theme.border,
  },
  invitationAvatar: { width: 28, height: 28, borderRadius: 14 },
  invitationAvatarFallback: {
    backgroundColor: theme.primary, alignItems: "center", justifyContent: "center",
  },
  invitationName: { color: theme.text, fontWeight: "800", fontSize: 14, flex: 1 },
  invitationChoose: { color: theme.primary, fontWeight: "900", fontSize: 13 },
  sponsorChosen: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(46,196,182,0.10)", borderWidth: 1,
    borderColor: "rgba(46,196,182,0.4)", borderRadius: radii.md,
    paddingHorizontal: 12, paddingVertical: 10, minHeight: 44,
  },
  sponsorChosenTxt: { color: theme.textDim, fontSize: 13, fontWeight: "700", flex: 1 },
  contactSearchBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, minHeight: 36, marginTop: 2,
  },
  contactSearchBtnTxt: {
    color: theme.primary, fontSize: 13, fontWeight: "700",
    textDecorationLine: "underline",
  },
});
