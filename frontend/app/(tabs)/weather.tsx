import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";

import { api, type WeatherResponse } from "@/src/api/client";
import { TideCard } from "@/src/components/TideCard";
import { theme, spacing, radii } from "@/src/lib/theme";

const SEVERITY_STYLE = {
  danger: { border: theme.danger, icon: "warning", bg: "rgba(230,57,70,0.12)" },
  warning: { border: theme.warning, icon: "alert", bg: "rgba(244,162,97,0.12)" },
  info: { border: theme.primary, icon: "information-circle", bg: "rgba(72,202,228,0.08)" },
} as const;

export default function WeatherScreen() {
  const [data, setData] = useState<WeatherResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      let c = coords;
      if (!c && perm.status === "granted") {
        const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        c = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setCoords(c);
      }
      const target = c ?? { lat: 43.2965, lng: 5.3698 };
      const w = await api.weather(target.lat, target.lng);
      setData(w);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [coords]);

  useEffect(() => { load(); }, [load]);

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(); }}
            tintColor={theme.primary}
          />
        }
      >
        <View style={styles.header}>
          <Text style={styles.title}>Météo marine</Text>
          <Text style={styles.sub}>
            {coords
              ? `Position ${coords.lat.toFixed(3)}°, ${coords.lng.toFixed(3)}°`
              : "Localisation par défaut"}
          </Text>
        </View>

        {loading ? (
          <ActivityIndicator color={theme.primary} style={{ marginTop: 40 }} />
        ) : (
          <>
            <View style={styles.grid}>
              <Tile
                icon="thermometer"
                value={`${data?.current.temperature ?? "—"}°`}
                label="Température"
              />
              <Tile
                icon="leaf"
                value={`${data?.current.wind_speed_kn ?? "—"} kn`}
                label="Vent"
              />
              <Tile
                icon="flash"
                value={`${data?.current.wind_gust_kn ?? "—"} kn`}
                label="Rafales"
              />
              <Tile
                icon="water"
                value={`${data?.current.wave_height_m ?? "—"} m`}
                label="Vagues"
              />
              <Tile
                icon="repeat"
                value={`${data?.current.wave_period_s ?? "—"} s`}
                label="Période"
              />
              <Tile
                icon="compass"
                value={`${data?.current.wind_direction ?? "—"}°`}
                label="Direction"
              />
            </View>

            <Text style={styles.sectionTitle}>Marées</Text>
            <TideCard coords={coords} />

            <Text style={styles.sectionTitle}>Alertes</Text>
            <View style={{ gap: spacing.sm }}>
              {(data?.alerts ?? []).map((a, i) => {
                const sty = SEVERITY_STYLE[a.severity];
                return (
                  <View
                    key={i}
                    style={[styles.alert, { borderLeftColor: sty.border, backgroundColor: sty.bg }]}
                    testID={`weather-alert-${a.severity}`}
                  >
                    <Ionicons name={sty.icon as never} size={22} color={sty.border} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.alertTitle}>{a.title}</Text>
                      <Text style={styles.alertDesc}>{a.description}</Text>
                    </View>
                  </View>
                );
              })}
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Tile({ icon, value, label }: { icon: string; value: string; label: string }) {
  return (
    <View style={styles.tile}>
      <Ionicons name={icon as never} size={20} color={theme.primary} />
      <Text style={styles.tileValue}>{value}</Text>
      <Text style={styles.tileLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  scroll: { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xxl },
  header: { gap: 4, marginTop: spacing.sm },
  title: { color: theme.text, fontSize: 28, fontWeight: "900", letterSpacing: -0.5 },
  sub: { color: theme.textDim, fontSize: 13 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  tile: {
    backgroundColor: theme.bg2, padding: spacing.md, borderRadius: radii.md,
    flexBasis: "31%", flexGrow: 1, gap: 4, alignItems: "flex-start",
    borderWidth: 1, borderColor: theme.border,
  },
  tileValue: { color: theme.text, fontWeight: "900", fontSize: 20 },
  tileLabel: { color: theme.textDim, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 },
  sectionTitle: {
    color: theme.textDim, fontWeight: "800", fontSize: 12, letterSpacing: 2,
    marginTop: spacing.md, textTransform: "uppercase",
  },
  alert: {
    padding: spacing.md, borderRadius: radii.md, borderLeftWidth: 4,
    flexDirection: "row", gap: spacing.sm, alignItems: "center",
  },
  alertTitle: { color: theme.text, fontWeight: "800", fontSize: 15 },
  alertDesc: { color: theme.textDim, fontSize: 13, marginTop: 2 },
});
