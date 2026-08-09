/**
 * SignalMar — FICHE « Mon bateau » (28/07/2026, demande armateur).
 * Identité + motorisation du bateau : nom, photo (galerie OU appareil
 * photo), type (moteur/voilier), longueur, largeur, tirant d'air, type de
 * moteur (hors-bord/inboard), nombre de moteurs, marque (tête de liste
 * imposée + recherche par frappe) et puissance par moteur.
 * Persistance locale immédiate (src/lib/boat-info.ts). Le TIRANT D'AIR est
 * partagé avec les réglages de sécurité (boat-settings → moteur de route).
 */
import { useCallback, useMemo, useState } from "react";
import {
  Image,
  Keyboard,
  Linking,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";

import { showToast } from "@/src/components/Toast";
import { filterBrands } from "@/src/lib/engine-brands";
import { toDataUri } from "@/src/lib/image-utils";
import { radii, spacing, theme } from "@/src/lib/theme";
import { useBoatInfo } from "@/src/lib/boat-info";

/** Champ numérique simple (saisie libre, commit au blur). */
function NumField(props: {
  label: string;
  unit: string;
  value: number | null;
  onChange: (v: number | null) => void;
  testID: string;
}) {
  const { label, unit, value, onChange, testID } = props;
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? (value != null ? String(value) : "");
  const commit = useCallback(() => {
    if (text == null) return;
    const parsed = parseFloat(text.replace(",", "."));
    onChange(Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed * 100) / 100 : null);
    setText(null);
    Keyboard.dismiss();
  }, [text, onChange]);
  return (
    <View style={styles.fieldRow}>
      <Text style={styles.fieldLbl}>{label}</Text>
      <View style={styles.fieldBox}>
        <TextInput
          style={styles.fieldInput}
          value={shown}
          onChangeText={setText}
          onBlur={commit}
          onSubmitEditing={commit}
          keyboardType="decimal-pad"
          returnKeyType="done"
          placeholder="—"
          placeholderTextColor={theme.textMute}
          selectTextOnFocus
          testID={testID}
        />
        <Text style={styles.fieldUnit}>{unit}</Text>
      </View>
    </View>
  );
}

export function BoatInfoForm(props: {
  /** Tirant d'air — PARTAGÉ avec les réglages de sécurité (moteur de route). */
  airDraftM: number;
  onAirDraft: (v: number) => void;
}) {
  const { airDraftM, onAirDraft } = props;
  const { loaded, info, setInfo } = useBoatInfo();
  const [brandQuery, setBrandQuery] = useState<string | null>(null);
  const [brandFocus, setBrandFocus] = useState(false);
  const [airText, setAirText] = useState<string | null>(null);

  const suggestions = useMemo(
    () => filterBrands(info.engineType, brandQuery ?? "").slice(0, 8),
    [info.engineType, brandQuery],
  );

  const pickPhoto = useCallback(async (fromCamera: boolean) => {
    try {
      // Permission CONTEXTUELLE (déclenchée par le tap) + redirection
      // Réglages si refus définitif (contrat permissions).
      const perm = fromCamera
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) {
          showToast("error", fromCamera ? "Caméra refusée — ouvrez les Réglages." : "Photos refusées — ouvrez les Réglages.");
          Linking.openSettings().catch(() => {});
        } else {
          showToast("error", fromCamera ? "Accès caméra refusé" : "Accès photos refusé");
        }
        return;
      }
      const r = fromCamera
        ? await ImagePicker.launchCameraAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 1, exif: false })
        : await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 1, exif: false });
      if (r.canceled || !r.assets?.[0]?.uri) return;
      const dataUri = await toDataUri(r.assets[0].uri);
      setInfo({ photo: dataUri });
    } catch {
      showToast("error", "Photo impossible à charger — réessayez.");
    }
  }, [setInfo]);

  if (!loaded) return null;

  const commitAir = () => {
    if (airText == null) return;
    const parsed = parseFloat(airText.replace(",", "."));
    if (Number.isFinite(parsed)) onAirDraft(parsed);
    setAirText(null);
    Keyboard.dismiss();
  };

  return (
    <View style={{ gap: spacing.md }}>
      {/* ── Nom + photo ── */}
      <View style={styles.card}>
        <Text style={styles.fieldLbl}>Nom de mon bateau</Text>
        <TextInput
          style={styles.nameInput}
          value={info.name}
          onChangeText={(t) => setInfo({ name: t })}
          placeholder="Ex. : Morskoul"
          placeholderTextColor={theme.textMute}
          returnKeyType="done"
          testID="boat-name"
        />
        <Text style={[styles.fieldLbl, { marginTop: spacing.sm }]}>Photo du bateau</Text>
        {info.photo ? (
          <Image source={{ uri: info.photo }} style={styles.photo} resizeMode="cover" />
        ) : null}
        <View style={styles.photoBtnRow}>
          <TouchableOpacity style={styles.photoBtn} onPress={() => void pickPhoto(false)} testID="boat-photo-gallery">
            <Ionicons name="images" size={15} color={theme.primary} />
            <Text style={styles.photoBtnTxt}>Galerie</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.photoBtn} onPress={() => void pickPhoto(true)} testID="boat-photo-camera">
            <Ionicons name="camera" size={15} color={theme.primary} />
            <Text style={styles.photoBtnTxt}>Photo</Text>
          </TouchableOpacity>
          {info.photo ? (
            <TouchableOpacity style={styles.photoBtn} onPress={() => setInfo({ photo: "" })} testID="boat-photo-remove">
              <Ionicons name="trash" size={15} color="#FFB4B6" />
              <Text style={[styles.photoBtnTxt, { color: "#FFB4B6" }]}>Retirer</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      </View>

      {/* ── Type + dimensions ── */}
      <View style={styles.card}>
        <Text style={styles.fieldLbl}>Type</Text>
        <View style={styles.segRow}>
          {([["moteur", "Bateau à moteur", "boat"], ["voilier", "Voilier", "flag"]] as const).map(([k, label, icon]) => (
            <TouchableOpacity
              key={k}
              style={[styles.segBtn, info.kind === k && styles.segBtnOn]}
              onPress={() => setInfo({ kind: k })}
              testID={`boat-kind-${k}`}
            >
              <Ionicons name={icon} size={14} color={info.kind === k ? theme.bg : theme.textDim} />
              <Text style={[styles.segTxt, info.kind === k && styles.segTxtOn]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <NumField label="Longueur" unit="m" value={info.lengthM} onChange={(v) => setInfo({ lengthM: v })} testID="boat-length" />
        <NumField label="Largeur" unit="m" value={info.widthM} onChange={(v) => setInfo({ widthM: v })} testID="boat-width" />
        <View style={styles.fieldRow}>
          <Text style={styles.fieldLbl}>Tirant d&apos;air (hauteur)</Text>
          <View style={styles.fieldBox}>
            <TextInput
              style={styles.fieldInput}
              value={airText ?? airDraftM.toFixed(1)}
              onChangeText={setAirText}
              onBlur={commitAir}
              onSubmitEditing={commitAir}
              keyboardType="decimal-pad"
              returnKeyType="done"
              selectTextOnFocus
              testID="boat-info-air-draft"
            />
            <Text style={styles.fieldUnit}>m</Text>
          </View>
        </View>
        <Text style={styles.hint}>
          Le tirant d&apos;air est aussi utilisé par le calcul de route (ponts, câbles).
        </Text>
      </View>

      {/* ── Motorisation ── */}
      <View style={styles.card}>
        <Text style={styles.fieldLbl}>Type de moteur</Text>
        <View style={styles.segRow}>
          {([["outboard", "Hors-bord"], ["inboard", "Inboard"]] as const).map(([k, label]) => (
            <TouchableOpacity
              key={k}
              style={[styles.segBtn, info.engineType === k && styles.segBtnOn]}
              onPress={() => {
                if (info.engineType !== k) setInfo({ engineType: k, engineBrand: "" });
                setBrandQuery(null);
              }}
              testID={`boat-engine-${k}`}
            >
              <Text style={[styles.segTxt, info.engineType === k && styles.segTxtOn]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <View style={styles.fieldRow}>
          <Text style={styles.fieldLbl}>Nombre de moteurs</Text>
          <View style={styles.stepper}>
            <TouchableOpacity
              style={styles.stepBtn}
              onPress={() => setInfo({ engineCount: Math.max(1, info.engineCount - 1) })}
              testID="boat-engines-minus"
            >
              <Ionicons name="remove" size={18} color={theme.text} />
            </TouchableOpacity>
            <Text style={styles.stepVal} testID="boat-engines-count">{info.engineCount}</Text>
            <TouchableOpacity
              style={styles.stepBtn}
              onPress={() => setInfo({ engineCount: Math.min(4, info.engineCount + 1) })}
              testID="boat-engines-plus"
            >
              <Ionicons name="add" size={18} color={theme.text} />
            </TouchableOpacity>
          </View>
        </View>

        <Text style={[styles.fieldLbl, { marginTop: spacing.sm }]}>
          {info.engineCount > 1 ? "Marque des moteurs" : "Marque du moteur"}
        </Text>
        <TextInput
          style={styles.nameInput}
          value={brandQuery ?? info.engineBrand}
          onChangeText={(t) => setBrandQuery(t)}
          onFocus={() => setBrandFocus(true)}
          onBlur={() => setTimeout(() => setBrandFocus(false), 150)}
          placeholder="Tapez le début de la marque…"
          placeholderTextColor={theme.textMute}
          returnKeyType="done"
          testID="boat-engine-brand"
        />
        {(brandFocus || brandQuery != null) && suggestions.length ? (
          <View style={styles.suggBox} testID="boat-brand-suggestions">
            {suggestions.map((b) => (
              <TouchableOpacity
                key={b}
                style={styles.suggRow}
                onPress={() => {
                  setInfo({ engineBrand: b });
                  setBrandQuery(null);
                  setBrandFocus(false);
                  Keyboard.dismiss();
                }}
                testID={`boat-brand-${b}`}
              >
                <Ionicons name="cog" size={13} color={theme.textDim} />
                <Text style={styles.suggTxt}>{b}</Text>
              </TouchableOpacity>
            ))}
          </View>
        ) : null}
        {info.engineBrand && brandQuery == null ? (
          <Text style={styles.hint}>Marque sélectionnée : {info.engineBrand}</Text>
        ) : null}

        {Array.from({ length: info.engineCount }).map((_, i) => (
          <View style={styles.fieldRow} key={i}>
            <Text style={styles.fieldLbl}>
              {info.engineCount > 1 ? `Puissance moteur ${i + 1}` : "Puissance"}
            </Text>
            <View style={styles.fieldBox}>
              <TextInput
                style={[styles.fieldInput, { minWidth: 72, textAlign: "right" }]}
                value={info.enginePowers[i] ?? ""}
                onChangeText={(t) => {
                  const powers = [...info.enginePowers];
                  powers[i] = t;
                  setInfo({ enginePowers: powers });
                }}
                placeholder="Ex. : 150 ch"
                placeholderTextColor={theme.textMute}
                returnKeyType="done"
                testID={`boat-engine-power-${i}`}
              />
            </View>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: spacing.md, borderRadius: radii.md,
    backgroundColor: theme.bg2, borderWidth: 1, borderColor: theme.border,
    gap: 6,
  },
  fieldRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    gap: spacing.sm, marginTop: 4, minHeight: 44,
  },
  fieldLbl: { color: theme.text, fontSize: 13.5, fontWeight: "800", flexShrink: 1 },
  fieldBox: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.sm, paddingHorizontal: 10, paddingVertical: 6,
  },
  fieldInput: {
    color: theme.primary, fontSize: 15, fontWeight: "900",
    minWidth: 48, textAlign: "right", padding: 0,
  },
  fieldUnit: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  nameInput: {
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.sm, paddingHorizontal: 12, paddingVertical: 10,
    color: theme.text, fontSize: 14.5, fontWeight: "700", minHeight: 44,
  },
  photo: { width: "100%", height: 150, borderRadius: radii.sm, backgroundColor: theme.bg },
  photoBtnRow: { flexDirection: "row", gap: spacing.sm },
  photoBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    flex: 1, paddingVertical: 10, borderRadius: radii.sm, minHeight: 44,
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
  },
  photoBtnTxt: { color: theme.text, fontSize: 12.5, fontWeight: "800" },
  segRow: { flexDirection: "row", gap: spacing.sm },
  segBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, borderRadius: radii.sm, minHeight: 44,
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
  },
  segBtnOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  segTxt: { color: theme.textDim, fontSize: 13, fontWeight: "800" },
  segTxtOn: { color: theme.bg },
  stepper: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  stepBtn: {
    width: 40, height: 40, borderRadius: radii.sm, alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
  },
  stepVal: { color: theme.primary, fontSize: 17, fontWeight: "900", minWidth: 24, textAlign: "center" },
  suggBox: {
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.sm, overflow: "hidden",
  },
  suggRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 12, paddingVertical: 10, minHeight: 42,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.border,
  },
  suggTxt: { color: theme.text, fontSize: 13.5, fontWeight: "700" },
  hint: { color: theme.textDim, fontSize: 11, lineHeight: 16 },
});
