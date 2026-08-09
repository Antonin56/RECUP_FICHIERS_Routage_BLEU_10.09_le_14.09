/**
 * SignalMar — Carte « Marées » de l'onglet Météo (20/07/2026, GO armateur).
 * Port le plus proche de la position + horaires/hauteurs BM-PM + COEFFICIENT
 * (approché — Open-Meteo calé sur Brest, non officiel). Sélecteur de jour
 * (aujourd'hui + 4) et choix parmi les 3 ports les plus proches.
 */
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api, type TidesResponse } from "@/src/api/client";
import { radii, spacing, theme } from "@/src/lib/theme";

const DAY_LABELS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];

function dayLabel(dateStr: string, index: number): string {
  if (index === 0) return "Auj.";
  const d = new Date(`${dateStr}T12:00:00`);
  return `${DAY_LABELS[d.getDay()]} ${d.getDate()}`;
}

export function TideCard({ coords }: { coords: { lat: number; lng: number } | null }) {
  const [data, setData] = useState<TidesResponse | null>(null);
  const [error, setError] = useState(false);
  const [dayIdx, setDayIdx] = useState(0);
  // Port choisi parmi les 3 plus proches (null = le plus proche).
  const [portId, setPortId] = useState<string | null>(null);

  const target = useMemo(() => {
    if (!data || !portId) return null;
    return data.nearest_ports.find((p) => p.id === portId) ?? null;
  }, [data, portId]);

  useEffect(() => {
    const c = coords ?? { lat: 47.55, lng: -2.91 }; // défaut : zone pilote
    const q = target ?? c;
    setError(false);
    api
      .tidesNearest("lat" in q ? q.lat : c.lat, "lng" in q ? q.lng : c.lng)
      .then((d) => { setData(d); setDayIdx((i) => Math.min(i, d.days.length - 1)); })
      .catch(() => setError(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coords?.lat, coords?.lng, portId]);

  if (error) {
    return (
      <View style={styles.card} testID="tide-card">
        <Text style={styles.err}>Marées momentanément indisponibles.</Text>
      </View>
    );
  }
  if (!data) {
    return (
      <View style={styles.card} testID="tide-card">
        <ActivityIndicator color={theme.primary} />
      </View>
    );
  }

  const day = data.days[dayIdx] ?? data.days[0];
  return (
    <View style={styles.card} testID="tide-card">
      <View style={styles.head}>
        <Ionicons name="swap-vertical" size={16} color={theme.primary} />
        <Text style={styles.title}>Marées — {data.port.name}</Text>
        <Text style={styles.dist}>{data.port.distance_km} km</Text>
      </View>

      {/* Ports proches */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {data.nearest_ports.map((p) => {
          const active = p.id === data.port.id;
          return (
            <TouchableOpacity
              key={p.id}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => setPortId(p.id)}
              testID={`tide-port-${p.id}`}
            >
              <Text style={[styles.chipTxt, active && styles.chipTxtActive]}>{p.name}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {/* Jours */}
      <View style={styles.dayRow}>
        {data.days.map((d, i) => (
          <TouchableOpacity
            key={d.date}
            style={[styles.dayChip, i === dayIdx && styles.dayChipActive]}
            onPress={() => setDayIdx(i)}
            testID={`tide-day-${i}`}
          >
            <Text style={[styles.dayTxt, i === dayIdx && styles.dayTxtActive]}>
              {dayLabel(d.date, i)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Événements BM/PM */}
      <View style={{ gap: 6 }}>
        {day.events.map((e, i) => (
          <View key={i} style={styles.eventRow}>
            <View style={[styles.typeBadge, e.type === "PM" ? styles.pmBadge : styles.bmBadge]}>
              <Text style={styles.typeTxt}>{e.type}</Text>
            </View>
            <Text style={styles.timeTxt}>{e.time}</Text>
            <Text style={styles.heightTxt}>≈ {e.height_m.toFixed(1)} m</Text>
            {e.coef != null ? (
              <View style={styles.coefBadge}>
                <Text style={styles.coefTxt}>coef {e.coef}</Text>
              </View>
            ) : (
              <View style={{ width: 62 }} />
            )}
          </View>
        ))}
      </View>

      <Text style={styles.disclaimer}>
        Prédictions approchées (Open-Meteo, coefficient calé sur Brest) — non
        officielles. Hauteurs ~au-dessus du zéro hydrographique.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, gap: spacing.sm,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { color: theme.text, fontSize: 15, fontWeight: "800", flex: 1 },
  dist: { color: theme.textDim, fontSize: 11, fontWeight: "700" },
  chips: { gap: 6 },
  chip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: radii.pill,
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg,
  },
  chipActive: { borderColor: theme.primary, backgroundColor: "rgba(72,202,228,0.12)" },
  chipTxt: { color: theme.textDim, fontSize: 11, fontWeight: "700" },
  chipTxtActive: { color: theme.primary },
  dayRow: { flexDirection: "row", gap: 6 },
  dayChip: {
    flex: 1, paddingVertical: 7, borderRadius: radii.sm, alignItems: "center",
    borderWidth: 1, borderColor: theme.border, backgroundColor: theme.bg,
  },
  dayChipActive: { borderColor: theme.primary, backgroundColor: "rgba(72,202,228,0.12)" },
  dayTxt: { color: theme.textDim, fontSize: 11, fontWeight: "700" },
  dayTxtActive: { color: theme.primary },
  eventRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  typeBadge: {
    width: 34, paddingVertical: 3, borderRadius: radii.sm, alignItems: "center",
  },
  pmBadge: { backgroundColor: "rgba(72,202,228,0.18)" },
  bmBadge: { backgroundColor: "rgba(244,162,97,0.18)" },
  typeTxt: { color: theme.text, fontSize: 11, fontWeight: "900" },
  timeTxt: { color: theme.text, fontSize: 15, fontWeight: "800", width: 56 },
  heightTxt: { color: theme.textDim, fontSize: 13, fontWeight: "700", flex: 1 },
  coefBadge: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: radii.pill,
    backgroundColor: "rgba(46,196,182,0.15)", borderWidth: 1,
    borderColor: "rgba(46,196,182,0.4)", width: 62, alignItems: "center",
  },
  coefTxt: { color: "#2EC4B6", fontSize: 11, fontWeight: "900" },
  disclaimer: { color: theme.textMute, fontSize: 9, lineHeight: 12 },
  err: { color: theme.textDim, fontSize: 12 },
});
