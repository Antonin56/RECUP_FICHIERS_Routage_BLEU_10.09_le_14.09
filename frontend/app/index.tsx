import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View, Text, Image } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth/AuthContext";
import { theme } from "@/src/lib/theme";

export default function Index() {
  const { user, loading, demoMode } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (user || demoMode) router.replace("/(tabs)/map");
    else router.replace("/(auth)/welcome");
  }, [loading, user, demoMode, router]);

  return (
    <View style={styles.container} testID="splash-screen">
      <Image
        source={require("../assets/images/icon.png")}
        style={styles.logo}
        resizeMode="contain"
      />
      <Text style={styles.title}>SignalMar</Text>
      <Text style={styles.subtitle}>Signalement collaboratif en mer</Text>
      <ActivityIndicator color={theme.primary} style={{ marginTop: 24 }} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.bg,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  logo: { width: 120, height: 120, marginBottom: 12 },
  title: { color: theme.text, fontSize: 36, fontWeight: "900", letterSpacing: -1 },
  subtitle: { color: theme.textDim, fontSize: 14, marginTop: 6 },
});
