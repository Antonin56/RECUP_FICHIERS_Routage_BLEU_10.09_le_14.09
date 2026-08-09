import { Tabs, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef } from "react";
import { ActivityIndicator, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { logger } from "@/src/lib/logger";
import { theme } from "@/src/lib/theme";

export default function TabsLayout() {
  const { user, loading, demoMode } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  // Auto-redirect on pending invitations happens ONCE per session per
  // user_id — we don't want to re-hijack navigation every time the tab
  // layout re-mounts. The last uid we checked is stored in a ref so the
  // effect stays cheap.
  const invitationCheckedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!loading && !user && !demoMode) router.replace("/(auth)/welcome");
  }, [user, loading, demoMode, router]);

  // Phase 4.2b — Right after the user is authenticated, silently poll
  // /invitations/mine. If at least one pending invitation exists we
  // hop to /groups so the user lands on the "Rejoindre / Décliner"
  // cards without having to search for them. Demo users never hit
  // this — the endpoint requires a real JWT.
  useEffect(() => {
    if (loading || !user || demoMode) return;
    if (invitationCheckedFor.current === user.user_id) return;
    invitationCheckedFor.current = user.user_id;
    (async () => {
      try {
        const { invitations } = await api.invitationsMine();
        if (invitations.length > 0) {
          logger.event("app", "auto_redirect_to_invitations", {
            count: invitations.length,
          });
          router.push("/groups");
        }
      } catch {
        /* silent — this is a nice-to-have; do not interrupt onboarding */
      }
    })();
  }, [user, loading, demoMode, router]);

  if (loading || (!user && !demoMode)) {
    return (
      <View style={{ flex: 1, backgroundColor: theme.bg, justifyContent: "center" }}>
        <ActivityIndicator color={theme.primary} />
      </View>
    );
  }

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.primary,
        tabBarInactiveTintColor: theme.textMute,
        tabBarStyle: {
          backgroundColor: theme.bg2,
          borderTopColor: theme.border,
          borderTopWidth: 1,
          height: 60 + insets.bottom,
          paddingBottom: insets.bottom + 6,
          paddingTop: 8,
        },
        tabBarLabelStyle: { fontWeight: "700", fontSize: 11 },
        sceneStyle: { backgroundColor: theme.bg },
      }}
    >
      <Tabs.Screen
        name="map"
        options={{
          title: "Carte",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="map" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="weather"
        options={{
          title: "Météo",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="partly-sunny" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="distress"
        options={{
          title: "Détresse",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="warning" color={theme.danger} size={size + 4} />
          ),
          tabBarLabelStyle: { color: theme.danger, fontWeight: "900", fontSize: 11 },
        }}
      />
      <Tabs.Screen
        name="safety"
        options={{
          title: "Sécurité",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="shield-checkmark" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: "Profil",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="person-circle" color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}
