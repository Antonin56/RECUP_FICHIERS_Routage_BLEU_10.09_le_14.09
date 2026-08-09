import { Platform } from "react-native";
import Constants from "expo-constants";
import * as Device from "expo-device";

import { api } from "@/src/api/client";

/**
 * Register the device for push notifications via the Emergent relay.
 * Safe to call on every app open and login; failures are swallowed.
 * No-op on web and Expo Go.
 *
 * IMPORTANT: `expo-notifications` is imported DYNAMICALLY. Since SDK 53 the
 * remote-push module is removed from Expo Go on Android and a top-level
 * `import * as Notifications` throws an ERROR at bundle-evaluation time on
 * every Expo Go launch (this file is pulled in by AuthContext → login).
 * Lazy-loading it only when we actually can register keeps Expo Go clean;
 * real dev/production builds are unaffected.
 */
export async function registerForPush(user_id: string): Promise<void> {
  if (Platform.OS === "web") return;
  if (!Device.isDevice) return; // simulators/emulators don't get tokens
  // Expo Go cannot receive remote push since SDK 53 → skip entirely.
  if (Constants.appOwnership === "expo") return;

  try {
    const Notifications = await import("expo-notifications");
    const existing = await Notifications.getPermissionsAsync();
    let status = existing.status;
    if (status !== "granted") {
      const req = await Notifications.requestPermissionsAsync();
      status = req.status;
    }
    if (status !== "granted") return;

    const tokenResp = await Notifications.getDevicePushTokenAsync();
    if (!tokenResp?.data) return;

    await api.registerPush(user_id, Platform.OS, String(tokenResp.data));
  } catch (e) {
    if (__DEV__) console.warn("push registration skipped:", e);
  }
}
