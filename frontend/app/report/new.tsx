import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  LayoutChangeEvent,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";

import { toDataUri } from "@/src/lib/image-utils";
import { logger } from "@/src/lib/logger";
import { api } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import {
  REPORT_TYPES,
  TYPE_BY_ID,
  type ReportTypeId,
  ANIMAL_HEALTH_STATES,
  ROCHE_VARIANTS,
  MARINE_MAMMALS,
  INJURY_TYPES,
} from "@/src/lib/report-types";
import {
  AUTHORITY_SUBTYPES,
  AUTHORITY_ACTIVITIES,
  SECOURS_SUBTYPES,
  SECOURS_ACTIVITIES,
  type AuthoritySubtype,
  type AuthorityActivity,
} from "@/src/lib/authorities";
import { theme, spacing, radii } from "@/src/lib/theme";
import { toDecimal } from "@/src/lib/coords";
import { showToast } from "@/src/components/Toast";
import { markReportCreated } from "@/src/lib/last-created";

export default function NewReport() {
  const router = useRouter();
  const params = useLocalSearchParams<{ lat?: string; lng?: string }>();
  const { refresh: refreshAuthUser } = useAuth();

  const [selected, setSelected] = useState<ReportTypeId | null>(null);
  const [description, setDescription] = useState("");
  const [photos, setPhotos] = useState<string[]>([]);
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Authorities-only fields — V1.2: no default value, force explicit tap.
  const [subtype, setSubtype] = useState<AuthoritySubtype | null>(null);
  const [activity, setActivity] = useState<AuthorityActivity | null>(null);
  const [heading, setHeading] = useState("");
  const [speed, setSpeed] = useState("");

  // Phase B — subtype + extras for non-authority types (animal_marin,
  // obstacle_nav, pollution, autre). Keeping a separate string state so the
  // typed AuthoritySubtype above stays narrow.
  const [subOther, setSubOther] = useState<string>("");
  const [health, setHealth] = useState<string>("");
  const [species, setSpecies] = useState<string>("");
  const [injuryType, setInjuryType] = useState<string>("");
  const [rocheVariant, setRocheVariant] = useState<string>("couvrante_decouvrante");
  // 24/07/2026 (demande armateur) — « Autre » : curseur placé directement
  // dans le champ commentaire.
  const commentRef = useRef<TextInput>(null);

  // V1.2 — auto-scroll helper: each section registers its own Y position via
  // onLayout so we can smoothly bring the next question into view as the user
  // makes choices. Refs live in .current to avoid unnecessary re-renders.
  const scrollRef = useRef<ScrollView>(null);
  const sectionYs = useRef<Record<string, number>>({});
  const onSectionLayout = (key: string) => (e: LayoutChangeEvent) => {
    sectionYs.current[key] = e.nativeEvent.layout.y;
  };
  function scrollToSection(key: string, offset: number = 12) {
    // Defer to next tick so the target section has been laid out at least
    // once after the state change that triggered this call.
    setTimeout(() => {
      const y = sectionYs.current[key];
      if (typeof y === "number") {
        scrollRef.current?.scrollTo({ y: Math.max(0, y - offset), animated: true });
      }
    }, 120);
  }

  // Reset all subtype/extras pickers when switching the main category.
  const otherSubtypes = useMemo(() => {
    if (!selected || selected === "autorites" || selected === "secours") return [] as { id: string; label: string }[];
    return (TYPE_BY_ID[selected]?.subtypes ?? []).map((s) => ({ id: s.id, label: s.label }));
  }, [selected]);

  useEffect(() => {
    if (!selected) return;
    if (selected === "autorites" || selected === "secours") return;
    // V1.2 — no auto-selection: the user must explicitly pick a sub-type.
    // 24/07/2026 (demande armateur) — EXCEPTION « Autre » : son unique
    // sous-type « Description libre » est pré-sélectionné et le curseur va
    // directement dans le champ commentaire.
    setSubOther(selected === "autre" ? "autre_libre" : "");
    setHealth("");
    setSpecies("");
    setInjuryType("");
    setRocheVariant("couvrante_decouvrante");
  }, [selected]);

  useEffect(() => {
    const lat = params.lat ? Number(params.lat) : null;
    const lng = params.lng ? Number(params.lng) : null;
    if (lat != null && lng != null && !Number.isNaN(lat) && !Number.isNaN(lng)) {
      setCoords({ lat, lng });
    } else {
      (async () => {
        try {
          const perm = await Location.requestForegroundPermissionsAsync();
          if (perm.status === "granted") {
            const pos = await Location.getCurrentPositionAsync({
              accuracy: Location.Accuracy.Balanced,
            });
            setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
          }
        } catch {
          /* ignore */
        }
      })();
    }
  }, [params.lat, params.lng]);

  // FIX crash 11/07 : ne JAMAIS demander base64 au picker (photo pleine
  // résolution → OOM Android). On redimensionne d'abord (image-utils).
  async function pickPhoto() {
    if (photos.length >= 3) {
      showToast("info", "3 photos maximum");
      return;
    }
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) {
          showToast("error", "Accès Photos refusé. Ouvrez les Réglages pour autoriser.");
        } else {
          showToast("error", "Accès photos refusé");
        }
        return;
      }
      await logger.breadcrumb("report", "photo_step: ouverture galerie");
      const r = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 1,
        allowsEditing: false,
        exif: false,
      });
      if (r.canceled) { void logger.breadcrumb("report", "photo_step: galerie annulée"); return; }
      const asset = r.assets?.[0];
      if (!asset?.uri) return;
      await logger.breadcrumb("report", "photo_step: galerie retournée", {
        w: asset.width, h: asset.height, fileSize: asset.fileSize,
      });
      const dataUri = await toDataUri(asset.uri);
      await logger.breadcrumb("report", "photo_step: décodage OK", { kb: Math.round(dataUri.length / 1024) });
      setPhotos((p) => [...p, dataUri]);
    } catch (e) {
      logger.error("app", "photo_pick_failed", { error: (e as Error).message });
      showToast("error", "Photo impossible à charger — réessayez.");
    }
  }

  // Phase D — capture from the device camera (in addition to gallery).
  async function takePhoto() {
    if (photos.length >= 3) {
      showToast("info", "3 photos maximum");
      return;
    }
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) {
          showToast("error", "Caméra refusée. Activez-la dans les Réglages.");
        } else {
          showToast("error", "Caméra refusée");
        }
        return;
      }
      await logger.breadcrumb("report", "photo_step: ouverture caméra");
      const r = await ImagePicker.launchCameraAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 1,
        allowsEditing: false,
        exif: false,
      });
      if (r.canceled) { void logger.breadcrumb("report", "photo_step: caméra annulée"); return; }
      const asset = r.assets?.[0];
      if (!asset?.uri) return;
      await logger.breadcrumb("report", "photo_step: caméra retournée", {
        w: asset.width, h: asset.height, fileSize: asset.fileSize,
      });
      const dataUri = await toDataUri(asset.uri);
      await logger.breadcrumb("report", "photo_step: décodage OK", { kb: Math.round(dataUri.length / 1024) });
      setPhotos((p) => [...p, dataUri]);
    } catch (e) {
      logger.error("app", "photo_capture_failed", { error: (e as Error).message });
      showToast("error", "Photo impossible à charger — réessayez.");
    }
  }

  async function submit() {
    if (!coords) {
      showToast("error", "Position GPS indisponible");
      return;
    }
    // V1.2 — a type is now mandatory (no default check).
    if (!selected) {
      showToast("error", "Choisissez un type de signalement.");
      scrollToSection("type", 0);
      return;
    }
    const isAuthorities = selected === "autorites";
    const isSecours = selected === "secours";
    const isAuthOrSecours = isAuthorities || isSecours;
    const isOther = selected === "autre";
    // V1.2 — subtype/activity are no longer pre-filled; enforce them here.
    if (isAuthOrSecours && !subtype) {
      showToast("error", isSecours ? "Choisissez un type de secours." : "Choisissez un type d'autorité.");
      scrollToSection("subtype");
      return;
    }
    if (isAuthOrSecours && !activity) {
      showToast("error", "Choisissez une activité.");
      scrollToSection("activity");
      return;
    }
    // Commentaire requis UNIQUEMENT pour "Autre type de signalement".
    if (isOther && !description.trim()) {
      showToast("error", "Ce type de signalement nécessite un commentaire.");
      return;
    }
    // Validate the contextual extras for non-authority types.
    if (!isAuthOrSecours) {
      if (!subOther) {
        showToast("error", "Sélectionnez un sous-type.");
        return;
      }
      if (selected === "animal_marin" && !health) {
        showToast("error", "Indiquez l'état de l'animal (vivant, mort…).");
        return;
      }
    }
    const headingNum = heading ? Number(heading) : null;
    const speedNum = speed ? Number(speed) : null;
    // Cap/vitesse facultatifs: si renseignés, on valide la plage.
    if (isAuthOrSecours && activity === "navigation") {
      if (headingNum !== null && (Number.isNaN(headingNum) || headingNum < 0 || headingNum > 360)) {
        showToast("error", "Cap entre 0 et 360°");
        return;
      }
      if (speedNum !== null && (Number.isNaN(speedNum) || speedNum < 0)) {
        showToast("error", "Vitesse invalide (en nœuds)");
        return;
      }
    }
    // Build the extras payload per the cahier des charges 27/06/2026.
    let extras: Record<string, string> | null = null;
    if (selected === "animal_marin") {
      extras = { health };
      if (subOther === "mammifere" && species) extras.species = species;
      if (health === "alive_injured" && injuryType) extras.injury_type = injuryType;
    } else if (selected === "obstacle_nav" && subOther === "roche") {
      extras = { roche_variant: rocheVariant };
    }
    setSubmitting(true);
    try {
      await logger.breadcrumb("report", "photo_step: envoi signalement", {
        type: selected, photos: photos.length,
        totalKb: Math.round(photos.reduce((s, p) => s + p.length, 0) / 1024),
      });
      const created = await api.createReport({
        type: selected,
        lat: coords.lat,
        lng: coords.lng,
        description,
        photos,
        subtype: isAuthOrSecours ? subtype : subOther || null,
        activity: isAuthOrSecours ? activity : null,
        heading: isAuthOrSecours && activity === "navigation" ? headingNum : null,
        speed_knots: isAuthOrSecours && activity === "navigation" ? speedNum : null,
        extras: extras ?? undefined,
      });
      // V1.2 — enriched confirmation toast (points earned + first-report tag).
      const gained = Number(created.points_awarded ?? 0);
      if (gained > 0) {
        const tag = created.is_first_report ? " — 1er signalement !" : "";
        showToast("success", `Signalement publié — +${gained} pts${tag}`);
      } else {
        showToast("success", "Signalement publié — merci !");
      }
      // Refresh AuthContext so every screen reads the up-to-date points.
      void refreshAuthUser();
      markReportCreated(created);
      router.replace(`/report/${created.id}?created=1`);
    } catch (e) {
      showToast("error", (e as Error).message || "Erreur");
    } finally {
      setSubmitting(false);
    }
  }

  const isAuthorities = selected === "autorites";
  const isSecours = selected === "secours";
  const isAuthOrSecours = isAuthorities || isSecours;

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="report-close">
            <Ionicons name="close" size={22} color={theme.text} />
          </TouchableOpacity>
          <Text style={styles.title}>Nouveau signalement</Text>
          <View style={{ width: 44 }} />
        </View>

        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.coordCard}>
            <Ionicons name="navigate" size={18} color={theme.primary} />
            <Text style={styles.coordText}>
              {coords
                ? `${toDecimal(coords.lat)}  /  ${toDecimal(coords.lng)}`
                : "Acquisition GPS…"}
            </Text>
          </View>

          <Text
            style={styles.sectionTitle}
            onLayout={onSectionLayout("type")}
          >Type</Text>
          <View style={styles.grid}>
            {REPORT_TYPES.map((t) => {
              const on = selected === t.id;
              return (
                <TouchableOpacity
                  key={t.id}
                  style={[
                    styles.typeCard,
                    on && { borderColor: t.color, backgroundColor: `${t.color}22` },
                  ]}
                  onPress={() => {
                    setSelected(t.id);
                    // Auto-scroll to the next relevant section so the user is
                    // placed exactly where the next choice needs to happen.
                    if (t.id === "autre") {
                      // 24/07 — « Description libre » est auto-sélectionné :
                      // on amène directement le clavier sur le commentaire.
                      scrollToSection("description");
                      setTimeout(() => commentRef.current?.focus(), 380);
                    } else {
                      scrollToSection("subtype");
                    }
                  }}
                  testID={`report-type-${t.id}`}
                >
                  <View style={[styles.typeIcon, { backgroundColor: t.color }]}>
                    <Ionicons name={t.icon} size={22} color="#fff" />
                  </View>
                  <Text style={styles.typeLabel}>{t.label}</Text>
                  <Text style={styles.typeDesc} numberOfLines={on ? undefined : 2}>{t.description}</Text>
                  {on && (
                    <View style={[styles.checkPill, { backgroundColor: t.color }]}>
                      <Ionicons name="checkmark" size={14} color="#fff" />
                    </View>
                  )}
                </TouchableOpacity>
              );
            })}
          </View>

          {!isAuthOrSecours && otherSubtypes.length > 0 && (
            <>
              <Text
                style={styles.sectionTitle}
                onLayout={onSectionLayout("subtype")}
              >Sous-type</Text>
              <View style={styles.grid}>
                {otherSubtypes.map((s) => {
                  const on = subOther === s.id;
                  return (
                    <TouchableOpacity
                      key={s.id}
                      style={[styles.subCard, on && styles.subCardOn]}
                      onPress={() => {
                        setSubOther(s.id);
                        // Route to the most relevant next section based on the
                        // main category + newly picked sub-type.
                        if (selected === "animal_marin") {
                          scrollToSection(s.id === "mammifere" ? "species" : "health");
                        } else if (selected === "obstacle_nav" && s.id === "roche") {
                          scrollToSection("roche");
                        } else {
                          scrollToSection("description");
                        }
                      }}
                      testID={`report-other-subtype-${s.id}`}
                    >
                      <Ionicons name="ellipse" size={10} color={on ? theme.bg : theme.primary} />
                      <Text style={[styles.subLabel, on && { color: theme.bg }]}>{s.label}</Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </>
          )}

          {selected === "animal_marin" && (
            <>
              {subOther === "mammifere" && (
                <>
                  <Text
                    style={styles.sectionTitle}
                    onLayout={onSectionLayout("species")}
                  >Espèce</Text>
                  <View style={styles.grid}>
                    {MARINE_MAMMALS.map((m) => {
                      const on = species === m.id;
                      return (
                        <TouchableOpacity
                          key={m.id}
                          style={[styles.subCard, on && styles.subCardOn]}
                          onPress={() => {
                            setSpecies(m.id);
                            scrollToSection("health");
                          }}
                          testID={`report-species-${m.id}`}
                        >
                          <Text style={[styles.subLabel, on && { color: theme.bg }]}>{m.label}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                </>
              )}
              <Text
                style={styles.sectionTitle}
                onLayout={onSectionLayout("health")}
              >{"État de l'animal"}</Text>
              <View style={styles.grid}>
                {ANIMAL_HEALTH_STATES.map((h) => {
                  const on = health === h.id;
                  const isDead = h.id.startsWith("dead");
                  return (
                    <TouchableOpacity
                      key={h.id}
                      style={[styles.subCard, on && styles.subCardOn]}
                      onPress={() => {
                        setHealth(h.id);
                        scrollToSection(h.id === "alive_injured" ? "injury" : "description");
                      }}
                      testID={`report-health-${h.id}`}
                    >
                      <Ionicons
                        name={isDead ? "skull-outline" : "heart-outline"}
                        size={16}
                        color={on ? theme.bg : (isDead ? "#FF6B6B" : theme.success)}
                      />
                      <Text style={[styles.subLabel, on && { color: theme.bg }]}>{h.label}</Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
              {health === "alive_injured" && (
                <>
                  <Text
                    style={styles.sectionTitle}
                    onLayout={onSectionLayout("injury")}
                  >Cause de la blessure (optionnel)</Text>
                  <View style={styles.grid}>
                    {INJURY_TYPES.map((it) => {
                      const on = injuryType === it.id;
                      return (
                        <TouchableOpacity
                          key={it.id}
                          style={[styles.subCard, on && styles.subCardOn]}
                          onPress={() => setInjuryType(on ? "" : it.id)}
                          testID={`report-injury-${it.id}`}
                        >
                          <Text style={[styles.subLabel, on && { color: theme.bg }]}>{it.label}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                </>
              )}
            </>
          )}

          {selected === "obstacle_nav" && subOther === "roche" && (
            <>
              <Text
                style={styles.sectionTitle}
                onLayout={onSectionLayout("roche")}
              >Type de roche</Text>
              <View style={styles.grid}>
                {ROCHE_VARIANTS.map((v) => {
                  const on = rocheVariant === v.id;
                  return (
                    <TouchableOpacity
                      key={v.id}
                      style={[styles.subCard, on && styles.subCardOn]}
                      onPress={() => {
                        setRocheVariant(v.id);
                        scrollToSection("description");
                      }}
                      testID={`report-roche-${v.id}`}
                    >
                      <Text style={[styles.subLabel, on && { color: theme.bg }]}>{v.label}</Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </>
          )}

          {!isAuthOrSecours && (selected === "animal_marin" || selected === "obstacle_nav" || selected === "pollution") &&
            subOther && health !== "" && selected !== "animal_marin" ? null : null}

          {!isAuthOrSecours && (selected === "animal_marin" || selected === "obstacle_nav" || selected === "pollution") && (
            <View style={styles.driftHint} testID="drift-hint">
              <Ionicons name="information-circle" size={14} color={theme.primary} />
              <Text style={styles.driftHintText}>
                {(() => {
                  if (selected === "obstacle_nav" && subOther === "roche") return "Roche fixe : pas de dérive estimée.";
                  if (selected === "animal_marin" && health && !health.startsWith("dead")) return "Animal vivant : pas de cône de dérive (seuls les corps dérivent).";
                  if (selected === "animal_marin" && !health) return "Sélectionnez l'état pour estimer la dérive éventuelle.";
                  return "Un cône de dérive orange (vent + courant, projection 1 h) s'affichera sur la carte.";
                })()}
              </Text>
            </View>
          )}

          {isAuthOrSecours && (
            <>
              <Text
                style={styles.sectionTitle}
                onLayout={onSectionLayout("subtype")}
              >
                {isSecours ? "Type de secours" : "Type d'autorité"}
              </Text>
              <View style={styles.grid}>
                {(isSecours ? SECOURS_SUBTYPES : AUTHORITY_SUBTYPES).map((s) => {
                  const on = subtype === s.id;
                  return (
                    <TouchableOpacity
                      key={s.id}
                      style={[styles.subCard, on && styles.subCardOn]}
                      onPress={() => {
                        setSubtype(s.id);
                        scrollToSection("activity");
                      }}
                      testID={`report-subtype-${s.id}`}
                    >
                      <Ionicons
                        name={isSecours ? "medkit" : "shield-checkmark"}
                        size={18}
                        color={on ? theme.bg : (isSecours ? "#FF6B6B" : theme.primary)}
                      />
                      <Text style={[styles.subLabel, on && { color: theme.bg }]}>
                        {s.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>

              <Text
                style={styles.sectionTitle}
                onLayout={onSectionLayout("activity")}
              >Activité</Text>
              <View style={styles.activityRow}>
                {(isSecours ? SECOURS_ACTIVITIES : AUTHORITY_ACTIVITIES).map((a) => {
                  const on = activity === a.id;
                  return (
                    <TouchableOpacity
                      key={a.id}
                      style={[styles.activityCard, on && styles.activityCardOn]}
                      onPress={() => {
                        setActivity(a.id);
                        // Navigation activity introduces cap/vitesse fields —
                        // scroll to them; otherwise skip straight to the
                        // comment section.
                        scrollToSection(a.id === "navigation" ? "activity" : "description");
                      }}
                      testID={`report-activity-${a.id}`}
                    >
                      <Ionicons
                        name={a.icon}
                        size={22}
                        color={on ? theme.bg : theme.primary}
                      />
                      <Text style={[styles.activityLabel, on && { color: theme.bg }]}>
                        {a.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>

              {activity === "navigation" && (
                <View style={styles.navRow}>
                  <View style={styles.navField}>
                    <View style={styles.navLabelRow}>
                      <Ionicons name="compass-outline" size={14} color={theme.textDim} style={styles.navLabelIcon} />
                      <Text style={styles.navLabel}>Cap (°) — facultatif</Text>
                    </View>
                    <TextInput
                      style={styles.navInput}
                      value={heading}
                      onChangeText={setHeading}
                      placeholder="ex. 185"
                      placeholderTextColor={theme.textMute}
                      keyboardType="numeric"
                      maxLength={3}
                      testID="report-heading"
                    />
                  </View>
                  <View style={styles.navField}>
                    <View style={styles.navLabelRow}>
                      <Ionicons name="speedometer-outline" size={14} color={theme.textDim} style={styles.navLabelIcon} />
                      <Text style={styles.navLabel}>Vitesse — facultatif</Text>
                    </View>
                    <TextInput
                      style={styles.navInput}
                      value={speed}
                      onChangeText={setSpeed}
                      placeholder="ex. 12"
                      placeholderTextColor={theme.textMute}
                      keyboardType="numeric"
                      maxLength={4}
                      testID="report-speed"
                    />
                  </View>
                </View>
              )}
            </>
          )}

          {/* Description / photos / submit are gated: only visible once the
              user has picked a type (V1.2 — no more default selection). */}
          {selected ? (
            <>
              <Text
                style={styles.sectionTitle}
                onLayout={onSectionLayout("description")}
              >
                {selected === "autre"
                  ? "Commentaire (obligatoire)"
                  : "Commentaire (optionnel)"}
              </Text>
          <TextInput
            ref={commentRef}
            style={styles.textArea}
            value={description}
            onChangeText={setDescription}
            placeholder={
              isAuthOrSecours
                ? "Optionnel — précisions sur le bâtiment, immatriculation…"
                : (selected ? TYPE_BY_ID[selected]?.description : "") || ""
            }
            placeholderTextColor={theme.textMute}
            multiline
            maxLength={400}
            testID="report-description"
          />

          <Text style={styles.sectionTitle}>Photos (max 3)</Text>
          <View style={styles.photoRow}>
            {photos.map((p, i) => (
              <View key={i} style={styles.photo}>
                <Image source={{ uri: p }} style={styles.photoImg} />
                <TouchableOpacity
                  style={styles.removePhoto}
                  onPress={() => setPhotos((arr) => arr.filter((_, idx) => idx !== i))}
                  testID={`remove-photo-${i}`}
                >
                  <Ionicons name="close" size={14} color="#fff" />
                </TouchableOpacity>
              </View>
            ))}
            {photos.length < 3 && (
              <>
                <TouchableOpacity style={styles.addPhoto} onPress={takePhoto} testID="take-photo">
                  <Ionicons name="camera" size={26} color={theme.primary} />
                  <Text style={styles.addPhotoText}>Photo</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.addPhoto} onPress={pickPhoto} testID="add-photo">
                  <Ionicons name="images" size={26} color={theme.primary} />
                  <Text style={styles.addPhotoText}>Galerie</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
            </>
          ) : (
            <View style={styles.emptyHint}>
              <Ionicons name="hand-left-outline" size={22} color={theme.textDim} />
              <Text style={styles.emptyHintText}>
                {"Choisissez un type ci-dessus pour continuer."}
              </Text>
            </View>
          )}
        </ScrollView>

        <View style={styles.footer}>
          <TouchableOpacity
            style={[styles.submit, (submitting || !selected) && { opacity: 0.5 }]}
            disabled={submitting || !selected}
            onPress={submit}
            testID="report-submit-button"
          >
            {submitting ? (
              <ActivityIndicator color={theme.bg} />
            ) : (
              <>
                <Ionicons name="paper-plane" size={20} color={theme.bg} />
                <Text style={styles.submitText}>Publier le signalement</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: theme.border,
  },
  iconBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
  },
  title: { color: theme.text, fontSize: 18, fontWeight: "900" },
  scroll: { padding: spacing.md, gap: spacing.sm, paddingBottom: 120 },
  coordCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  coordText: { color: theme.text, fontWeight: "700" },
  sectionTitle: {
    color: theme.textDim, fontWeight: "800", fontSize: 12, letterSpacing: 2,
    textTransform: "uppercase", marginTop: spacing.md,
  },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  typeCard: {
    flexBasis: "47%", flexGrow: 1, backgroundColor: theme.bg2, padding: spacing.md,
    borderRadius: radii.md, gap: 6, borderWidth: 2, borderColor: theme.border, position: "relative",
  },
  typeIcon: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  typeLabel: { color: theme.text, fontWeight: "800", fontSize: 14 },
  typeDesc: { color: theme.textDim, fontSize: 11, lineHeight: 14 },
  checkPill: {
    position: "absolute", top: 8, right: 8, width: 24, height: 24, borderRadius: 12,
    alignItems: "center", justifyContent: "center",
  },
  subCard: {
    flexBasis: "47%", flexGrow: 1, backgroundColor: theme.bg2, padding: spacing.md,
    borderRadius: radii.md, borderWidth: 1, borderColor: theme.border,
    flexDirection: "row", alignItems: "center", gap: 8, minHeight: 52,
  },
  subCardOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  subLabel: { color: theme.text, fontWeight: "700", fontSize: 13, flex: 1 },
  driftHint: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: `${theme.primary}11`, borderRadius: radii.sm,
    borderWidth: 1, borderColor: `${theme.primary}44`,
    paddingHorizontal: spacing.sm, paddingVertical: 8, marginTop: spacing.sm,
  },
  driftHintText: { color: theme.textDim, fontSize: 12, flex: 1, lineHeight: 16 },
  // V1.2 — inline hint shown when no type is chosen yet.
  emptyHint: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, marginTop: spacing.md,
  },
  emptyHintText: { color: theme.textDim, fontSize: 13, flex: 1 },
  activityRow: { flexDirection: "row", gap: spacing.sm, alignItems: "stretch" },
  activityCard: {
    flex: 1, backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, alignItems: "center", minHeight: 88,
    justifyContent: "flex-start", paddingTop: 12, paddingBottom: 10,
  },
  activityCardOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  activityLabel: {
    color: theme.text, fontWeight: "700", fontSize: 12, textAlign: "center",
    marginTop: 8, flexShrink: 1, lineHeight: 16,
  },
  navRow: { flexDirection: "row", gap: spacing.sm },
  navField: { flex: 1, gap: 4 },
  navLabelRow: { flexDirection: "row", alignItems: "center", gap: 6, height: 18, marginBottom: 4 },
  navLabelIcon: { width: 14, height: 14, textAlign: "center" },
  navLabel: { color: theme.textDim, fontSize: 12, fontWeight: "700" },
  navInput: {
    backgroundColor: theme.bg2, color: theme.text, fontSize: 18,
    paddingVertical: 12, paddingHorizontal: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, fontWeight: "900",
  },
  textArea: {
    backgroundColor: theme.bg2, borderRadius: radii.md, padding: spacing.md,
    color: theme.text, minHeight: 90, textAlignVertical: "top",
    borderWidth: 1, borderColor: theme.border, fontSize: 15,
  },
  photoRow: { flexDirection: "row", gap: spacing.sm },
  photo: { width: 100, height: 100, borderRadius: radii.md, overflow: "hidden", position: "relative" },
  photoImg: { width: "100%", height: "100%" },
  removePhoto: {
    position: "absolute", top: 6, right: 6, width: 22, height: 22, borderRadius: 11,
    backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center",
  },
  addPhoto: {
    width: 100, height: 100, borderRadius: radii.md, borderWidth: 2, borderStyle: "dashed",
    borderColor: theme.primary, alignItems: "center", justifyContent: "center", gap: 4,
    backgroundColor: theme.bg2,
  },
  addPhotoText: { color: theme.primary, fontWeight: "700", fontSize: 12 },
  footer: {
    padding: spacing.md, borderTopWidth: 1, borderTopColor: theme.border, backgroundColor: theme.bg,
  },
  submit: {
    backgroundColor: theme.primary, padding: 16, borderRadius: radii.md,
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: spacing.sm,
    minHeight: 56,
  },
  submitText: { color: theme.bg, fontWeight: "900", fontSize: 17 },
});
