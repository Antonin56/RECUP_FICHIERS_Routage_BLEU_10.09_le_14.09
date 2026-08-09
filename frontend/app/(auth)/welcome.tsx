import { useRef, useState } from "react";
import {
  Dimensions,
  ImageBackground,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  NativeScrollEvent,
  NativeSyntheticEvent,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth/AuthContext";
import { theme, spacing, radii } from "@/src/lib/theme";

const { width } = Dimensions.get("window");

type Slide = {
  title: string;
  text: string;
  image: string;
  highlight: { icon: keyof typeof import("@expo/vector-icons/Ionicons").default.glyphMap; label: string; color: string }[];
  disclaimer?: string;
};

const SLIDES: Slide[] = [
  {
    title: "La mer, ensemble.",
    text: "SignalMar, la communauté qui rend la navigation plus sûre, du Morbihan au large.",
    image: "https://images.unsplash.com/photo-1502784444187-359ac186c5bb?crop=entropy&cs=srgb&fm=jpg&q=85",
    highlight: [
      { icon: "people", label: "Plaisanciers", color: "#48CAE4" },
      { icon: "boat", label: "Pros", color: "#90E0EF" },
    ],
  },
  {
    title: "Signalez en 3 taps",
    text: "Autorités, OFNI, pollution, espèces protégées… L'information circule en temps réel entre marins.",
    image: "https://images.unsplash.com/photo-1473116763249-2faaef81ccda?crop=entropy&cs=srgb&fm=jpg&q=85",
    highlight: [
      { icon: "shield-checkmark", label: "Autorités", color: "#48CAE4" },
      { icon: "help-circle", label: "OFNI", color: "#E63946" },
      { icon: "water", label: "Pollution", color: "#9D4CDD" },
    ],
  },
  {
    title: "Sécurité d'abord",
    text: "Météo marine, bouton 1616 et coordonnées GPS toujours à portée — même en pleine tempête.",
    image: "https://images.unsplash.com/photo-1518837695005-2083093ee35b?crop=entropy&cs=srgb&fm=jpg&q=85",
    highlight: [
      { icon: "warning", label: "1616", color: "#E63946" },
      { icon: "partly-sunny", label: "Météo", color: "#F4A261" },
    ],
    disclaimer:
      "SignalMar n\u2019est qu\u2019une aide à l\u2019amélioration de la sécurité en mer. Elle ne remplace en aucun cas les cartes marines et ne se substitue pas à la plus grande vigilance du barreur et de son équipage.",
  },
];

export default function Welcome() {
  const { enterDemo } = useAuth();
  const router = useRouter();
  const [index, setIndex] = useState(0);
  const scrollRef = useRef<ScrollView | null>(null);

  function onScroll(e: NativeSyntheticEvent<NativeScrollEvent>) {
    const i = Math.round(e.nativeEvent.contentOffset.x / width);
    if (i !== index) setIndex(i);
  }

  function goNext() {
    if (index < SLIDES.length - 1) {
      scrollRef.current?.scrollTo({ x: (index + 1) * width, animated: true });
    }
  }

  function startDemo() {
    enterDemo();
    router.replace("/(tabs)/map");
  }

  return (
    <View style={styles.root}>
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
      >
        {SLIDES.map((s, i) => (
          <ImageBackground key={i} source={{ uri: s.image }} style={[styles.slide, { width }]}>
            <LinearGradient
              colors={["rgba(11,19,43,0.35)", "rgba(11,19,43,0.92)", "#0B132B"]}
              style={StyleSheet.absoluteFill}
              locations={[0, 0.6, 1]}
            />
            <SafeAreaView style={styles.slideSafe} edges={["top"]}>
              <View style={styles.brandRow}>
                <View style={styles.brandLogo}>
                  <Ionicons name="navigate" size={20} color={theme.bg} />
                </View>
                <Text style={styles.brandText}>SignalMar</Text>
              </View>
            </SafeAreaView>

            <View style={styles.slideBottom}>
              <View style={styles.chipRow}>
                {s.highlight.map((h, j) => (
                  <View key={j} style={[styles.chip, { borderColor: h.color }]}>
                    <Ionicons name={h.icon} size={14} color={h.color} />
                    <Text style={[styles.chipText, { color: h.color }]}>{h.label}</Text>
                  </View>
                ))}
              </View>
              <Text style={styles.title}>{s.title}</Text>
              <Text style={styles.subtitle}>{s.text}</Text>
              {s.disclaimer ? (
                <Text style={styles.disclaimer}>{s.disclaimer}</Text>
              ) : null}
            </View>
          </ImageBackground>
        ))}
      </ScrollView>

      <SafeAreaView edges={["bottom"]} style={styles.footer}>
        <View style={styles.dots}>
          {SLIDES.map((_, i) => (
            <View
              key={i}
              style={[styles.dot, i === index && styles.dotActive]}
            />
          ))}
        </View>
        {index < SLIDES.length - 1 ? (
          <TouchableOpacity style={styles.nextBtn} onPress={goNext} testID="onboarding-next">
            <Text style={styles.nextText}>Suivant</Text>
            <Ionicons name="arrow-forward" size={20} color={theme.bg} />
          </TouchableOpacity>
        ) : (
          <View style={{ gap: spacing.sm }}>
            <TouchableOpacity
              style={styles.demoVideo}
              onPress={() => router.push("/demo-autopilot")}
              testID="onboarding-autopilot"
            >
              <Ionicons name="play-circle" size={20} color="#F4A261" />
              <Text style={styles.demoVideoText}>Voir la démo (90 s)</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.primary} onPress={() => router.push("/(auth)/login")} testID="onboarding-login">
              <Ionicons name="phone-portrait" size={20} color={theme.bg} />
              <Text style={styles.primaryText}>Continuer avec mon téléphone</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.ghost} onPress={startDemo} testID="onboarding-demo">
              <Ionicons name="eye" size={18} color={theme.primary} />
              <Text style={styles.ghostText}>Découvrir en mode démo</Text>
            </TouchableOpacity>
            <Text style={styles.demoHint}>
              En démo, vous voyez uniquement les signalements de plus de 12h. Connectez-vous pour le temps réel.
            </Text>
          </View>
        )}
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  slide: { height: "70%", justifyContent: "space-between" },
  slideSafe: { padding: spacing.md },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  brandLogo: {
    width: 32, height: 32, borderRadius: 12, backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  brandText: { color: theme.text, fontWeight: "900", fontSize: 18, letterSpacing: -0.5 },
  slideBottom: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing.xl },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: radii.pill,
    borderWidth: 1, backgroundColor: "rgba(11,19,43,0.55)",
  },
  chipText: { fontWeight: "800", fontSize: 12 },
  title: { color: theme.text, fontSize: 32, fontWeight: "900", letterSpacing: -1, lineHeight: 36 },
  subtitle: { color: theme.textDim, fontSize: 15, lineHeight: 21 },
  disclaimer: {
    color: theme.textMute,
    fontSize: 11,
    fontStyle: "italic",
    lineHeight: 15,
    marginTop: 6,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "rgba(255,255,255,0.15)",
  },
  footer: { padding: spacing.lg, gap: spacing.md, backgroundColor: theme.bg },
  dots: { flexDirection: "row", justifyContent: "center", gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.bg3 },
  dotActive: { backgroundColor: theme.primary, width: 24 },
  nextBtn: {
    backgroundColor: theme.primary, paddingVertical: 16, borderRadius: radii.md,
    alignItems: "center", flexDirection: "row", justifyContent: "center", gap: 8, minHeight: 56,
  },
  nextText: { color: theme.bg, fontWeight: "900", fontSize: 17 },
  primary: {
    backgroundColor: theme.primary, paddingVertical: 16, borderRadius: radii.md,
    alignItems: "center", flexDirection: "row", justifyContent: "center", gap: 8, minHeight: 56,
  },
  primaryText: { color: theme.bg, fontWeight: "900", fontSize: 17 },
  secondary: {
    backgroundColor: theme.bg2, paddingVertical: 14, borderRadius: radii.md,
    alignItems: "center", borderWidth: 1, borderColor: theme.border, minHeight: 50,
    justifyContent: "center",
  },
  secondaryText: { color: theme.text, fontWeight: "800", fontSize: 15 },
  ghost: {
    paddingVertical: 12, alignItems: "center", flexDirection: "row",
    justifyContent: "center", gap: 6,
  },
  ghostText: { color: theme.primary, fontWeight: "700", fontSize: 14 },
  demoVideo: {
    paddingVertical: 13, borderRadius: radii.md, alignItems: "center", flexDirection: "row",
    justifyContent: "center", gap: 8, borderWidth: 1.5, borderColor: "#F4A261",
    backgroundColor: "rgba(244,162,97,0.10)", minHeight: 50,
  },
  demoVideoText: { color: "#F4A261", fontWeight: "800", fontSize: 15 },
  demoHint: { color: theme.textMute, fontSize: 11, textAlign: "center", lineHeight: 16 },
});
