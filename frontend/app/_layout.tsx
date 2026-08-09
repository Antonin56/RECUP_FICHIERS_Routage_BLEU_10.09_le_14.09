import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import Constants from "expo-constants";
import * as Linking from "expo-linking";
import { useEffect } from "react";
import { LogBox, NativeModules, Platform, StatusBar, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { AuthProvider } from "@/src/auth/AuthContext";
import { ToastHost } from "@/src/components/Toast";
import UpdateGate from "@/src/components/UpdateGate";
import { theme } from "@/src/lib/theme";
import { logger } from "@/src/lib/logger";
import { usePendingReferral } from "@/src/lib/referral-link";
import { startGpsWarmup } from "@/src/lib/gps-warmup";
import * as ScreenOrientation from "expo-screen-orientation";

// SHAKE-TO-OPEN-DEV-MENU (retour terrain 16/07/2026) : les chocs de vague
// déclenchent le menu dev Expo Go / dev-client en Android. On DÉSACTIVE la
// détection au boot — no-op en Expo Go (le menu Expo Go reste natif et ne
// peut pas être désactivé depuis JS) mais efficace en dev-client / prod.
try {
  const DS = (NativeModules as { DevSettings?: {
    setIsShakeToShowDevMenuEnabled?: (v: boolean) => void
  } }).DevSettings;
  DS?.setIsShakeToShowDevMenuEnabled?.(false);
} catch { /* best-effort */ }

LogBox.ignoreAllLogs(true);
SplashScreen.preventAutoHideAsync();

// Phase K.1 — Unlock screen rotation at runtime (Expo Go doesn't respect the
// `orientation: "default"` value in app.json for JS-driven apps, so we
// explicitly allow all rotations here). Enables landscape mode in nav on
// the water — the map + all overlays reflow via safe-area / flex layouts.
if (Platform.OS !== "web") {
  ScreenOrientation.unlockAsync().catch(() => { /* noop — best-effort */ });
}

// Démarrer le logger AU PLUS TÔT pour capturer console.* et les erreurs
// dès le boot — y compris pendant l'init de l'app.
logger.init().catch(() => { /* noop */ });

// PRÉCHAUFFAGE GPS (13/07/2026) — la puce GPS est mise en chauffe dès le
// lancement de l'app (position = cœur du produit) : dernière position connue
// instantanée + watcher haute précision. La carte affiche ainsi la position
// sans attendre un fix à froid (plusieurs minutes en mer sinon).
startGpsWarmup().catch(() => { /* best-effort */ });

// DIAGNOSTIC crash photo (14/07/2026) — sur Android, l'OS peut TUER
// l'activité de l'app pendant que la galerie/caméra est ouverte (pression
// mémoire). Au redémarrage, expo-image-picker conserve le résultat en
// attente : sa présence PROUVE ce scénario (≠ OOM de décodage). On le logge.
if (Platform.OS === "android") {
  import("expo-image-picker")
    .then((ImagePicker) => ImagePicker.getPendingResultAsync())
    .then((pending) => {
      if (Array.isArray(pending) ? pending.length > 0 : !!pending) {
        void logger.breadcrumb("report", "photo_step: RÉSULTAT PICKER EN ATTENTE après redémarrage (activité tuée par l'OS pendant la sélection)", {
          count: Array.isArray(pending) ? pending.length : 1,
        });
      }
    })
    .catch(() => { /* best-effort */ });
}

// ---------- Push setup (dev/production builds only) ------------------------
// `expo-notifications` remote push is REMOVED from Expo Go since SDK 53 : un
// import statique du module logge une ERROR à chaque boot Android Expo Go et
// la création de canal au niveau module pouvait échouer au démarrage. Tout
// est donc importé DYNAMIQUEMENT et ignoré dans Expo Go (les push n'y
// fonctionnent pas de toute façon).
const IS_EXPO_GO = Constants.appOwnership === "expo";

async function setupNotifications() {
  if (Platform.OS === "web" || IS_EXPO_GO) return null;
  try {
    const Notifications = await import("expo-notifications");
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      }),
    });
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "Default",
        importance: Notifications.AndroidImportance.MAX,
        sound: "default",
      });
    }
    return Notifications;
  } catch {
    return null; // best-effort — jamais bloquant au boot
  }
}

export default function RootLayout() {
  const [loaded, error] = useIconFonts();
  const router = useRouter();

  // Phase B — Capture the ?ref=CODE / /i/CODE from any deep-link the OS
  // hands us (cold-start or warm resume), and stash it in AsyncStorage
  // so registration can attribute the parrainage even if the user
  // takes a while to finish signup.
  usePendingReferral();

  useEffect(() => {
    if (loaded || error) {
      SplashScreen.hideAsync();
    }
  }, [loaded, error]);

  // Push tap handlers (warm + cold-start) — dev/production builds only.
  useEffect(() => {
    if (Platform.OS === "web" || IS_EXPO_GO) return;

    let tapSub: { remove: () => void } | null = null;
    let cancelled = false;

    const handleResponse = (response: {
      notification: { request: { content: { data?: Record<string, unknown> } } };
    } | null) => {
      if (!response) return;
      const data = (response.notification.request.content.data || {}) as {
        deeplink?: string;
        action_url?: string;
      };
      const url = data.deeplink || data.action_url;
      if (!url) return;
      if (url.startsWith("http")) Linking.openURL(url);
      else router.push(url as never);
    };

    setupNotifications().then((Notifications) => {
      if (!Notifications || cancelled) return;
      tapSub = Notifications.addNotificationResponseReceivedListener(handleResponse);
      Notifications.getLastNotificationResponseAsync().then(handleResponse).catch(() => {});
    });

    return () => {
      cancelled = true;
      tapSub?.remove();
    };
  }, [router]);

  if (!loaded && !error) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <KeyboardProvider>
          <View style={{ flex: 1, backgroundColor: theme.bg }}>
            <StatusBar barStyle="light-content" backgroundColor={theme.bg} />
            <AuthProvider>
              <ToastHost>
                <Stack
                  screenOptions={{
                    headerShown: false,
                    contentStyle: { backgroundColor: theme.bg },
                    animation: "fade",
                  }}
                />
                {/* Détection de MAJ store au lancement (15/07/2026). */}
                <UpdateGate />
              </ToastHost>
            </AuthProvider>
          </View>
        </KeyboardProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
