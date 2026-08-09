/**
 * Phase E.5 — Adaptive reports polling
 *
 * Refreshes the shared reports list at a cadence that adapts to the user's
 * boat speed and application lifecycle. Guarantees:
 *
 *  - Interval schedule (validated by the product owner):
 *      • boat stopped (< 1 kn)          → 90 s
 *      • slow navigation (1-5 kn)       → 60 s
 *      • fast navigation (> 5 kn)       → 30 s
 *  - Immediate refresh whenever the user's GPS jumps > 100 m (they entered
 *    a new zone → force a fetch even if the timer hasn't fired).
 *  - Polling pauses when the app is backgrounded (AppState !== "active")
 *    and resumes immediately on foreground.
 *  - The caller supplies the actual fetch function and receives:
 *      • `newCount`  → how many *new* reports appeared since the last poll
 *      • `lastAt`    → the timestamp of the most recent successful refresh
 *      • `refresh()` → imperative manual refresh (also resets the timer)
 *      • `isRefreshing` → true during a fetch (for UI indicators)
 *
 * The hook is fully cross-platform (uses only `AppState` + `setInterval`),
 * so it works in Expo Go / dev builds without any native module.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";

// Speed thresholds in **knots** (bateau vitesse en nds).
// GPS speed is delivered in m/s; we convert on the fly (1 kn ≈ 0.5144 m/s).
const KN_STOP = 1;
const KN_FAST = 5;
const MS_PER_KN = 0.5144;

// Polling intervals (ms) — validated by the product owner (option 🐢).
export const POLL_STOPPED_MS = 90_000;
export const POLL_SLOW_MS = 60_000;
export const POLL_FAST_MS = 30_000;

// Distance (m) beyond which we consider the user has moved into a new zone
// and immediately fetch — even if the interval hasn't elapsed yet.
const ZONE_CHANGE_M = 100;

/** Great-circle distance in metres (Haversine — simplified, ok for < 5 km). */
function distMeters(
  a: { lat: number; lng: number } | null,
  b: { lat: number; lng: number } | null,
): number {
  if (!a || !b) return Infinity;
  const R = 6371000;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((a.lat * Math.PI) / 180) *
      Math.cos((b.lat * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

/** Convert boat speed (m/s from GPS) to the appropriate poll interval. */
export function pollIntervalForSpeed(speedMs: number | null | undefined): number {
  if (speedMs == null || Number.isNaN(speedMs)) return POLL_STOPPED_MS;
  const kn = speedMs / MS_PER_KN;
  if (kn < KN_STOP) return POLL_STOPPED_MS;
  if (kn <= KN_FAST) return POLL_SLOW_MS;
  return POLL_FAST_MS;
}

export interface AdaptivePollingOptions<T extends { id: string }> {
  /** Enabled = polling active; toggling to false stops any pending timer. */
  enabled: boolean;
  /** Current boat speed in m/s (from `Location.watchPositionAsync`). */
  speedMs: number | null | undefined;
  /** Current user position; a > 100 m jump triggers an immediate refresh. */
  userLoc: { lat: number; lng: number } | null;
  /** Current in-memory reports list — used to compute "N new" deltas. */
  currentIds: Set<string>;
  /** Callback that must perform the fetch + update state; MUST return the
   *  freshly fetched list so we can diff it against `currentIds`. */
  fetcher: () => Promise<T[]>;
  /** Optional callback fired when N new reports have been detected. */
  onNewReports?: (newItems: T[]) => void;
}

export interface AdaptivePollingState {
  /** Timestamp (ms) of the last successful fetch, null if never. */
  lastAt: number | null;
  /** How many new reports since the last fetch (reset when `dismiss()` is called). */
  newCount: number;
  /** True while a fetch is in-flight (spinner + disable manual button). */
  isRefreshing: boolean;
  /** Currently used interval in ms — for debugging/UI. */
  intervalMs: number;
  /** Manually trigger a refresh. Resets the timer + `newCount`. */
  refresh: () => Promise<void>;
  /** Dismiss the "N new" banner without triggering a refresh. */
  dismissNewCount: () => void;
}

export function useAdaptiveReportsPolling<T extends { id: string }>(
  opts: AdaptivePollingOptions<T>,
): AdaptivePollingState {
  const { enabled, speedMs, userLoc, currentIds, fetcher, onNewReports } = opts;

  const [lastAt, setLastAt] = useState<number | null>(null);
  const [newCount, setNewCount] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [intervalMs, setIntervalMs] = useState(() => pollIntervalForSpeed(speedMs));
  const [appActive, setAppActive] = useState(
    () => AppState.currentState === "active",
  );

  // Refs used inside timer callbacks so we always read fresh values without
  // triggering re-renders of the timer itself.
  const currentIdsRef = useRef(currentIds);
  useEffect(() => { currentIdsRef.current = currentIds; }, [currentIds]);
  const fetcherRef = useRef(fetcher);
  useEffect(() => { fetcherRef.current = fetcher; }, [fetcher]);
  const onNewReportsRef = useRef(onNewReports);
  useEffect(() => { onNewReportsRef.current = onNewReports; }, [onNewReports]);
  const lastLocRef = useRef<typeof userLoc>(userLoc);
  const inFlightRef = useRef(false);

  // Track AppState so we pause polling in background.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s: AppStateStatus) => {
      setAppActive(s === "active");
    });
    return () => sub.remove();
  }, []);

  // Update interval whenever speed changes.
  useEffect(() => {
    setIntervalMs(pollIntervalForSpeed(speedMs));
  }, [speedMs]);

  // Core refresh routine — deduplicated (no overlapping fetches).
  const doRefresh = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setIsRefreshing(true);
    try {
      const fresh = await fetcherRef.current();
      const prevIds = currentIdsRef.current;
      const added = fresh.filter((r) => !prevIds.has(r.id));
      if (added.length > 0) {
        setNewCount((n) => n + added.length);
        try { onNewReportsRef.current?.(added); } catch { /* swallow */ }
      }
      setLastAt(Date.now());
    } catch {
      // Errors are the caller's responsibility (offline banner, toast, etc.);
      // we just keep the last successful `lastAt` untouched.
    } finally {
      setIsRefreshing(false);
      inFlightRef.current = false;
    }
  }, []);

  // Immediate refresh on > 100 m GPS jump (zone change).
  useEffect(() => {
    if (!enabled || !appActive) {
      lastLocRef.current = userLoc;
      return;
    }
    const d = distMeters(lastLocRef.current, userLoc);
    if (userLoc && d > ZONE_CHANGE_M) {
      lastLocRef.current = userLoc;
      void doRefresh();
    } else if (userLoc && !lastLocRef.current) {
      // Initialise anchor without triggering a refresh.
      lastLocRef.current = userLoc;
    }
  }, [userLoc, enabled, appActive, doRefresh]);

  // Interval-based polling. Recreated whenever inputs change so we always
  // schedule the *current* interval (speed-adaptive).
  useEffect(() => {
    if (!enabled || !appActive) return;
    const t = setInterval(doRefresh, intervalMs);
    return () => clearInterval(t);
  }, [enabled, appActive, intervalMs, doRefresh]);

  const refresh = useCallback(async () => {
    setNewCount(0);
    await doRefresh();
  }, [doRefresh]);

  const dismissNewCount = useCallback(() => setNewCount(0), []);

  return { lastAt, newCount, isRefreshing, intervalMs, refresh, dismissNewCount };
}

/** Format "il y a Xs / X min" from a timestamp (ms). */
export function formatLastRefresh(ts: number | null, now: number = Date.now()): string {
  if (ts == null) return "jamais";
  const s = Math.max(0, Math.floor((now - ts) / 1000));
  if (s < 5) return "à l'instant";
  if (s < 60) return `il y a ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `il y a ${m} min`;
  const h = Math.floor(m / 60);
  return `il y a ${h}h`;
}
