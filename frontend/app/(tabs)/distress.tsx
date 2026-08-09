import { useEffect, useRef, useState } from "react";
import {
  Animated,
  Easing,
  Linking,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";

import { theme, spacing, radii } from "@/src/lib/theme";
import { toDMS, toDecimal } from "@/src/lib/coords";
import { showToast } from "@/src/components/Toast";

const EMERGENCY_NUMBERS = [
  { label: "CROSS / Secours en mer", number: "1616", priority: true },
  { label: "VHF Canal 16", number: "16", note: "Veille internationale" },
  { label: "SAMU", number: "15" },
  { label: "Pompiers", number: "18" },
  { label: "Numéro européen", number: "112" },
];

export default function DistressScreen() {
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [counting, setCounting] = useState(false);
  const [count, setCount] = useState(5);
  const pulse = useRef(new Animated.Value(0)).current;
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const perm = await Location.requestForegroundPermissionsAsync();
        if (perm.status !== "granted") return;
        const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        // refresh periodically
        const sub = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.Balanced, distanceInterval: 5, timeInterval: 5000 },
          (p) => setCoords({ lat: p.coords.latitude, lng: p.coords.longitude }),
        );
        return () => sub.remove();
      } catch {
        /* ignore */
      }
    })();
  }, []);

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 1100, useNativeDriver: true, easing: Easing.out(Easing.quad) }),
        Animated.timing(pulse, { toValue: 0, duration: 1100, useNativeDriver: true, easing: Easing.in(Easing.quad) }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  function doCall(num: string) {
    const url = Platform.OS === "web" ? `tel:${num}` : `tel:${num}`;
    Linking.canOpenURL(url)
      .then((ok) => {
        if (ok) Linking.openURL(url);
        else showToast("error", `Impossible d'appeler le ${num} sur cet appareil`);
      })
      .catch(() => showToast("error", "Appel impossible"));
  }

  function startCountdown() {
    if (counting) return;
    setCounting(true);
    setCount(5);
    timerRef.current = setInterval(() => {
      setCount((c) => {
        if (c <= 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          setCounting(false);
          doCall("1616");
          return 0;
        }
        return c - 1;
      });
    }, 1000);
  }

  function cancel() {
    if (timerRef.current) clearInterval(timerRef.current);
    setCounting(false);
    setCount(5);
  }

  const scale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.18] });
  const opacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.55, 0] });

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.header}>
          <Ionicons name="warning" size={28} color={theme.danger} />
          <View>
            <Text style={styles.title}>Détresse en mer</Text>
            <Text style={styles.sub}>Restez calme, voici l&apos;aide la plus proche.</Text>
          </View>
        </View>

        <View style={styles.gpsCard} testID="distress-gps-card">
          <Text style={styles.gpsLabel}>POSITION ACTUELLE</Text>
          {coords ? (
            <>
              <Text style={styles.gpsDecimal}>{toDecimal(coords.lat)}  /  {toDecimal(coords.lng)}</Text>
              <View style={styles.dmsRow}>
                <Text style={styles.dmsText}>{toDMS(coords.lat, true)}</Text>
                <Text style={styles.dmsText}>{toDMS(coords.lng, false)}</Text>
              </View>
            </>
          ) : (
            <Text style={styles.gpsLoading}>Acquisition GPS en cours…</Text>
          )}
        </View>

        <View style={styles.bigButtonWrap}>
          <Animated.View
            pointerEvents="none"
            style={[styles.pulse, { transform: [{ scale }], opacity }]}
          />
          <TouchableOpacity
            style={[styles.bigButton, counting && { backgroundColor: theme.dangerDark }]}
            activeOpacity={0.9}
            onPress={counting ? cancel : startCountdown}
            testID="distress-call-button"
          >
            {counting ? (
              <>
                <Text style={styles.bigCount}>{count}</Text>
                <Text style={styles.bigLabel}>Toucher pour annuler</Text>
              </>
            ) : (
              <>
                <Ionicons name="call" size={44} color="#fff" />
                <Text style={styles.bigLabel}>APPELER LE 1616</Text>
                <Text style={styles.bigHint}>(5s avant l&apos;appel)</Text>
              </>
            )}
          </TouchableOpacity>
        </View>

        <Text style={styles.sectionTitle}>Autres numéros d&apos;urgence</Text>
        <View style={{ gap: spacing.sm }}>
          {EMERGENCY_NUMBERS.map((n) => (
            <TouchableOpacity
              key={n.number + n.label}
              style={[styles.numRow, n.priority && styles.numRowPriority]}
              onPress={() => doCall(n.number)}
              testID={`distress-call-${n.number}`}
            >
              <View style={styles.numBox}>
                <Text style={styles.numText}>{n.number}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.numLabel}>{n.label}</Text>
                {n.note && <Text style={styles.numNote}>{n.note}</Text>}
              </View>
              <Ionicons name="call-outline" size={22} color={theme.text} />
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  scroll: { padding: spacing.md, gap: spacing.lg, paddingBottom: spacing.xxl },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm },
  title: { color: theme.text, fontSize: 26, fontWeight: "900", letterSpacing: -0.5 },
  sub: { color: theme.textDim, fontSize: 13 },
  gpsCard: {
    backgroundColor: theme.bg2, padding: spacing.lg, borderRadius: radii.lg,
    borderWidth: 2, borderColor: theme.danger, alignItems: "center", gap: 8,
  },
  gpsLabel: { color: theme.danger, fontWeight: "800", fontSize: 12, letterSpacing: 2 },
  gpsDecimal: { color: theme.text, fontSize: 26, fontWeight: "900", textAlign: "center" },
  dmsRow: { flexDirection: "row", gap: spacing.md, flexWrap: "wrap", justifyContent: "center" },
  dmsText: { color: theme.textDim, fontSize: 15, fontWeight: "700" },
  gpsLoading: { color: theme.textDim, fontSize: 16, fontWeight: "700" },
  bigButtonWrap: { alignItems: "center", justifyContent: "center", marginTop: spacing.md },
  pulse: {
    position: "absolute", width: 240, height: 240, borderRadius: 120, backgroundColor: theme.danger,
  },
  bigButton: {
    width: 240, height: 240, borderRadius: 120, backgroundColor: theme.danger,
    alignItems: "center", justifyContent: "center",
    shadowColor: theme.danger, shadowOpacity: 0.6, shadowRadius: 22, shadowOffset: { width: 0, height: 10 },
    elevation: 16, gap: 6,
  },
  bigLabel: { color: "#fff", fontWeight: "900", fontSize: 18, letterSpacing: 0.5 },
  bigHint: { color: "rgba(255,255,255,0.85)", fontSize: 12, marginTop: 2 },
  bigCount: { color: "#fff", fontWeight: "900", fontSize: 88, lineHeight: 100 },
  sectionTitle: {
    color: theme.textDim, fontWeight: "800", fontSize: 12, letterSpacing: 2,
    marginTop: spacing.md, textTransform: "uppercase",
  },
  numRow: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    borderWidth: 1, borderColor: theme.border, minHeight: 64,
  },
  numRowPriority: { borderColor: theme.danger, backgroundColor: "rgba(230,57,70,0.12)" },
  numBox: {
    backgroundColor: theme.bg3, paddingHorizontal: 14, paddingVertical: 6,
    borderRadius: radii.sm, minWidth: 64, alignItems: "center",
  },
  numText: { color: theme.primary, fontWeight: "900", fontSize: 16 },
  numLabel: { color: theme.text, fontWeight: "700", fontSize: 15 },
  numNote: { color: theme.textDim, fontSize: 12, marginTop: 2 },
});
