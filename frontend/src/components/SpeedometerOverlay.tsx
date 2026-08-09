// SignalMar — Compteur de vitesse en BANDE (12/07/2026, v3).
//
// Version unique « Verre » (ex-variante A) retenue par l'utilisateur :
//   • PRIORITÉ AUX CHIFFRES (gros, tabulaires), cap à DROITE.
//   • Unité par défaut : nœuds (« Nds ») — tap sur l'unité ⇄ km/h (persisté).
//     Conversion : 1 nœud = 1 mille marin (1852 m) / heure = 1,852 km/h.
//   • Déplaçable par APPUI LONG + glisser (position persistée).
//   • Fermeture : croix ou tap à côté.

import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TouchableOpacity, useWindowDimensions, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, {
  runOnJS, useAnimatedStyle, useSharedValue, withDelay, withSpring, withTiming,
} from "react-native-reanimated";

import { theme } from "@/src/lib/theme";
import { storage } from "@/src/utils/storage";
import { useSafeAreaInsets } from "react-native-safe-area-context";

type Unit = "kn" | "kmh";

// 1 nœud = 1 mille marin (1852 m) par heure → 1,852 km/h exactement.
const KMH_PER_KNOT = 1.852;

const BAND_W = 320;
const BAND_H = 72; // réduit (cap sur 1 ligne) sans toucher à la taille des chiffres
// Ancrage vertical par défaut de la bande (depuis le HAUT de l'écran).
const ANCHOR_TOP = 108;
// Bas de la rangée de pills du haut (SafeArea top + padding 8 + pill ~44).
// La bande peut venir se COLLER juste dessous, sans jamais les chevaucher.
const TOPBAR_H = 54;

function capTxt(heading: number | null): string {
  if (heading == null) return "—";
  const dirs = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
  return `${Math.round(heading)}° ${dirs[Math.round(heading / 45) % 8]}`;
}

export function SpeedometerOverlay({
  visible, onClose, speedMs, heading,
}: {
  visible: boolean;
  onClose: () => void;
  speedMs: number | null;
  heading: number | null;
}) {
  const { width: W, height: H } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [unit, setUnit] = useState<Unit>("kn");
  const [dragging, setDragging] = useState(false);
  // Limite haute du drag : la bande peut venir se COLLER juste sous les
  // pills du haut (GPS / vitesse / filtres), sans jamais les chevaucher.
  const minTy = insets.top + TOPBAR_H - ANCHOR_TOP;

  // Position — remise à zéro (bande CENTRÉE) à chaque ouverture ;
  // déplaçable pendant la session uniquement (plus de persistance).
  const tx = useSharedValue(0);
  const ty = useSharedValue(0);
  const sx = useSharedValue(0);
  const sy = useSharedValue(0);
  const pop = useSharedValue(0);
  // Astuce « Appui long pour déplacer » : visible 3 s puis fondu progressif.
  const hintOp = useSharedValue(0);

  useEffect(() => {
    storage.getItem<Unit>("sm.speedo.unit", "kn")
      .then((u) => { if (u === "kn" || u === "kmh") setUnit(u); }).catch(() => {});
  }, []);

  useEffect(() => {
    pop.value = visible
      ? withSpring(1, { damping: 14, stiffness: 160 })
      : withTiming(0, { duration: 140 });
    // Bandeau d'astuce : affiché 3 s à chaque ouverture, puis fondu (800 ms).
    if (visible) {
      // Toujours s'ouvrir CENTRÉ (retour utilisateur 12/07).
      tx.value = 0;
      ty.value = 0;
      hintOp.value = 1;
      hintOp.value = withDelay(3000, withTiming(0, { duration: 800 }));
    } else {
      hintOp.value = 0;
    }
  }, [visible, pop, hintOp, tx, ty]);

  const setDrag = (v: boolean) => setDragging(v);

  const panGesture = Gesture.Pan()
    .activateAfterLongPress(320)
    .onStart(() => {
      sx.value = tx.value; sy.value = ty.value;
      runOnJS(setDrag)(true);
    })
    .onChange((e) => {
      const maxX = (W - BAND_W) / 2 + 8;
      tx.value = Math.min(maxX, Math.max(-maxX, sx.value + e.translationX));
      // Haut : collage possible juste sous les pills (minTy), sans
      // chevauchement. Bas : collage tout en bas, au-dessus de la tab bar.
      ty.value = Math.min(H - 240, Math.max(minTy, sy.value + e.translationY));
    })
    .onFinalize(() => {
      runOnJS(setDrag)(false);
    });

  const bandStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: tx.value },
      { translateY: ty.value },
      { scale: 0.85 + 0.15 * pop.value },
    ],
    opacity: pop.value,
  }));

  const hintStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: tx.value }, { translateY: ty.value }],
    opacity: pop.value * hintOp.value,
  }));

  if (!visible) return null;

  // m/s → km/h (×3,6) ; km/h → nœuds (÷1,852). Seuil d'affichage : 3 km/h.
  const kmh = speedMs != null && speedMs * 3.6 >= 3 ? speedMs * 3.6 : 0;
  const val = unit === "kn" ? kmh / KMH_PER_KNOT : kmh;
  const valTxt = val.toFixed(1);
  // 15/07/2026 (bug terrain) : au-delà de 100 km/h (« 102.4 » = 5 caractères)
  // les chiffres étaient TRONQUÉS (adjustsFontSizeToFit peu fiable selon
  // plateforme). Taille adaptée déterministe jusqu'à 3 chiffres et plus.
  const valueFontSize = valTxt.length >= 6 ? 34 : valTxt.length === 5 ? 42 : 52;
  const toggleUnit = () => {
    const next: Unit = unit === "kn" ? "kmh" : "kn";
    setUnit(next);
    storage.setItem("sm.speedo.unit", next).catch(() => {});
  };

  return (
    // 13/07 — plus de GestureHandlerRootView imbriqué (root unique dans
    // app/_layout.tsx). Le plein écran reste volontaire ici : le backdrop
    // Pressable ferme le compteur au tap à côté.
    <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
      {/* Tap à côté = fermeture. */}
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} testID="speedo-backdrop" />
      <View style={styles.anchor} pointerEvents="box-none">
        <GestureDetector gesture={panGesture}>
          <Animated.View
            style={[styles.band, dragging && styles.bandDragging, bandStyle]}
            testID="speedo-band"
          >
            {/* Chiffres — priorité visuelle. */}
            <View style={styles.valueBlock}>
              <Text
                style={[styles.value, { fontSize: valueFontSize }]}
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.55}
                testID="speedo-value"
              >
                {valTxt}
              </Text>
              <TouchableOpacity
                onPress={toggleUnit}
                hitSlop={10}
                style={styles.unitBtn}
                testID="speedo-unit"
                accessibilityLabel="Changer d'unité"
              >
                <Text style={styles.unitTxt}>
                  {unit === "kn" ? "Nds" : "km/h"}
                </Text>
              </TouchableOpacity>
            </View>

            {/* Cap — à droite, sur UNE ligne : [compas] 279° O. */}
            <View style={styles.capBlock}>
              <Ionicons name="compass-outline" size={19} color={theme.primary} />
              <Text style={styles.capTxt} numberOfLines={1} testID="speedo-cap">
                {capTxt(heading)}
              </Text>
            </View>

            <TouchableOpacity style={styles.closeBtn} onPress={onClose} hitSlop={10} testID="speedo-close">
              <Ionicons name="close" size={17} color={theme.textDim} />
            </TouchableOpacity>
          </Animated.View>
        </GestureDetector>

        <Animated.View style={[styles.hintRow, hintStyle]} pointerEvents="none">
          <Text style={styles.hintTxt}>Appui long pour déplacer</Text>
        </Animated.View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  anchor: { position: "absolute", top: ANCHOR_TOP, left: 0, right: 0, alignItems: "center" },
  band: {
    width: BAND_W, height: BAND_H,
    borderRadius: 20, flexDirection: "row", alignItems: "center",
    paddingLeft: 16, paddingRight: 34, overflow: "hidden",
    backgroundColor: "rgba(11,19,43,0.88)",
    borderWidth: 1.5, borderColor: "rgba(72,202,228,0.55)",
    shadowColor: "#000", shadowOpacity: 0.45, shadowRadius: 16,
    shadowOffset: { width: 0, height: 8 }, elevation: 12,
  },
  bandDragging: { shadowOpacity: 0.7, elevation: 20 },
  valueBlock: { flex: 1, flexDirection: "row", alignItems: "center", gap: 8 },
  value: {
    color: "#FFFFFF", fontSize: 52, fontWeight: "900",
    fontVariant: ["tabular-nums"], letterSpacing: -1, flexShrink: 1,
  },
  unitBtn: {
    backgroundColor: "rgba(72,202,228,0.18)",
    borderWidth: 1, borderColor: "rgba(72,202,228,0.5)",
    borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4,
  },
  unitTxt: { color: theme.primary, fontWeight: "900", fontSize: 14 },
  capBlock: { flexDirection: "row", alignItems: "center", gap: 5 },
  capTxt: {
    color: "#FFFFFF", fontSize: 21, fontWeight: "900",
    fontVariant: ["tabular-nums"], letterSpacing: -0.5,
  },
  closeBtn: { position: "absolute", top: 6, right: 8 },
  hintRow: {
    marginTop: 10, backgroundColor: "rgba(11,19,43,0.85)", borderRadius: 999,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 12, paddingVertical: 5,
  },
  hintTxt: { color: theme.textMute, fontSize: 10.5 },
});
