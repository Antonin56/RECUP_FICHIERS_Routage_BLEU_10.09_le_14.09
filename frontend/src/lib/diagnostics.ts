// SignalMar — Collecte d'un instantané système pour le diagnostic.
//
// Fonctions :
//   • snapshot()      → état réseau + GPS + app + backend
//   • pingBackend()   → mesure latence + statut HTTP
//
// Aucun stockage : tout est calculé à la demande.

import * as Application from "expo-application";
import * as Device from "expo-device";
import * as Location from "expo-location";
import NetInfo from "@react-native-community/netinfo";
import { Platform } from "react-native";

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

export interface DiagnosticSnapshot {
  collectedAt: string;
  app: {
    name: string;
    version: string | null;
    build: string | null;
    bundleId: string | null;
  };
  device: {
    platform: string;
    osVersion: string | number | null;
    brand: string | null;
    modelName: string | null;
  };
  network: {
    isConnected: boolean | null;
    isInternetReachable: boolean | null;
    type: string | null;
    details: Record<string, unknown> | null;
  };
  gps: {
    permission: string | null;
    servicesEnabled: boolean | null;
    lastFix: {
      lat: number;
      lng: number;
      accuracyM: number | null;
      ageS: number | null;
      speedMs: number | null;
      heading: number | null;
    } | null;
    error: string | null;
  };
  backend: {
    url: string;
  };
}

export async function snapshot(): Promise<DiagnosticSnapshot> {
  const [net, perm, services] = await Promise.all([
    NetInfo.fetch().catch(() => null),
    Location.getForegroundPermissionsAsync().catch(() => null),
    Location.hasServicesEnabledAsync().catch(() => null),
  ]);

  let gpsFix: DiagnosticSnapshot["gps"]["lastFix"] = null;
  let gpsErr: string | null = null;
  if (perm?.granted) {
    try {
      const pos = await Location.getLastKnownPositionAsync({
        maxAge: 60_000,
        requiredAccuracy: 200,
      });
      if (pos) {
        gpsFix = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracyM: pos.coords.accuracy ?? null,
          ageS: pos.timestamp ? Math.round((Date.now() - pos.timestamp) / 1000) : null,
          speedMs: typeof pos.coords.speed === "number" ? pos.coords.speed : null,
          heading: typeof pos.coords.heading === "number" ? pos.coords.heading : null,
        };
      } else {
        gpsErr = "no_last_known_position";
      }
    } catch (e) {
      gpsErr = e instanceof Error ? e.message : "unknown_gps_error";
    }
  }

  return {
    collectedAt: new Date().toISOString(),
    app: {
      name: Application.applicationName ?? "SignalMar",
      version: Application.nativeApplicationVersion,
      build: Application.nativeBuildVersion,
      bundleId: Application.applicationId,
    },
    device: {
      platform: Platform.OS,
      osVersion: Platform.Version ?? null,
      brand: Device.brand ?? null,
      modelName: Device.modelName ?? null,
    },
    network: {
      isConnected: net?.isConnected ?? null,
      isInternetReachable: net?.isInternetReachable ?? null,
      type: net?.type ?? null,
      details: (net?.details as Record<string, unknown> | null) ?? null,
    },
    gps: {
      permission: perm?.status ?? null,
      servicesEnabled: services ?? null,
      lastFix: gpsFix,
      error: gpsErr,
    },
    backend: {
      url: BACKEND_URL,
    },
  };
}

export interface PingResult {
  ok: boolean;
  status: number | null;
  latencyMs: number;
  error: string | null;
}

export async function pingBackend(): Promise<PingResult> {
  const start = Date.now();
  try {
    const res = await fetch(`${BACKEND_URL}/api/diagnostics/ping`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    return {
      ok: res.ok,
      status: res.status,
      latencyMs: Date.now() - start,
      error: res.ok ? null : `HTTP ${res.status}`,
    };
  } catch (e) {
    return {
      ok: false,
      status: null,
      latencyMs: Date.now() - start,
      error: e instanceof Error ? e.message : "unknown_error",
    };
  }
}
