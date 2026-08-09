// SignalMar — Visuel « post viral » 1080×1080 (11/07/2026).
//
// Rendu HORS ÉCRAN dans le détail d'un signalement puis capturé avec
// react-native-view-shot pour être partagé sur Instagram / Facebook / X.
// Règles produit :
//   • position APPROXIMATIVE uniquement (arrondie ~0,1° ≈ zone ± 5 km)
//   • mention obligatoire : « Plus de précisions sur SignalMar.app »

import { Image, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { type ReportItem } from "@/src/api/client";
import { TYPE_BY_ID, type ReportTypeId } from "@/src/lib/report-types";
import { formatTimeAgo } from "@/src/lib/coords";

export const SOCIAL_CARD_SIZE = 350; // capturé en 1080×1080 (width option)

/** Zone approximative publique : coordonnées arrondies à 0,1°. */
export function approxZone(lat: number, lng: number): string {
  const f = (v: number) => Math.abs(v).toFixed(1).replace(".", ",");
  return `Zone ${f(lat)}°${lat >= 0 ? "N" : "S"} · ${f(lng)}°${lng >= 0 ? "E" : "O"}`;
}

const EMOJI: Record<string, string> = {
  autorites: "\u{1F6E1}\uFE0F", secours: "\u{1F6DF}", obstacle_nav: "\u26A0\uFE0F",
  animal_marin: "\u{1F42C}", pollution: "\u{1F6E2}\uFE0F", autre: "\u2049\uFE0F",
};

/** Extrait public : 100 premiers caractères de la description + « ... ». */
export function descriptionExcerpt(desc?: string | null): string | null {
  const d = (desc || "").trim();
  if (!d) return null;
  return d.length > 100 ? d.slice(0, 100).trimEnd() + "..." : d;
}

/** Tuile OSM de la zone APPROXIMATIVE (coords arrondies 0,1°, zoom large)
 *  — affichée FLOUTÉE pour protéger la position exacte. Réutilisée par la
 *  page web publique /s/[CODE]. */
export function approxTileUrl(lat: number, lng: number, z = 7): string {
  const rlat = Math.round(lat * 10) / 10;
  const rlng = Math.round(lng * 10) / 10;
  const n = 2 ** z;
  const x = Math.min(n - 1, Math.max(0, Math.floor(((rlng + 180) / 360) * n)));
  const latRad = (rlat * Math.PI) / 180;
  const y = Math.min(
    n - 1,
    Math.max(0, Math.floor(
      ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n,
    )),
  );
  return `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
}

export function SocialPostCard({ report }: { report: ReportItem }) {
  const t = TYPE_BY_ID[report.type as ReportTypeId];
  const color = t?.color || "#48CAE4";
  const photo = report.photos?.[0] || null;
  const emoji = EMOJI[report.type] || "\u2693";
  const excerpt = descriptionExcerpt(report.description);

  return (
    <View style={styles.card} collapsable={false}>
      {photo ? (
        <Image source={{ uri: photo }} style={StyleSheet.absoluteFill} resizeMode="cover" />
      ) : (
        <View style={[StyleSheet.absoluteFill, { backgroundColor: "#0B132B" }]}>
          <View style={[styles.bgGlow, { backgroundColor: color + "33" }]} />
          <Text style={styles.bgEmoji}>{emoji}</Text>
        </View>
      )}
      {/* Voiles de lisibilité haut/bas. */}
      <View style={styles.scrimTop} />
      <View style={styles.scrimBottom} />

      {/* En-tête : marque + heure. */}
      <View style={styles.topRow}>
        <View style={styles.brandPill}>
          <Ionicons name="boat" size={15} color="#0B132B" />
          <Text style={styles.brandTxt}>SignalMar</Text>
        </View>
        <View style={styles.whenPill}>
          <Text style={styles.whenTxt}>{formatTimeAgo(report.created_at)}</Text>
        </View>
      </View>

      {/* Bloc bas : type + zone + mention. */}
      <View style={styles.bottom}>
        <View style={[styles.typePill, { backgroundColor: color }]}>
          <Text style={styles.typeEmoji}>{emoji}</Text>
          <Text style={styles.typeTxt} numberOfLines={1}>
            {(t?.label || report.type).toUpperCase()}
          </Text>
        </View>
        <Text style={styles.alertTxt}>Signalé en mer par la communauté</Text>
        {excerpt ? (
          <Text style={styles.excerptTxt} numberOfLines={3}>
            {"\u00AB "}{excerpt}{" \u00BB"}
          </Text>
        ) : null}
        {/* Aperçu carte FLOUTÉ — zone approximative uniquement, la position
            exacte n'est jamais divulguée sur un post public. */}
        <View style={styles.mapStrip}>
          <Image
            source={{ uri: approxTileUrl(report.lat, report.lng) }}
            style={StyleSheet.absoluteFill}
            resizeMode="cover"
            blurRadius={6}
          />
          <View style={styles.mapVeil} />
          <Ionicons name="location" size={16} color="#F4A261" />
          <Text style={styles.zoneTxt}>{approxZone(report.lat, report.lng)} (approx.)</Text>
        </View>
        <View style={styles.ctaBar}>
          <Text style={styles.ctaTxt}>
            Obtenez gratuitement SignalMar sur SignalMar.app (Android et Iphone) et
            retrouvez en détail ce signalement :{" "}
            <Text style={styles.ctaCode}>{report.short_id || "—"}</Text>
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: SOCIAL_CARD_SIZE, height: SOCIAL_CARD_SIZE,
    borderRadius: 0, overflow: "hidden", backgroundColor: "#0B132B",
  },
  bgGlow: {
    position: "absolute", top: -80, left: -80, right: -80, height: 260,
    borderRadius: 999,
  },
  bgEmoji: {
    position: "absolute", alignSelf: "center", top: SOCIAL_CARD_SIZE / 2 - 70,
    fontSize: 92,
  },
  scrimTop: {
    position: "absolute", top: 0, left: 0, right: 0, height: 70,
    backgroundColor: "rgba(11,19,43,0.45)",
  },
  scrimBottom: {
    position: "absolute", bottom: 0, left: 0, right: 0, height: 150,
    backgroundColor: "rgba(11,19,43,0.72)",
  },
  topRow: {
    position: "absolute", top: 12, left: 12, right: 12,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  brandPill: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: "#48CAE4", borderRadius: 999,
    paddingHorizontal: 11, paddingVertical: 5,
  },
  brandTxt: { color: "#0B132B", fontWeight: "900", fontSize: 14 },
  whenPill: {
    backgroundColor: "rgba(11,19,43,0.65)", borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5,
    borderWidth: 1, borderColor: "rgba(255,255,255,0.25)",
  },
  whenTxt: { color: "#F4F6F8", fontWeight: "700", fontSize: 11 },
  bottom: { position: "absolute", left: 14, right: 14, bottom: 12, gap: 6 },
  typePill: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6,
  },
  typeEmoji: { fontSize: 14 },
  typeTxt: { color: "#0B132B", fontWeight: "900", fontSize: 15, letterSpacing: 0.5 },
  alertTxt: { color: "#F4F6F8", fontWeight: "800", fontSize: 13 },
  excerptTxt: {
    color: "#E7EEF5", fontWeight: "600", fontSize: 12, fontStyle: "italic",
    lineHeight: 16,
  },
  mapStrip: {
    height: 46, borderRadius: 10, overflow: "hidden",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderWidth: 1, borderColor: "rgba(255,255,255,0.25)",
  },
  mapVeil: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(11,19,43,0.35)",
  },
  zoneTxt: { color: "#FFFFFF", fontWeight: "800", fontSize: 12 },
  ctaBar: {
    backgroundColor: "#F4A261", borderRadius: 10,
    paddingVertical: 7, paddingHorizontal: 10, marginTop: 2,
  },
  ctaTxt: {
    color: "#0B132B", fontWeight: "800", fontSize: 10.5, lineHeight: 14,
    textAlign: "center",
  },
  ctaCode: { fontWeight: "900", fontSize: 12, letterSpacing: 1 },
});
