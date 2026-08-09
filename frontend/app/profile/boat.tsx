/**
 * SignalMar — Réglages « Mon bateau » (N0, 20/07/2026 — préparation V2).
 *
 * Deux réglages persistés localement (src/lib/boat-settings.ts) :
 *   1. Tirant d'eau (m) — profondeur de la coque sous la flottaison.
 *   2. Marge de sécurité latérale (m, ≥ 50 imposé) — distance mini que la
 *      future route calculée gardera avec les zones trop peu profondes.
 * Le moteur de route V2 (phase N1) lira ces valeurs au moment du calcul.
 */
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Keyboard,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";

import { BoatInfoForm } from "@/src/components/BoatInfoForm";
import { MarineSlider } from "@/src/components/MarineSlider";
import {
  BOAT_CONS_MAX_LH,
  BOAT_CONS_MIN_LH,
  BOAT_CRUISE_MAX_KN,
  BOAT_CRUISE_MIN_KN,
  BOAT_DEPTH_MARGIN_MAX_M,
  BOAT_DEPTH_MARGIN_MIN_M,
  BOAT_DRAFT_MAX_M,
  BOAT_DRAFT_MIN_M,
  BOAT_HEIGHT_MARGIN_MAX_M,
  BOAT_HEIGHT_MARGIN_MIN_M,
  BOAT_MARGIN_MAX_M,
  BOAT_MARGIN_MIN_M,
  clampAirDraft,
  clampCons,
  clampCruise,
  clampDepthMargin,
  clampDraft,
  clampHeightMargin,
  clampMargin,
  useBoatSettings,
} from "@/src/lib/boat-settings";
import { radii, spacing, theme } from "@/src/lib/theme";

/** Champ réutilisé : slider + saisie directe, borné, commit au blur/entrée. */
function BoatField(props: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step: number;
  decimals: number;
  unit: string;
  onChange: (v: number) => void;
  testID: string;
}) {
  const { icon, title, hint, value, min, max, step, decimals, unit, onChange, testID } = props;
  // Texte local pendant la frappe (commit au blur / submit).
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? value.toFixed(decimals);

  const commit = useCallback(() => {
    if (text == null) return;
    const parsed = parseFloat(text.replace(",", "."));
    if (Number.isFinite(parsed)) onChange(parsed);
    setText(null);
    Keyboard.dismiss();
  }, [text, onChange]);

  return (
    <View style={styles.card} testID={`${testID}-card`}>
      <View style={styles.cardHead}>
        <Ionicons name={icon} size={18} color={theme.primary} />
        <Text style={styles.cardTitle}>{title}</Text>
        <View style={styles.valueBox}>
          <TextInput
            style={styles.valueInput}
            value={shown}
            onChangeText={setText}
            onBlur={commit}
            onSubmitEditing={commit}
            keyboardType="decimal-pad"
            returnKeyType="done"
            selectTextOnFocus
            testID={`${testID}-input`}
          />
          <Text style={styles.valueUnit}>{unit}</Text>
        </View>
      </View>
      <MarineSlider
        value={value}
        minimumValue={min}
        maximumValue={max}
        step={step}
        onValueChange={onChange}
        testID={`${testID}-slider`}
      />
      <View style={styles.boundsRow}>
        <Text style={styles.boundTxt}>{min.toFixed(decimals)} {unit}</Text>
        <Text style={styles.boundTxt}>{max.toFixed(decimals)} {unit}</Text>
      </View>
      <Text style={styles.hint}>{hint}</Text>
    </View>
  );
}

export default function BoatSettingsScreen() {
  const router = useRouter();
  // 28/07 (demande armateur) — page en DEUX parties : « Réglages de
  // sécurité » (calcul des routes) et « Mon bateau » (fiche du bateau).
  const [tab, setTab] = useState<"security" | "boat">("security");
  const {
    loaded,
    draftM, setDraftM,
    depthMarginM, setDepthMarginM,
    airDraftM, setAirDraftM,
    heightMarginM, setHeightMarginM,
    marginM, setMarginM,
    marginMode, setMarginMode,
    cruiseKn, setCruiseKn,
    consLh, setConsLh,
  } = useBoatSettings();

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.hBtn} hitSlop={12} testID="boat-back">
          <Ionicons name="chevron-back" size={26} color={theme.text} />
        </TouchableOpacity>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.title}>Mon bateau</Text>
          <Text style={styles.sub}>Sécurité des routes & fiche du bateau</Text>
        </View>
        <View style={styles.hBtn} />
      </View>

      {/* ── 28/07 — deux boutons de section. ── */}
      <View style={styles.tabRow}>
        <TouchableOpacity
          style={[styles.tabBtn, tab === "security" && styles.tabBtnOn]}
          onPress={() => setTab("security")}
          testID="boat-tab-security"
        >
          <Ionicons name="shield-checkmark" size={15} color={tab === "security" ? theme.bg : theme.textDim} />
          <Text style={[styles.tabTxt, tab === "security" && styles.tabTxtOn]}>Réglages de sécurité</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tabBtn, tab === "boat" && styles.tabBtnOn]}
          onPress={() => setTab("boat")}
          testID="boat-tab-info"
        >
          <Ionicons name="boat" size={15} color={tab === "boat" ? theme.bg : theme.textDim} />
          <Text style={[styles.tabTxt, tab === "boat" && styles.tabTxtOn]}>Mon bateau</Text>
        </TouchableOpacity>
      </View>

      {!loaded ? (
        <View style={styles.centered}>
          <ActivityIndicator color={theme.primary} size="large" />
        </View>
      ) : tab === "boat" ? (
        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <BoatInfoForm
            airDraftM={airDraftM}
            onAirDraft={(v) => setAirDraftM(clampAirDraft(v))}
          />
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <BoatField
            icon="boat"
            title="Tirant d'eau"
            hint="Profondeur de la coque sous la ligne de flottaison."
            value={draftM}
            min={BOAT_DRAFT_MIN_M}
            max={BOAT_DRAFT_MAX_M}
            step={0.1}
            decimals={1}
            unit="m"
            onChange={(v) => setDraftM(clampDraft(v))}
            testID="boat-draft"
          />
          <BoatField
            icon="arrow-down"
            title="Marge de sécurité (profondeur)"
            hint="Eau minimale gardée SOUS la quille. La route sûre exigera : profondeur ≥ tirant d'eau + cette marge."
            value={depthMarginM}
            min={BOAT_DEPTH_MARGIN_MIN_M}
            max={BOAT_DEPTH_MARGIN_MAX_M}
            step={0.1}
            decimals={1}
            unit="m"
            onChange={(v) => setDepthMarginM(clampDepthMargin(v))}
            testID="boat-depth-margin"
          />
          <BoatField
            icon="remove-outline"
            title="Marge de sécurité (hauteur)"
            hint="Espace minimal gardé AU-DESSUS du bateau sous les ponts : hauteur libre ≥ tirant d'air + cette marge."
            value={heightMarginM}
            min={BOAT_HEIGHT_MARGIN_MIN_M}
            max={BOAT_HEIGHT_MARGIN_MAX_M}
            step={0.1}
            decimals={1}
            unit="m"
            onChange={(v) => setHeightMarginM(clampHeightMargin(v))}
            testID="boat-height-margin"
          />
          {/* 23/07/2026 (demande armateur) — mode de marge latérale :
              AUTO (défaut) = adaptée à la largeur du chenal par le moteur ;
              MANUEL = valeur fixe envoyée telle quelle. */}
          <View style={styles.card} testID="boat-margin-mode-card">
            <View style={styles.cardHead}>
              <Ionicons name="resize" size={18} color={theme.primary} />
              <Text style={styles.cardTitle}>Marge de sécurité latérale</Text>
            </View>
            <View style={styles.modeRow}>
              <TouchableOpacity
                style={[styles.modeBtn, marginMode === "auto" && styles.modeBtnOn]}
                onPress={() => setMarginMode("auto")}
                testID="boat-margin-mode-auto"
              >
                <Ionicons
                  name="sparkles"
                  size={14}
                  color={marginMode === "auto" ? theme.bg : theme.textDim}
                />
                <Text style={[styles.modeTxt, marginMode === "auto" && styles.modeTxtOn]}>
                  Automatique
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modeBtn, marginMode === "manual" && styles.modeBtnOn]}
                onPress={() => setMarginMode("manual")}
                testID="boat-margin-mode-manual"
              >
                <Ionicons
                  name="options"
                  size={14}
                  color={marginMode === "manual" ? theme.bg : theme.textDim}
                />
                <Text style={[styles.modeTxt, marginMode === "manual" && styles.modeTxtOn]}>
                  Manuelle
                </Text>
              </TouchableOpacity>
            </View>
            <Text style={styles.hint}>
              {marginMode === "auto"
                ? "Recommandé : la marge s'adapte à la largeur du chenal — maximale au large, réduite dans les passes étroites (sécurité minimale 10 m toujours garantie)."
                : "La route garde AU MOINS cette distance avec les zones trop peu profondes ou dangereuses. Si un passage étroit l'exige, elle sera réduite temporairement (annoncé dans la fiche route)."}
            </Text>
          </View>
          {marginMode === "manual" && (
            <BoatField
              icon="resize"
              title="Marge latérale (manuelle)"
              hint="Distance minimale que la route gardera avec les zones trop peu profondes ou dangereuses. Minimum imposé : 10 m."
              value={marginM}
              min={BOAT_MARGIN_MIN_M}
              max={BOAT_MARGIN_MAX_M}
              step={10}
              decimals={0}
              unit="m"
              onChange={(v) => setMarginM(clampMargin(v))}
              testID="boat-margin"
            />
          )}
          {/* 22/07 (GO armateur) — croisière : durée + carburant des routes. */}
          <BoatField
            icon="speedometer"
            title="Vitesse de croisière"
            hint="Vitesse moyenne au moteur en croisière — utilisée pour estimer la durée et le carburant d'une route."
            value={cruiseKn}
            min={BOAT_CRUISE_MIN_KN}
            max={BOAT_CRUISE_MAX_KN}
            step={0.5}
            decimals={1}
            unit="nd"
            onChange={(v) => setCruiseKn(clampCruise(v))}
            testID="boat-cruise"
          />
          <BoatField
            icon="flame"
            title="Consommation en croisière"
            hint="Consommation moteur à la vitesse de croisière. 0 = non renseignée (pas d'estimation carburant). La fiche route affichera la conso estimée + la quantité à prévoir (pied de pilote +30 %)."
            value={consLh}
            min={BOAT_CONS_MIN_LH}
            max={BOAT_CONS_MAX_LH}
            step={0.5}
            decimals={1}
            unit="L/h"
            onChange={(v) => setConsLh(clampCons(v))}
            testID="boat-cons"
          />
          <View style={styles.infoBanner}>
            <Ionicons name="information-circle" size={16} color={theme.primary} />
            <Text style={styles.infoTxt}>
              Ces réglages préparent le mode Navigation V2 (routes sûres type
              Navionics). Les profondeurs utilisées seront référencées au zéro
              hydrographique (marée basse) — calcul volontairement conservateur.
            </Text>
          </View>
        </ScrollView>
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
  hBtn: { padding: 4, minWidth: 36, alignItems: "center" },
  title: { color: theme.text, fontSize: 17, fontWeight: "800" },
  sub: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center" },
  // 28/07 — sélecteur de section (sécurité / fiche bateau).
  tabRow: {
    flexDirection: "row", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  tabBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, borderRadius: radii.sm, minHeight: 44,
    backgroundColor: theme.bg2, borderWidth: 1, borderColor: theme.border,
  },
  tabBtnOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  tabTxt: { color: theme.textDim, fontSize: 12.5, fontWeight: "800" },
  tabTxtOn: { color: theme.bg },
  body: { padding: spacing.md, gap: spacing.md, paddingBottom: 40 },
  card: {
    padding: spacing.md, borderRadius: radii.md,
    backgroundColor: theme.bg2, borderWidth: 1, borderColor: theme.border,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: "800", flex: 1 },
  valueBox: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.sm, paddingHorizontal: 10, paddingVertical: 6,
  },
  valueInput: {
    color: theme.primary, fontSize: 16, fontWeight: "900",
    minWidth: 44, textAlign: "right", padding: 0,
  },
  valueUnit: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  boundsRow: { flexDirection: "row", justifyContent: "space-between", marginTop: -6 },
  boundTxt: { color: theme.textMute, fontSize: 10, fontWeight: "700" },
  hint: { color: theme.textDim, fontSize: 11, lineHeight: 16, marginTop: spacing.sm },
  modeRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  modeBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, borderRadius: radii.sm,
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
    minHeight: 44,
  },
  modeBtnOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  modeTxt: { color: theme.textDim, fontSize: 13, fontWeight: "800" },
  modeTxtOn: { color: theme.bg },
  infoBanner: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    padding: 10, borderRadius: radii.md,
    backgroundColor: "rgba(46,196,182,0.10)",
    borderColor: "rgba(46,196,182,0.35)", borderWidth: 1,
  },
  infoTxt: { color: theme.text, fontSize: 11, flex: 1, lineHeight: 16 },
});
