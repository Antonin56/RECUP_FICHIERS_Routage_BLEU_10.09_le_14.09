// SignalMar — Popup « Signalement toujours là ? » (15/07/2026, GO armateur).
//
// Affichée par la carte quand le bateau vient de DÉPASSER un signalement à
// ≤ 500 m (hook useProximityConfirm). Fermeture AUTO en 7 s matérialisée par
// une barre de progression ; aucune réponse = aucun effet. Gros boutons
// (gants / mains prises), style distinct de l'alerte (pas de rouge, pas de
// son) pour ne JAMAIS être confondue avec la séquence d'alarme.

import React, { useEffect, useRef } from "react";
import { View, Text, TouchableOpacity, StyleSheet, Animated, LayoutChangeEvent } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import type { ReportItem } from "@/src/api/client";
import { TYPE_BY_ID } from "@/src/lib/report-types";
import { theme, spacing } from "@/src/lib/theme";

// 16/07/2026 (retour user) : 7 s trop court pour lire + décider en nav — passé à 12 s.
const AUTO_CLOSE_MS = 12_000;

export function ProximityConfirmCard({ report, onYes, onNo, onTimeout }: {
  report: ReportItem;
  onYes: () => void;
  onNo: () => void;
  onTimeout: () => void;
}) {
  // 16/07/2026 — la barre saccadait par phases (progression animée sur
  // `width` = layout, non compatible native driver). On l'anime désormais
  // via transform.scaleX pilotée sur le driver natif → 60 fps fluides.
  // Note : scaleX ancré à gauche via transformOrigin (RN 0.71+ = automatique
  // avec un style d'ancrage = translateX).
  const progress = useRef(new Animated.Value(1)).current;
  const trackW = useRef(0);
  const timeoutRef = useRef(onTimeout);
  timeoutRef.current = onTimeout;

  useEffect(() => {
    progress.setValue(1);
    const anim = Animated.timing(progress, {
      toValue: 0,
      duration: AUTO_CLOSE_MS,
      useNativeDriver: true,
    });
    anim.start();
    const t = setTimeout(() => timeoutRef.current(), AUTO_CLOSE_MS);
    return () => { anim.stop(); clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report.id]);

  const onTrackLayout = (e: LayoutChangeEvent) => {
    trackW.current = e.nativeEvent.layout.width;
  };

  const def = TYPE_BY_ID[report.type as keyof typeof TYPE_BY_ID];
  const label = def?.short || def?.label || "Signalement";

  return (
    <View style={styles.card} testID="proximity-confirm-card">
      <View style={styles.headerRow}>
        <Ionicons name={(def?.icon as never) || "help-circle"} size={18} color={def?.color || theme.primary} />
        <Text style={styles.title} numberOfLines={1}>
          {label} — toujours là ?
        </Text>
      </View>
      <View style={styles.btnRow}>
        <TouchableOpacity style={[styles.btn, styles.btnYes]} onPress={onYes} testID="proximity-confirm-yes">
          <Ionicons name="checkmark-circle" size={18} color="#06222E" />
          <Text style={styles.btnYesText}>Oui, vu !</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.btn, styles.btnNo]} onPress={onNo} testID="proximity-confirm-no">
          <Ionicons name="close-circle-outline" size={18} color={theme.text} />
          <Text style={styles.btnNoText}>Non, pas vu.</Text>
        </TouchableOpacity>
      </View>
      <View style={styles.progressTrack} onLayout={onTrackLayout}>
        <Animated.View
          style={[styles.progressFill, {
            transform: [{ scaleX: progress }],
          }]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.bg2,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(72,202,228,0.45)",
    padding: spacing.md,
    gap: 10,
    shadowColor: "#000",
    shadowOpacity: 0.35,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
    elevation: 6,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { flex: 1, color: theme.text, fontSize: 15, fontWeight: "900" },
  btnRow: { flexDirection: "row", gap: 10 },
  btn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, minHeight: 48, borderRadius: 12,
  },
  btnYes: { backgroundColor: theme.primary },
  btnYesText: { color: "#06222E", fontWeight: "900", fontSize: 15 },
  btnNo: { backgroundColor: theme.bg3, borderWidth: 1, borderColor: theme.border },
  btnNoText: { color: theme.text, fontWeight: "800", fontSize: 15 },
  progressTrack: { height: 4, borderRadius: 2, backgroundColor: theme.bg3, overflow: "hidden" },
  // width: '100%' + scaleX(progress) → animation continue sur driver natif.
  // transformOrigin: gauche pour que la barre se vide vers la droite.
  progressFill: {
    height: 4, width: "100%", borderRadius: 2,
    backgroundColor: theme.primary,
    // @ts-expect-error RN Web tolère transformOrigin ; iOS/Android l'utilisent
    // à partir de 0.74 (default = center). On force à gauche pour l'animation.
    transformOrigin: "left center",
  },
});
