// SignalMar — Panneau « Zone de veille & alertes » (réutilisable).
//
// Fusion 10/07/2026 : l'ancien « rayon d'alerte » sonore et le « rayon de
// notifications » push deviennent UNE seule notion — la Zone de veille —
// réglée distinctement pour les 2 modes :
//   • Zone de veille VIGIE      → rayon du radar 360° (diamètre = 2 × zone)
//     + rayon des notifications push (notify_radius_km synchronisé backend).
//   • Zone de veille NAVIGATION → longueur du cône devant le bateau.
//
// Variantes :
//   • "quick" : zones Vigie/Nav + types de notification (+ bouton « Tous les
//     paramètres » si onOpenFullSettings est fourni). Utilisée dans la popup
//     engrenage de la carte et sous le bouton « Stopper l'alerte ».
//   • "full"  : quick + répétitions + voix & vibration. Utilisée dans la
//     page Paramètres.
//
// Les « Types de notification » sont une liste UNIQUE : couper un type coupe
// à la fois l'alerte sonore locale (voiceSettings.mutedTypes) ET les push
// backend (muted_types) — liste d'exclusion, nouveaux types actifs par défaut.

import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from "react-native";
import Slider from "@react-native-community/slider";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { theme } from "@/src/lib/theme";
import { REPORT_TYPES } from "@/src/lib/report-types";
import { useVoiceSettings } from "@/src/lib/voice-settings";
import { NM_IN_M } from "@/src/lib/voice-alerts";
import { ALERT_SOUNDS, previewAlertSound, type AlertSoundId } from "@/src/lib/alert-sound";
import { showToast } from "@/src/components/Toast";

// ── Échelles logarithmiques par zone, aimant sur 1 NM ──────────────────────
// Vigie      : 200 m → 20 km (slider et saisie).
// Navigation : 200 m → 500 km au slider, saisie manuelle jusqu'à 1000 km.
const KM_MIN = 0.2;
const SNAP_KM = NM_IN_M / 1000; // 1 NM
const SNAP_HALF_WIDTH = 0.035;

const VIGIE_SLIDER_MAX_KM = 20;
const VIGIE_INPUT_MAX_KM = 20;
// Exportés (15/07/2026) : mêmes bornes dans le popup cône de la carte.
export const NAV_SLIDER_MAX_KM = 500;
export const NAV_INPUT_MAX_KM = 1000;

function kmToPos(km: number, maxKm: number): number {
  const k = Math.max(KM_MIN, Math.min(maxKm, km || KM_MIN));
  return Math.log(k / KM_MIN) / Math.log(maxKm / KM_MIN);
}
function posToKm(pos: number, maxKm: number): number {
  return KM_MIN * Math.exp(Math.max(0, Math.min(1, pos)) * Math.log(maxKm / KM_MIN));
}
function snapPos(pos: number, maxKm: number): number {
  const target = kmToPos(SNAP_KM, maxKm);
  return Math.abs(pos - target) < SNAP_HALF_WIDTH ? target : pos;
}
function roundKm(km: number): number {
  // Granularité 0,1 km sous 100 km (préserve les valeurs NM exactes,
  // ex : 5 NM = 9,26 → 9,3 km), 1 km au-delà.
  if (km < 100) return Math.round(km * 10) / 10;
  return Math.round(km);
}
function fmtKm(km: number): string {
  if (km < 1) return `${Math.round(km * 1000)} m`;
  const v = km < 10 ? km.toFixed(1).replace(/\.0$/, "") : String(Math.round(km));
  return `${v} km`;
}
/** Valeur numérique (km) pour le champ de saisie — sans unité. */
function fmtInputKm(km: number): string {
  return km < 10 ? String(Math.round(km * 10) / 10) : String(Math.round(km));
}
function fmtNm(km: number): string {
  const nm = (km * 1000) / NM_IN_M;
  if (nm >= 10) return String(Math.round(nm));
  return nm.toFixed(1).replace(/\.0$/, "");
}

// 13/07/2026 (demande user) : 0 à 2 répétitions maximum.
const REPETITION_CHOICES = [0, 1, 2];

/** Slider + saisie manuelle d'une zone de veille, affichage km/m ET NM.
 *  Exporté (15/07/2026) : réutilisé par le popup « Cône Navigation » de la
 *  carte pour régler la distance du cône sans passer par la page Réglages. */
export function ZoneField({
  icon,
  label,
  hint,
  valueM,
  onCommitM,
  testIDPrefix,
  showHint,
  sliderMaxKm,
  inputMaxKm,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  hint: string;
  valueM: number;
  onCommitM: (m: number) => void;
  testIDPrefix: string;
  showHint: boolean;
  /** Borne haute du slider (échelle log 200 m → sliderMaxKm). */
  sliderMaxKm: number;
  /** Borne haute de la saisie manuelle (peut dépasser le slider). */
  inputMaxKm: number;
}) {
  const currentKm = roundKm((valueM || SNAP_KM * 1000) / 1000);
  const [pendingKm, setPendingKm] = useState<number>(currentKm);
  const [inputText, setInputText] = useState<string>(fmtInputKm(currentKm));

  useEffect(() => {
    setPendingKm(currentKm);
    setInputText(fmtInputKm(currentKm));
  }, [currentKm]);

  const commitKm = useCallback((raw: number) => {
    const clamped = Math.max(KM_MIN, Math.min(inputMaxKm, raw));
    const rounded = roundKm(clamped);
    setPendingKm(rounded);
    setInputText(fmtInputKm(rounded));
    onCommitM(Math.round(rounded * 1000));
  }, [onCommitM, inputMaxKm]);

  const applyText = useCallback(() => {
    const raw = parseFloat(inputText.replace(",", "."));
    if (!Number.isFinite(raw)) {
      setInputText(fmtInputKm(pendingKm));
      return;
    }
    commitKm(raw);
  }, [inputText, pendingKm, commitKm]);

  return (
    <View>
      <View style={styles.headerRow}>
        <View style={styles.zoneLabelRow}>
          <Ionicons name={icon} size={14} color={theme.primary} />
          {/* flexShrink → le libellé passe sur 2 lignes au lieu de chevaucher
              la valeur (bug signalé 11/07 : « Navigation6.5 km »). */}
          <Text style={[styles.label, { flexShrink: 1 }]}>{label}</Text>
        </View>
        <Text style={styles.valueText}>
          <Text style={{ color: theme.primary }}>{fmtKm(pendingKm)}</Text>
          <Text style={{ color: theme.textDim }}> · </Text>
          <Text style={{ color: "#F4A261" }}>{fmtNm(pendingKm)}</Text>
          <Text style={{ color: theme.textDim }}> NM</Text>
        </Text>
      </View>
      {showHint && <Text style={styles.hint}>{hint}</Text>}
      <View style={styles.sliderWrap}>
        <Slider
          style={styles.slider}
          minimumValue={0}
          maximumValue={1}
          value={kmToPos(Math.min(pendingKm, sliderMaxKm), sliderMaxKm)}
          minimumTrackTintColor={theme.primary}
          maximumTrackTintColor={theme.border}
          thumbTintColor={theme.primary}
          onValueChange={(v) => {
            const km = roundKm(posToKm(snapPos(v, sliderMaxKm), sliderMaxKm));
            setPendingKm(km);
            setInputText(fmtInputKm(km));
          }}
          onSlidingComplete={(v) => commitKm(posToKm(snapPos(v, sliderMaxKm), sliderMaxKm))}
        />
        <View pointerEvents="none" style={[styles.snapPin, { left: `${kmToPos(SNAP_KM, sliderMaxKm) * 100}%` }]}>
          <View style={styles.snapDot} />
          <Text style={styles.snapLabel}>1 NM</Text>
        </View>
      </View>
      <View style={styles.scaleRow}>
        <Text style={styles.scaleTxt}>200 m</Text>
        <Text style={styles.scaleTxt}>{sliderMaxKm} km</Text>
      </View>
      <View style={styles.manualRow}>
        <Text style={styles.manualLabel}>Valeur précise :</Text>
        <TextInput
          style={styles.manualInput}
          value={inputText}
          onChangeText={setInputText}
          onBlur={applyText}
          onSubmitEditing={applyText}
          keyboardType="decimal-pad"
          inputMode="decimal"
          returnKeyType="done"
          selectTextOnFocus
          placeholder="km"
          placeholderTextColor={theme.textDim}
          maxLength={6}
          testID={`${testIDPrefix}-input`}
        />
        <Text style={styles.manualUnit}>km (max {inputMaxKm})</Text>
        <Text style={styles.manualNm}>= {fmtNm(pendingKm)} NM</Text>
      </View>
    </View>
  );
}

export function AlertSettingsPanel({
  variant = "full",
  mode = "vigie",
  onOpenFullSettings,
  highlightAutoSwitch = false,
}: {
  variant?: "quick" | "full" | "alert";
  /** Variante "alert" (popup d'alerte active, 12/07/2026) : n'affiche QUE le
   *  périmètre du mode courant + le bouton vers la page Réglages. */
  mode?: "vigie" | "nav";
  onOpenFullSettings?: () => void;
  /** Deep-link depuis la bannière « Bascule auto » de la carte : met en
   *  évidence la rangée de bascule auto Vigie ⇄ Navigation. */
  highlightAutoSwitch?: boolean;
}) {
  const { settings, update } = useVoiceSettings();
  const full = variant === "full";

  // ── Zone Vigie : aussi synchronisée côté backend (rayon des push). ──
  const commitVigie = useCallback((m: number) => {
    void update({ zoneVigieM: m });
    api.updatePreferences({ notify_radius_km: Math.max(1, Math.round(m / 1000)) })
      .catch(() => { /* mode démo / hors-ligne — le réglage local suffit */ });
  }, [update]);

  const commitNav = useCallback((m: number) => {
    void update({ zoneNavM: m });
  }, [update]);

  // ── Types de notification : liste UNIQUE son + push. ──
  const mutedTypes = settings.mutedTypes ?? [];
  const toggleType = useCallback((id: string) => {
    const cur = settings.mutedTypes ?? [];
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    void update({ mutedTypes: next });
    api.updatePreferences({ muted_types: next })
      .catch(() => { /* mode démo / hors-ligne */ });
  }, [settings.mutedTypes, update]);

  const reps = Math.min(2, settings.repetitions ?? 2);

  // ── Règle de sécurité (rétablie 11/07/2026) : au moins UN canal d'alerte
  // doit rester actif — le vibreur est le minimum incompressible.
  //   • Couper la voix quand le vibreur est déjà coupé → on réactive le
  //     vibreur automatiquement (avec message).
  //   • Couper le vibreur quand la voix est déjà coupée → REFUSÉ (message).
  const toggleVoice = useCallback((v: boolean) => {
    if (!v && !settings.vibrationEnabled) {
      void update({ enabled: false, vibrationEnabled: true });
      showToast("info", "Vibreur réactivé — au moins un canal d'alerte doit rester actif pour votre sécurité.");
      return;
    }
    void update({ enabled: v });
  }, [settings.vibrationEnabled, update]);

  const toggleVibration = useCallback((v: boolean) => {
    if (!v && !settings.enabled) {
      showToast("error", "Impossible : les alertes vocales sont déjà coupées — le vibreur doit rester actif pour votre sécurité en mer.");
      return;
    }
    void update({ vibrationEnabled: v });
  }, [settings.enabled, update]);

  // ── Variante "alert" (12/07/2026) : périmètre du mode actif + accès à la
  // page Réglages — utilisée REPLIÉE/dépliée dans la popup d'alerte active.
  if (variant === "alert") {
    const isNav = mode === "nav";
    return (
      <View style={styles.root}>
        <ZoneField
          icon={isNav ? "navigate" : "radio"}
          label={isNav ? "Zone de veille — Navigation" : "Zone de veille — Vigie"}
          hint={isNav
            ? "Longueur du cône de surveillance devant votre bateau."
            : "Rayon surveillé à 360° autour de vous."}
          valueM={isNav ? (settings.zoneNavM ?? 5 * NM_IN_M) : (settings.zoneVigieM ?? 2 * NM_IN_M)}
          onCommitM={isNav ? commitNav : commitVigie}
          testIDPrefix={isNav ? "zone-nav" : "zone-vigie"}
          showHint={false}
          sliderMaxKm={isNav ? NAV_SLIDER_MAX_KM : VIGIE_SLIDER_MAX_KM}
          inputMaxKm={isNav ? NAV_INPUT_MAX_KM : VIGIE_INPUT_MAX_KM}
        />
        {/* 15/07/2026 (demande user) — réglage des répétitions directement
            dans le bandeau d'alerte, pour la Vigie ET la Navigation. */}
        <Text style={[styles.label, styles.sectionGap]}>Répétitions de l&apos;alerte</Text>
        <View style={styles.repsRow}>
          {REPETITION_CHOICES.map((n) => (
            <TouchableOpacity
              key={n}
              style={[styles.repChip, reps === n && styles.repChipOn]}
              onPress={() => { void update({ repetitions: n }); }}
              testID={`alert-banner-reps-${n}`}
            >
              <Text style={[styles.repChipText, reps === n && styles.repChipTextOn]}>{n}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <Text style={styles.hint}>
          {reps === 0
            ? "Aucun rappel — l'alerte n'est présentée qu'une fois."
            : `1 alerte + ${reps} rappel${reps > 1 ? "s" : ""} (son + vibration).`}
        </Text>
        {onOpenFullSettings && (
          <TouchableOpacity
            style={styles.allSettingsBtn}
            onPress={onOpenFullSettings}
            activeOpacity={0.85}
            testID="alert-open-full-settings"
          >
            <Ionicons name="settings-outline" size={16} color={theme.primary} />
            <Text style={styles.allSettingsText}>Tous les paramètres</Text>
            <Ionicons name="chevron-forward" size={16} color={theme.primary} />
          </TouchableOpacity>
        )}
      </View>
    );
  }

  return (
    <View style={styles.root}>
      {/* ── 0. Bascule AUTO Vigie ⇄ Navigation (11/07/2026) ── */}
      {full && (
        <View
          style={[styles.autoSwitchRow, highlightAutoSwitch && styles.autoSwitchRowHi]}
          testID="alert-auto-switch-row"
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.switchLabel}>Bascule auto Vigie ⇄ Navigation</Text>
            <Text style={styles.hint}>
              Passe en Navigation dès que le bateau avance (≥ 3 km/h pendant 5 s)
              et revient en Vigie à l{"\u2019"}arrêt.
            </Text>
          </View>
          <Switch
            value={settings.autoModeSwitch !== false}
            onValueChange={(v) => { void update({ autoModeSwitch: v }); }}
            trackColor={{ false: theme.border, true: theme.primary }}
            thumbColor="#fff"
            testID="alert-auto-mode-switch"
          />
        </View>
      )}

      {/* ── 1. Zone de veille — Vigie & Navigation ── */}
      <ZoneField
        icon="radio"
        label="Zone de veille — Vigie"
        hint="Rayon surveillé à 360° autour de vous (le radar affiche exactement cette zone)."
        valueM={settings.zoneVigieM ?? 2 * NM_IN_M}
        onCommitM={commitVigie}
        testIDPrefix="zone-vigie"
        showHint={full}
        sliderMaxKm={VIGIE_SLIDER_MAX_KM}
        inputMaxKm={VIGIE_INPUT_MAX_KM}
      />
      <View style={styles.zoneGap} />
      <ZoneField
        icon="navigate"
        label="Zone de veille — Navigation"
        hint="Longueur du cône de surveillance devant votre bateau."
        valueM={settings.zoneNavM ?? 5 * NM_IN_M}
        onCommitM={commitNav}
        testIDPrefix="zone-nav"
        showHint={full}
        sliderMaxKm={NAV_SLIDER_MAX_KM}
        inputMaxKm={NAV_INPUT_MAX_KM}
      />

      {/* ── 2. Types de notification (liste unique son + push) ── */}
      <Text style={[styles.label, styles.sectionGap]}>Types de notification</Text>
      {full && (
        <Text style={styles.hint}>
          Touchez un type pour le désactiver (alertes sonores ET notifications).
          Les nouveaux types de signalement sont actifs par défaut.
        </Text>
      )}
      <View style={styles.chipsRow}>
        {REPORT_TYPES.map((t) => {
          const muted = mutedTypes.includes(t.id);
          return (
            <TouchableOpacity
              key={t.id}
              style={[
                styles.chip,
                muted
                  ? { backgroundColor: theme.bg3, borderColor: theme.textMute, opacity: 0.55 }
                  : { borderColor: t.color, backgroundColor: "rgba(72,202,228,0.05)" },
              ]}
              onPress={() => toggleType(t.id)}
              testID={`alert-type-${t.id}`}
            >
              <Ionicons
                name={muted ? "notifications-off" : "notifications"}
                size={13}
                color={muted ? theme.textMute : t.color}
              />
              <Text style={[styles.chipText, muted && { color: theme.textMute, textDecorationLine: "line-through" }]}>
                {t.short}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {full && (
        <>
          {/* ── 3. Répétitions (0-2, 13/07/2026) — confirmation explicite du
              nombre TOTAL de diffusions (1 annonce + N répétitions). ── */}
          <Text style={[styles.label, styles.sectionGap]}>Nombre de répétition des alertes</Text>
          <View style={styles.repsRow}>
            {REPETITION_CHOICES.map((n) => (
              <TouchableOpacity
                key={n}
                style={[styles.repChip, reps === n && styles.repChipOn]}
                onPress={() => {
                  void update({ repetitions: n });
                  const total = n + 1;
                  showToast(
                    "info",
                    n === 0
                      ? "Aucun rappel : l'alerte sera présentée 1 seule fois."
                      : `L'alerte sera présentée ${total} fois au total (1 alerte + ${n} rappel${n > 1 ? "s" : ""} — son + vibration).`,
                  );
                }}
                testID={`alert-reps-${n}`}
              >
                <Text style={[styles.repChipText, reps === n && styles.repChipTextOn]}>{n}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={styles.hint}>
            {reps === 0
              ? "Aucun rappel — l'alerte s'éteint après la première notification."
              : `Présentée ${reps + 1} fois au total : 1 alerte + ${reps} rappel${reps > 1 ? "s" : ""} (son + vibration) toutes les 15 s si non interrompue, puis extinction automatique.`}
          </Text>

          {/* ── 4. Alertes & vibration (14/07/2026 — audio SUPPRIMÉ sur
              décision armateur : alerte = popup + vibration). ── */}
          <Text style={[styles.label, styles.sectionGap]}>Alertes &amp; vibration</Text>
          <View style={styles.switchRow}>
            <Text style={styles.switchLabel}>Alertes sonores activées</Text>
            <Switch
              value={settings.enabled}
              onValueChange={toggleVoice}
              trackColor={{ false: theme.border, true: theme.primary }}
              thumbColor="#fff"
              testID="alert-voice-enabled"
            />
          </View>
          <View style={styles.switchRow}>
            <Text style={styles.switchLabel}>Vibration</Text>
            <Switch
              value={settings.vibrationEnabled}
              onValueChange={toggleVibration}
              trackColor={{ false: theme.border, true: theme.primary }}
              thumbColor="#fff"
              testID="alert-vibration-enabled"
            />
          </View>

          {/* ── 5. Son d'alerte (14/07/2026) — CHOIX du fichier uniquement,
              le code de DÉCLENCHEMENT est FIGÉ (exigence armateur). ── */}
          <Text style={[styles.label, styles.sectionGap]}>Son d&apos;alerte</Text>
          <View style={styles.soundRow}>
            {ALERT_SOUNDS.map((snd) => {
              const on = (settings.alertSound ?? "horn") === snd.id;
              return (
                <TouchableOpacity
                  key={snd.id}
                  style={[styles.soundChip, on && styles.soundChipOn]}
                  onPress={() => {
                    void update({ alertSound: snd.id });
                    previewAlertSound(snd.id);
                  }}
                  activeOpacity={0.85}
                  testID={`alert-sound-${snd.id}`}
                >
                  <Ionicons
                    name={snd.id === "horn" ? "megaphone-outline" : "radio-outline"}
                    size={15}
                    color={on ? theme.primary : theme.textMute}
                  />
                  <Text style={[styles.soundChipText, on && styles.soundChipTextOn]}>{snd.label}</Text>
                </TouchableOpacity>
              );
            })}
            <TouchableOpacity
              style={styles.listenBtn}
              onPress={() => previewAlertSound((settings.alertSound ?? "horn") as AlertSoundId)}
              activeOpacity={0.85}
              testID="alert-sound-test"
            >
              <Ionicons name="play" size={14} color={theme.primary} />
              <Text style={styles.listenText}>Écouter</Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.hint}>
            Le son choisi est joué à chaque alerte (toucher un son = pré-écoute).
          </Text>
        </>
      )}

      {/* ── Accès à la page dédiée « Tous les paramètres » ── */}
      {onOpenFullSettings && (
        <TouchableOpacity
          style={styles.allSettingsBtn}
          onPress={onOpenFullSettings}
          activeOpacity={0.85}
          testID="alert-open-full-settings"
        >
          <Ionicons name="settings-outline" size={16} color={theme.primary} />
          <Text style={styles.allSettingsText}>Tous les paramètres</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.primary} />
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { gap: 4 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  zoneLabelRow: { flexDirection: "row", alignItems: "center", gap: 6, flex: 1, flexShrink: 1 },
  zoneGap: { height: 14 },
  label: { color: theme.text, fontWeight: "800", fontSize: 13 },
  sectionGap: { marginTop: 14 },
  valueText: { fontWeight: "900", fontSize: 15, flexShrink: 0 },
  sliderWrap: { position: "relative", marginTop: 2 },
  // 16/07/2026 (retour terrain « difficile à régler en mer ») — hauteur du
  // slider portée de 34 → 56 px : la zone tactile s'agrandit d'autant sans
  // impacter la position visuelle du track (Slider RN Community centre le
  // track dans son container).
  slider: { width: "100%", height: 56 },
  snapPin: { position: "absolute", top: -4, alignItems: "center", marginLeft: -10, width: 26 },
  snapDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: theme.primary, opacity: 0.8 },
  snapLabel: { color: theme.textDim, fontSize: 8, fontWeight: "700", marginTop: 1 },
  scaleRow: { flexDirection: "row", justifyContent: "space-between", marginTop: -4 },
  scaleTxt: { color: theme.textDim, fontSize: 10 },
  manualRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  manualLabel: { color: theme.textMute, fontSize: 12 },
  manualInput: {
    backgroundColor: theme.bg3, borderWidth: 1, borderColor: theme.border,
    borderRadius: 8, color: theme.text, fontWeight: "800", fontSize: 14,
    paddingHorizontal: 10, paddingVertical: 6, minWidth: 64, textAlign: "center",
  },
  manualUnit: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  manualNm: { color: "#F4A261", fontSize: 12, fontWeight: "700", marginLeft: "auto" },
  hint: { color: theme.textDim, fontSize: 11, lineHeight: 15, marginTop: 4 },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderRadius: 16, paddingHorizontal: 10, paddingVertical: 7,
    minHeight: 34,
  },
  chipText: { color: theme.text, fontSize: 12, fontWeight: "700" },
  repsRow: { flexDirection: "row", gap: 10, marginTop: 8 },
  repChip: {
    width: 44, height: 40, borderRadius: 10, alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg3,
  },
  repChipOn: { borderColor: theme.primary, backgroundColor: "rgba(72,202,228,0.15)" },
  repChipText: { color: theme.textMute, fontWeight: "800", fontSize: 16 },
  repChipTextOn: { color: theme.primary },
  switchRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: 8, minHeight: 36,
  },
  autoSwitchRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 10, marginBottom: 14, borderRadius: 10,
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg3,
  },
  autoSwitchRowHi: {
    borderColor: "#F4A261", backgroundColor: "rgba(244,162,97,0.10)",
  },
  switchLabel: { color: theme.text, fontSize: 13, fontWeight: "600" },
  soundRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8, marginTop: 8 },
  soundChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg3,
    borderRadius: 10, paddingHorizontal: 12, minHeight: 40,
  },
  soundChipOn: { borderColor: theme.primary, backgroundColor: "rgba(72,202,228,0.15)" },
  soundChipText: { color: theme.textMute, fontWeight: "800", fontSize: 13 },
  soundChipTextOn: { color: theme.primary },
  listenBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: theme.primary, borderRadius: 10,
    paddingHorizontal: 12, minHeight: 40, marginLeft: "auto",
  },
  listenText: { color: theme.primary, fontWeight: "800", fontSize: 12 },
  allSettingsBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: 16, minHeight: 46, borderRadius: 12,
    borderWidth: 1, borderColor: theme.primary, backgroundColor: "rgba(72,202,228,0.08)",
  },
  allSettingsText: { color: theme.primary, fontSize: 14, fontWeight: "800" },
});
