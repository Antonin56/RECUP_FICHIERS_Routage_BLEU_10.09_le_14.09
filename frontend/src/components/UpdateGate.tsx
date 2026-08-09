// SignalMar — Détection de mise à jour au lancement (15/07/2026, GO armateur).
//
// Au boot, l'app interroge GET /api/app/version (fail-silent : jamais
// bloquant si le réseau/backend est indisponible) et compare sa propre
// version (app.json expo.version, lue via expo-constants) :
//   • locale < minimum → écran « Mise à jour requise » (blocage DOUX :
//     bouton store bien visible + lien « Plus tard » discret — app de
//     sécurité en mer, on ne verrouille jamais complètement).
//   • locale < latest  → bannière « Mise à jour disponible » rejetable,
//     mémorisée PAR VERSION (ne réapparaît pas pour la même version).
// Les URLs de store sont fournies par le backend (configurables sans
// redéploiement via POST /api/app/version, admin).

import React, { useEffect, useState, useCallback } from "react";
import { View, Text, TouchableOpacity, StyleSheet, Linking, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Constants from "expo-constants";
import { Ionicons } from "@expo/vector-icons";

import { storage } from "@/src/utils/storage";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
const DISMISS_KEY = "signmar.update.dismissed"; // valeur = version "latest" rejetée

/** true si a < b (comparaison numérique segment par segment, "1.5.0"). */
export function semverLt(a: string, b: string): boolean {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < 3; i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x !== y) return x < y;
  }
  return false;
}

interface VersionInfo {
  latest: string;
  minimum: string;
  android_url: string;
  ios_url: string;
  message: string;
}

export default function UpdateGate() {
  const insets = useSafeAreaInsets();
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [mode, setMode] = useState<"none" | "banner" | "required">("none");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 6000);
        const res = await fetch(`${BASE}/api/app/version`, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!res.ok) return;
        const v: VersionInfo = await res.json();
        if (cancelled) return;
        const current = Constants.expoConfig?.version ?? "0.0.0";
        if (semverLt(current, v.minimum)) {
          setInfo(v); setMode("required");
        } else if (semverLt(current, v.latest)) {
          const dismissed = await storage.getItem<string>(DISMISS_KEY, "");
          if (!cancelled && dismissed !== v.latest) { setInfo(v); setMode("banner"); }
        }
      } catch { /* fail-silent : pas de réseau ≠ pas d'app */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const openStore = useCallback(() => {
    if (!info) return;
    const url = Platform.OS === "ios" ? info.ios_url : info.android_url;
    if (url) Linking.openURL(url).catch(() => {});
  }, [info]);

  const dismissBanner = useCallback(() => {
    if (info) void storage.setItem(DISMISS_KEY, info.latest);
    setMode("none");
  }, [info]);

  if (mode === "none" || !info) return null;

  const hasStoreUrl = !!(Platform.OS === "ios" ? info.ios_url : info.android_url);

  if (mode === "required") {
    return (
      <View style={styles.overlay} testID="update-required">
        <View style={styles.card}>
          <Ionicons name="cloud-download-outline" size={44} color="#48CAE4" />
          <Text style={styles.title}>Mise à jour requise</Text>
          <Text style={styles.body}>
            {info.message ||
              "Cette version de SignalMar n'est plus supportée. Mettez à jour l'application pour continuer à recevoir les signalements et alertes."}
          </Text>
          {hasStoreUrl && (
            <TouchableOpacity style={styles.cta} onPress={openStore} testID="update-required-cta">
              <Text style={styles.ctaText}>Mettre à jour</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity onPress={() => setMode("none")} style={styles.laterBtn} testID="update-later">
            <Text style={styles.laterText}>Plus tard</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={[styles.banner, { top: insets.top + 6 }]} testID="update-banner">
      <Ionicons name="cloud-download-outline" size={18} color="#06222E" />
      <Text style={styles.bannerText} numberOfLines={2}>
        Mise à jour disponible ({info.latest})
        {info.message ? ` — ${info.message}` : ""}
      </Text>
      {hasStoreUrl && (
        <TouchableOpacity onPress={openStore} style={styles.bannerCta} testID="update-banner-cta">
          <Text style={styles.bannerCtaText}>Mettre à jour</Text>
        </TouchableOpacity>
      )}
      <TouchableOpacity onPress={dismissBanner} hitSlop={10} testID="update-banner-close">
        <Ionicons name="close" size={18} color="#06222E" />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(4,18,26,0.94)",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    zIndex: 9999,
  },
  card: {
    width: "100%",
    maxWidth: 400,
    backgroundColor: "#0D2B3A",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "rgba(72,202,228,0.35)",
    padding: 24,
    alignItems: "center",
    gap: 12,
  },
  title: { color: "#EAF7FB", fontSize: 19, fontWeight: "900" },
  body: { color: "#9DBBC7", fontSize: 14, lineHeight: 20, textAlign: "center" },
  cta: {
    backgroundColor: "#48CAE4",
    borderRadius: 12,
    minHeight: 48,
    paddingHorizontal: 28,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "stretch",
    marginTop: 6,
  },
  ctaText: { color: "#06222E", fontWeight: "900", fontSize: 15 },
  laterBtn: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  laterText: { color: "#5E7C8A", fontSize: 13, fontWeight: "600" },
  banner: {
    position: "absolute",
    left: 12,
    right: 12,
    backgroundColor: "#48CAE4",
    borderRadius: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    zIndex: 9999,
    elevation: 8,
  },
  bannerText: { flex: 1, color: "#06222E", fontSize: 12.5, fontWeight: "700" },
  bannerCta: {
    backgroundColor: "#06222E",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  bannerCtaText: { color: "#8FE3F7", fontSize: 12, fontWeight: "800" },
});
