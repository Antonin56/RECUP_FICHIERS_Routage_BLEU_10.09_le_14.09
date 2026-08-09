import { useEffect, useRef, useState, useCallback } from "react";
import {
  ActivityIndicator,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import Slider from "@react-native-community/slider";
import { useRouter, useFocusEffect, useLocalSearchParams } from "expo-router";
import * as Location from "expo-location";
import * as Haptics from "expo-haptics";

import { MarineMap, type MarineMapHandle } from "@/src/components/MarineMap";
import { api, type ReportItem } from "@/src/api/client";
import { theme, spacing, radii } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";
import { REPORT_TYPES, TYPE_BY_ID, type ReportTypeId } from "@/src/lib/report-types";
import { useAuth } from "@/src/auth/AuthContext";
import { saveReportsCache, loadReportsCache } from "@/src/lib/reports-cache";
import { consumeLastCreated } from "@/src/lib/last-created";
import { useVoiceSettings } from "@/src/lib/voice-settings";
import { useSoundAlertWatcher } from "@/src/lib/sound-alert";
import { getWarmLocation, startGpsWarmup } from "@/src/lib/gps-warmup";
import { vibrateAlert, stopAlertFeedback } from "@/src/lib/alert-vibration";
import { playAlertHorn, stopAlertHorn } from "@/src/lib/alert-sound";
import { useProximityConfirm } from "@/src/lib/proximity-confirm";
import { ProximityConfirmCard } from "@/src/components/ProximityConfirmCard";
import { AlertSettingsPanel, ZoneField, NAV_SLIDER_MAX_KM, NAV_INPUT_MAX_KM } from "@/src/components/AlertSettingsPanel";
import { SpeedometerOverlay } from "@/src/components/SpeedometerOverlay";
import { DraggableZoomButtons } from "@/src/components/DraggableZoomButtons";
import { storage } from "@/src/utils/storage";
import { logger } from "@/src/lib/logger";
import { formatDM } from "@/src/lib/coords";
import { CoordsPopup } from "@/src/components/CoordsPopup";
import {
  useAdaptiveReportsPolling,
  formatLastRefresh,
} from "@/src/lib/adaptive-polling";
import NetInfo from "@react-native-community/netinfo";
import { useMapUnit } from "@/src/lib/map-unit";

// Default centre: between the Golfe du Morbihan and Belle-Île.
const DEFAULT_CENTER = { lat: 47.46, lng: -2.92 };
// Rayon d'AFFICHAGE des signalements (fixe, interne). L'ancien bouton
// « 200 km » en haut de la carte a été supprimé (10/07/2026) : il créait
// une confusion avec la Zone de veille. Tous les signalements dans ce
// rayon restent visibles ; seule la Zone de veille déclenche les alertes.
const DISPLAY_RADIUS_KM = 200;
// Bascule AUTO Vigie ⇄ Navigation (11/07/2026) : le mode suit le bateau.
// ≥ 3 km/h maintenu 5 s → Navigation ; < 3 km/h maintenu 5 s → Vigie.
const AUTO_SWITCH_SPEED_MS = 3 / 3.6; // 3 km/h en m/s
const AUTO_SWITCH_SUSTAIN_MS = 5_000;
// Phase K — Navigation cone defaults & bounds.
const CONE_ANGLE_DEFAULT = 45;   // total spread in degrees (half-angle = 22.5)
const CONE_ANGLE_MIN = 5;
const CONE_ANGLE_MAX = 90;
// Longueur du cône Navigation = Zone de veille Navigation (valeur fixe
// choisie par l'utilisateur — l'ancienne formule vitesse × 10 min a été
// remplacée le 10/07/2026 : « Simple, sans ambiguïté »).

// Phase 3c — Welcome banner is shown only ONCE per app boot (JS session).
// The module-level flag is reset when the JS engine reloads, so a full
// close/reopen of the app is required to see it again. This matches the
// user's requirement: "uniquement au 1er chargement".
let welcomeBannerShownInSession = false;

export default function MapScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  // Paysage (12/07) : la colonne d'icônes de droite monte haut — on décale
  // les pills du haut vers la gauche pour leur laisser un couloir dédié.
  const { width: winW, height: winH } = useWindowDimensions();
  const isLandscape = winW > winH;
  const { demoMode, user } = useAuth();
  const mapRef = useRef<MarineMapHandle>(null);
  const shiftParams = useLocalSearchParams<{
    shift_report_id?: string;
    shift_lat?: string;
    shift_lng?: string;
    /** When set, switch to author-direct-edit mode (no community vote). */
    shift_author?: string;
    /** When set, the map highlights this marker with a glowing halo. */
    focus_id?: string;
    focus_lat?: string;
    focus_lng?: string;
  }>();

  const [userLoc, setUserLoc] = useState<{ lat: number; lng: number } | null>(null);
  // 16/07/2026 — unité d'affichage des échelles (km / NM), persistée locale.
  const { unit: mapUnit, setUnit: setMapUnit } = useMapUnit();
  const [unitPickerOpen, setUnitPickerOpen] = useState(false);
  // Phase I — Navigation projection: cap (heading 0-360°) + vitesse (nœuds)
  // mis à jour en continu via expo-location. Servent à dessiner la flèche
  // rouge orientée + la ligne rouge de projection devant le bateau.
  const [userHeading, setUserHeading] = useState<number | null>(null);
  const [userSpeed, setUserSpeed] = useState<number | null>(null);
  // Toggle: when ON, the boat marker + projection line are shown on the
  // map AND continuous GPS tracking starts. Default OFF — the user has to
  // tap the dedicated "navigation" button (above "Me localiser") to enable.
  const [navMode, setNavMode] = useState<boolean>(false);
  // Phase K.2 — Persist navMode across screen navigations. Loaded on mount,
  // saved on every toggle. On return from a report detail we auto-restore
  // the last state (via the useFocusEffect below).
  const [navModeLoaded, setNavModeLoaded] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const saved = await storage.getItem<boolean>("sm.nav.mode_on", false);
        if (saved === true) setNavMode(true);
      } catch { /* keep default */ }
      finally { setNavModeLoaded(true); }
    })();
  }, []);
  useEffect(() => {
    if (!navModeLoaded) return;
    storage.setItem("sm.nav.mode_on", navMode).catch(() => {});
  }, [navMode, navModeLoaded]);
  // Phase K.13 — Radar-effect toggle (Vigie mode only). Persisted with the
  // same storage helper so the user's preference survives app restarts.
  // Default ON so first-time users see the sonar ring; power users who find
  // it distracting can silence it with the top-right toggle.
  const [radarEnabled, setRadarEnabled] = useState<boolean>(true);
  const [radarLoaded, setRadarLoaded] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const saved = await storage.getItem<boolean>("sm.radar.enabled", true);
        if (saved === false) setRadarEnabled(false);
      } catch { /* keep default */ }
      finally { setRadarLoaded(true); }
    })();
  }, []);
  useEffect(() => {
    if (!radarLoaded) return;
    storage.setItem("sm.radar.enabled", radarEnabled).catch(() => {});
  }, [radarEnabled, radarLoaded]);
  // Latest-speed ref used inside the heading callback (avoids stale closures).
  const speedRef = useRef<number | null>(null);
  // Refs miroirs (position + rayon) lus par fetchReports sans figurer dans
  // ses dépendances — voir la note anti-boucle dans fetchReports.
  const userLocRef = useRef<{ lat: number; lng: number } | null>(null);
  const radiusRef = useRef<number>(200);
  /** Phase J — Lissage exponentiel du cap (EMA) pour fluidifier la flèche
   *  et la ligne de projection. Le GPS donne un cap qui sautille de
   *  quelques degrés à chaque tic ; on filtre pour rendre le déplacement
   *  visuel lisse. La gestion du wraparound 0°/360° est faite via la
   *  différence signée la plus courte (delta ∈ ]-180°,+180°]). */
  const smoothedHeadingRef = useRef<number | null>(null);
  const smoothHeading = useCallback((raw: number): number => {
    const ALPHA = 0.25;
    const DEADBAND_DEG = 2; // ignore le micro-bruit magnétomètre/GPS (< 2°)
    if (smoothedHeadingRef.current == null) {
      smoothedHeadingRef.current = raw;
      return raw;
    }
    const cur = smoothedHeadingRef.current;
    const delta = ((raw - cur + 540) % 360) - 180; // signed shortest arc
    if (Math.abs(delta) < DEADBAND_DEG) return cur; // deadband → flèche stable
    const next = (cur + delta * ALPHA + 360) % 360;
    smoothedHeadingRef.current = next;
    return next;
  }, []);
  const [center, setCenter] = useState(DEFAULT_CENTER);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [permDenied, setPermDenied] = useState(false);
  const [offline, setOffline] = useState(false);
  // Phase 4: filters are now a multi-select. An empty Set means "all types".
  // Default = empty Set so EVERY type is shown by default (user feedback).
  const [selectedTypes, setSelectedTypes] = useState<Set<ReportTypeId>>(
    () => new Set<ReportTypeId>(),
  );
  const [hideFakes, setHideFakes] = useState(true);
  const [filterSheetOpen, setFilterSheetOpen] = useState(false);
  /** Phase J — popup coordonnées au tap sur le badge GPS. */
  const [coordsPopupOpen, setCoordsPopupOpen] = useState(false);
  // Phase A v2: bumped storage keys ("_v2") to discard pre-refonte selections
  // (the old type IDs no longer exist in REPORT_TYPES).
  const [filterPrefsLoaded, setFilterPrefsLoaded] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const validIds = new Set(REPORT_TYPES.map((t) => t.id));
        const types = await storage.getItem<string[] | null>("sm.map.types_v2", null);
        if (Array.isArray(types)) {
          // Filter unknown IDs (defensive against any future rename).
          setSelectedTypes(new Set(types.filter((x) => validIds.has(x as ReportTypeId)) as ReportTypeId[]));
        }
        const hf = await storage.getItem<boolean | null>("sm.map.hide_fakes_v2", null);
        if (typeof hf === "boolean") setHideFakes(hf);
      } catch {
        // ignore
      } finally {
        setFilterPrefsLoaded(true);
      }
    })();
  }, []);
  useEffect(() => {
    if (!filterPrefsLoaded) return;
    storage.setItem("sm.map.types_v2", Array.from(selectedTypes)).catch(() => {});
  }, [selectedTypes, filterPrefsLoaded]);
  useEffect(() => {
    if (!filterPrefsLoaded) return;
    storage.setItem("sm.map.hide_fakes_v2", hideFakes).catch(() => {});
  }, [hideFakes, filterPrefsLoaded]);
  // Phase K — Cône jaune Navigation. Persisté sur AsyncStorage.
  const [coneAngleDeg, setConeAngleDeg] = useState<number>(CONE_ANGLE_DEFAULT);
  const [coneModalOpen, setConeModalOpen] = useState<boolean>(false);
  // Loupe (12/07/2026) — recherche d'un signalement par son ID COURT
  // (8 caractères, affiché sur les posts viraux).
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchCode, setSearchCode] = useState("");
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const searchByCode = useCallback(async () => {
    const code = searchCode.trim().toUpperCase();
    if (code.length < 4) {
      setSearchErr("Entrez le code du signalement (8 caractères).");
      return;
    }
    setSearchBusy(true);
    setSearchErr(null);
    try {
      const r = await api.getReportByCode(code);
      setSearchOpen(false);
      setSearchCode("");
      router.push(`/report/${r.id}`);
    } catch (e) {
      setSearchErr((e as Error).message || "Aucun signalement avec ce code.");
    } finally {
      setSearchBusy(false);
    }
  }, [searchCode, router]);
  const [coneLoaded, setConeLoaded] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const saved = await storage.getItem<number>("sm.nav.cone_angle", CONE_ANGLE_DEFAULT);
        if (typeof saved === "number" && saved >= CONE_ANGLE_MIN && saved <= CONE_ANGLE_MAX) {
          setConeAngleDeg(saved);
        }
      } catch { /* keep default */ }
      finally { setConeLoaded(true); }
    })();
  }, []);
  useEffect(() => {
    if (!coneLoaded) return;
    storage.setItem("sm.nav.cone_angle", coneAngleDeg).catch(() => {});
  }, [coneAngleDeg, coneLoaded]);
  // Phase 3c — In-app notifications: unread badge on the bell + welcome banner.
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [welcomeVisible, setWelcomeVisible] = useState<boolean>(false);
  const [welcomeCount, setWelcomeCount] = useState<number>(0);
  // Compteur de vitesse agrandi (10/07/2026) — overlay au tap sur la pill.
  // Version unique « Verre » (ex-A) retenue par l'utilisateur le 12/07/2026.
  const [speedoOpen, setSpeedoOpen] = useState(false);

  const [picking, setPicking] = useState(false);
  const [pickedPoint, setPickedPoint] = useState<{ lat: number; lng: number }>(DEFAULT_CENTER);
  const [shiftReportId, setShiftReportId] = useState<string | null>(null);
  const [submittingShift, setSubmittingShift] = useState(false);
  // When true, the active shift workflow is the author editing their own report.
  // Bypasses /edits (community vote) → calls PATCH /reports/{id} directly.
  const [authorShiftMode, setAuthorShiftMode] = useState(false);
  // Marker to glow on the map (e.g. just after a creation).
  const [focusId, setFocusId] = useState<string | null>(null);

  // Auto-focus a marker when navigated here with ?focus_id=...&focus_lat&focus_lng.
  useEffect(() => {
    const fid = shiftParams.focus_id;
    if (!fid) return;
    setFocusId(fid);
    const flat = shiftParams.focus_lat ? Number(shiftParams.focus_lat) : null;
    const flng = shiftParams.focus_lng ? Number(shiftParams.focus_lng) : null;
    if (flat != null && flng != null && !Number.isNaN(flat) && !Number.isNaN(flng)) {
      setTimeout(() => mapRef.current?.flyTo(flat, flng, 14), 250);
    }
    // Halo fades after a few seconds for a non-intrusive cue.
    const t = setTimeout(() => setFocusId(null), 6000);
    return () => clearTimeout(t);
  }, [shiftParams.focus_id, shiftParams.focus_lat, shiftParams.focus_lng]);

  // Enter shift-picking mode when the report detail screen routes us here.
  // V1.1 bug fix — do NOT re-fire on userLoc changes: the map was continuously
  // recentering on the original report position every time the GPS ticked,
  // preventing the user from actually moving the pick cursor.
  const shiftInitRef = useRef<string | null>(null);
  useEffect(() => {
    const rid = shiftParams.shift_report_id;
    if (!rid) return;
    if (shiftInitRef.current === rid) return;  // already initialised for this rid
    shiftInitRef.current = rid;
    const lat = shiftParams.shift_lat ? Number(shiftParams.shift_lat) : null;
    const lng = shiftParams.shift_lng ? Number(shiftParams.shift_lng) : null;
    const seed = lat != null && lng != null && !Number.isNaN(lat) && !Number.isNaN(lng)
      ? { lat, lng }
      : userLoc ?? DEFAULT_CENTER;
    setShiftReportId(rid);
    setAuthorShiftMode(shiftParams.shift_author === "1");
    setPickedPoint(seed);
    setPicking(true);
    setTimeout(() => mapRef.current?.flyTo(seed.lat, seed.lng, 15), 100);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shiftParams.shift_report_id, shiftParams.shift_lat, shiftParams.shift_lng, shiftParams.shift_author]);

  // Sync des refs miroirs à chaque rendu (toujours frais dans fetchReports).
  // (radiusRef est synchronisé plus bas, après le calcul du rayon effectif.)
  userLocRef.current = userLoc;

  const fetchReports = useCallback(async (typesOverride?: Set<ReportTypeId> | null): Promise<ReportItem[]> => {
    const sel = typesOverride ?? selectedTypes;
    // Empty Set = "all" → omit the filter so the backend returns everything.
    const types = sel.size === 0 ? undefined : Array.from(sel);
    const t0 = Date.now();
    // NOTE identité stable : userLoc change CHAQUE SECONDE (watcher GPS 1 s).
    // S'il était en dépendance, l'identité de fetchReports changeait à chaque
    // tick → le useFocusEffect qui en dépend relançait listReports EN BOUCLE
    // (1 req/s constatée dans les logs device). On lit donc la position et le
    // rayon via des refs, toujours frais sans invalider le callback.
    const loc = userLocRef.current;
    // Phase E.5 — server-side geofiltering: use the *visible* map radius
    // (the "200 km" chip the user actively controls). We deliberately do NOT
    // use user.notify_radius_km here — that field is for push notifications
    // (typically 5 km) and would hide most nearby reports from the map.
    // Cap at 1000 km (borne haute de la Zone de veille Navigation).
    const userRadius = loc ? Math.max(1, Math.min(1000, radiusRef.current ?? 200)) : undefined;
    try {
      const list = await api.listReports({
        types,
        lat: loc?.lat,
        lng: loc?.lng,
        radius_km: loc ? userRadius : undefined,
      });
      setReports(list);
      setOffline(false);
      logger.event("api", "listReports OK", { count: list.length, ms: Date.now() - t0, types });
      await saveReportsCache(list);
      return list;
    } catch (e) {
      const cached = await loadReportsCache(12);
      const filtered = sel.size === 0
        ? cached
        : cached.filter((r) => sel.has(r.type as ReportTypeId));
      setReports(filtered);
      setOffline(true);
      const msg = e instanceof Error ? e.message : String(e);
      // Capture l'état réseau exact au moment de l'échec — utile pour
      // distinguer un vrai offline (NetInfo.isConnected=false) d'un échec
      // backend / proxy alors que le réseau est OK (cas du bug rapporté).
      try {
        const ni = await NetInfo.fetch();
        logger.error("api", "listReports FAILED → offline", {
          error: msg,
          ms: Date.now() - t0,
          types,
          cached: cached.length,
          netinfo: {
            isConnected: ni.isConnected,
            isInternetReachable: ni.isInternetReachable,
            type: ni.type,
          },
        });
      } catch {
        logger.error("api", "listReports FAILED → offline", { error: msg, ms: Date.now() - t0, types, cached: cached.length });
      }
      showToast("info", "Hors-ligne — affichage du cache local (12h).");
      return filtered;
    }
  }, [selectedTypes]);

  // ─── Phase E.5 — Adaptive reports polling ──────────────────────────────
  // Refresh cadence follows the boat's speed (90/60/30 s tiers) and pauses
  // when the app goes to background. A > 100 m GPS jump triggers an
  // instant refetch even if the timer hasn't fired.
  const reportIdSet = useRef<Set<string>>(new Set());
  useEffect(() => {
    reportIdSet.current = new Set(reports.map((r) => r.id));
  }, [reports]);
  const {
    lastAt: pollLastAt,
    newCount: pollNewCount,
    isRefreshing: pollRefreshing,
    refresh: pollRefresh,
    dismissNewCount: pollDismiss,
  } = useAdaptiveReportsPolling<ReportItem>({
    enabled: !picking && !demoMode,
    speedMs: userSpeed,
    userLoc,
    currentIds: reportIdSet.current,
    fetcher: () => fetchReports(),
  });

  // 15/07/2026 (demande user) — le bandeau « N nouveaux signalements près de
  // vous » disparaît AUTOMATIQUEMENT après 4 s. L'information reste
  // disponible dans la cloche : chaque signalement proche crée une
  // notification backend (fan-out géo, core/notifications.py) consultable
  // dans /profile/notifications, indépendamment de ce bandeau.
  useEffect(() => {
    if (pollNewCount <= 0) return;
    const t = setTimeout(() => pollDismiss(), 4_000);
    return () => clearTimeout(t);
  }, [pollNewCount, pollDismiss]);
  // Trigger a re-render every 10 s so the "il y a Xs" indicator stays fresh
  // without requiring the whole map to re-render on every state change.
  const [nowTick, setNowTick] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 10_000);
    return () => clearInterval(t);
  }, []);

  // Auto-retry tant qu'on est offline : ping le backend toutes les 20 s
  // pour reprendre les données dès que la connexion revient.
  useEffect(() => {
    if (!offline) return;
    let cancelled = false;
    const t = setInterval(async () => {
      if (cancelled) return;
      logger.event("net", "auto_retry_listReports");
      try {
        const types = selectedTypes.size === 0 ? undefined : Array.from(selectedTypes);
        const list = await api.listReports({ types });
        if (cancelled) return;
        setReports(list);
        setOffline(false);
        await saveReportsCache(list);
        logger.event("api", "auto_retry OK", { count: list.length });
      } catch {
        // toujours offline — on continue
      }
    }, 20_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [offline, selectedTypes]);

  // First-fix + always-on position tracking. The blue dot follows in real
  // time even when nav mode is OFF — the user no longer has to keep tapping
  // "Me localiser" to see their current position move. The recenter button
  // is now strictly for re-centring the camera, not for refreshing the dot.
  useEffect(() => {
    let cancelled = false;
    let posSub: Location.LocationSubscription | null = null;
    (async () => {
      try {
        // 0) Position PRÉCHAUFFÉE (warmup lancé au démarrage de l'app dans
        //    _layout.tsx) — affichée IMMÉDIATEMENT, zéro attente.
        const warm = getWarmLocation();
        if (warm && !cancelled) {
          setUserLoc({ lat: warm.lat, lng: warm.lng });
        }
        const perm = await Location.requestForegroundPermissionsAsync();
        if (perm.status !== "granted") {
          if (!cancelled) setPermDenied(true);
          return;
        }
        // Permission peut-être accordée APRÈS le boot → (re)lancer la chauffe.
        startGpsWarmup().catch(() => { /* best-effort */ });
        // 1) Dernière position connue de l'OS — instantanée, sans fix.
        Location.getLastKnownPositionAsync()
          .then((pos) => {
            if (pos && !cancelled) {
              setUserLoc((prev) => prev ?? { lat: pos.coords.latitude, lng: pos.coords.longitude });
            }
          })
          .catch(() => { /* pas de cache OS */ });
        // 2) Watcher démarré SANS ATTENDRE un premier fix, avec RETRY :
        //    BUG corrigé (13/07) : avant, un getCurrentPositionAsync BLOQUANT
        //    précédait le watcher (fix à froid = minutes sans localisation) ET
        //    la moindre exception du provider tuait le GPS définitivement en
        //    affichant à tort « Localisation refusée ». Désormais on re-tente
        //    toutes les 3 s tant que le watcher n'a pas démarré.
        const onFix = (p: Location.LocationObject) => {
          if (cancelled) return;
          setUserLoc({ lat: p.coords.latitude, lng: p.coords.longitude });
          const sp = (typeof p.coords.speed === "number" && p.coords.speed >= 0) ? p.coords.speed : null;
          if (sp != null) {
            speedRef.current = sp;
            setUserSpeed(sp);
          }
          // Le cap GPS n'a AUCUN sens à l'arrêt (valeurs aléatoires → la
          // flèche rouge tournait sur elle-même en Vigie). On ne l'accepte
          // qu'en mouvement réel (≥ 0,6 m/s) ; à l'arrêt le dernier cap
          // fiable est conservé.
          if (
            typeof p.coords.heading === "number" && p.coords.heading >= 0 &&
            (sp ?? 0) >= 0.6
          ) {
            setUserHeading(smoothHeading(p.coords.heading));
          }
        };
        for (let attempt = 0; attempt < 40 && !cancelled && !posSub; attempt++) {
          try {
            posSub = await Location.watchPositionAsync(
              { accuracy: Location.Accuracy.High, distanceInterval: 0, timeInterval: 1000 },
              onFix,
            );
          } catch {
            // Provider momentanément indisponible — on RE-TENTE (pas de
            // bannière « refusée » : la permission est accordée).
            await new Promise((res) => setTimeout(res, 3000));
          }
        }
        // 3) Premier fix rapide en PARALLÈLE (non bloquant) + sync serveur.
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })
          .then((pos) => {
            if (cancelled) return;
            const c = { lat: pos.coords.latitude, lng: pos.coords.longitude };
            setUserLoc(c);
            if (user) {
              api.updateLocation(c.lat, c.lng).catch(() => { /* offline / auth race */ });
            }
          })
          .catch(() => { /* le watcher prendra le relais */ });
      } catch {
        if (!cancelled) setPermDenied(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      try { posSub?.remove(); } catch { /* noop */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Phase I — Navigation mode: HIGH-FREQ position + compass tracking. Layered
  // on top of the always-on watcher; the OS de-duplicates internally.
  useEffect(() => {
    if (!navMode) return;
    let posSub: Location.LocationSubscription | null = null;
    let headSub: Location.LocationSubscription | null = null;
    let cancelled = false;
    (async () => {
      try {
        posSub = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.BestForNavigation, distanceInterval: 0, timeInterval: 1000 },
          (p) => {
            if (cancelled) return;
            setUserLoc({ lat: p.coords.latitude, lng: p.coords.longitude });
            speedRef.current = (typeof p.coords.speed === "number" && p.coords.speed >= 0) ? p.coords.speed : null;
            setUserSpeed(speedRef.current);
            // Cap GPS fiable uniquement en mouvement (cf. watcher Vigie) ;
            // à l'arrêt c'est le compas (watchHeadingAsync) qui prend le relais.
            if (
              typeof p.coords.heading === "number" && p.coords.heading >= 0 &&
              (speedRef.current ?? 0) >= 0.6
            ) {
              setUserHeading(smoothHeading(p.coords.heading));
            }
          },
        );
        try {
          headSub = await Location.watchHeadingAsync((h) => {
            if (cancelled) return;
            const reliable = (speedRef.current ?? 0) >= 0.6;
            if (!reliable && typeof h.trueHeading === "number" && h.trueHeading >= 0) {
              setUserHeading(smoothHeading(h.trueHeading));
            }
          });
        } catch {
          /* compass unavailable on some emulators */
        }
      } catch {
        /* fail silently — base watcher keeps the blue dot moving */
      }
    })();
    return () => {
      cancelled = true;
      try { posSub?.remove(); } catch { /* noop */ }
      try { headSub?.remove(); } catch { /* noop */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navMode]);

  // Phase E — Voice-alert proximity watcher.
  // Fires an audible alert (via /api/tts/alert) whenever the user enters the
  // alert radius of an eligible active report while in nav mode. Uses the
  // user's voice settings (radius, speed threshold, look-ahead, voice pick)
  // and applies a 5-minute per-report cool-down so we don't spam the same
  // point. Runs client-side and is independent from the server-side push
  // notify_radius_km setting (which only gates INITIAL push notifications).
  const { settings: voiceSettings, update: updateVoiceSettings } = useVoiceSettings();
  // Miroir ref pour les timers de répétition (les réglages peuvent changer
  // pendant qu'une alerte est active, via les réglages rapides).
  const voiceSettingsRef = useRef(voiceSettings);
  voiceSettingsRef.current = voiceSettings;

  // ── Bascule AUTO Vigie ⇄ Navigation (11/07/2026) ────────────────────────
  // Le mode suit le bateau : vitesse ≥ 3 km/h maintenue 5 s → Navigation ;
  // < 3 km/h maintenue 5 s → Vigie. On n'agit QUE sur les TRANSITIONS
  // (départ / arrêt du bateau), jamais en continu : un basculement manuel
  // reste donc respecté jusqu'au prochain changement d'état réel.
  const [autoSwitchBanner, setAutoSwitchBanner] = useState<null | "nav" | "vigie">(null);
  const navModeRef = useRef(navMode);
  useEffect(() => { navModeRef.current = navMode; }, [navMode]);
  const speedStateRef = useRef<"moving" | "stopped" | null>(null);
  const speedStreakKindRef = useRef<"moving" | "stopped" | null>(null);
  const speedStreakStartRef = useRef<number>(0);

  // 1ʳᵉ bascule auto (persistée) → bannière d'info avec accès direct au
  // réglage ; les suivantes → simple toast.
  const announceAutoSwitch = useCallback(async (nav: boolean) => {
    const toast = () =>
      showToast("info", nav ? "Bascule auto — mode Navigation" : "Bascule auto — mode Vigie");
    try {
      const shown = await storage.getItem<boolean>("sm.autoswitch.info_shown", false);
      if (!shown) {
        await storage.setItem("sm.autoswitch.info_shown", true);
        setAutoSwitchBanner(nav ? "nav" : "vigie");
      } else {
        toast();
      }
    } catch { toast(); }
  }, []);

  useEffect(() => {
    if (voiceSettings.autoModeSwitch === false) return;
    const t = setInterval(() => {
      const sp = speedRef.current;
      if (sp == null) return; // pas de fix GPS exploitable
      const kind: "moving" | "stopped" = sp >= AUTO_SWITCH_SPEED_MS ? "moving" : "stopped";
      if (speedStreakKindRef.current !== kind) {
        speedStreakKindRef.current = kind;
        speedStreakStartRef.current = Date.now();
        return;
      }
      if (Date.now() - speedStreakStartRef.current < AUTO_SWITCH_SUSTAIN_MS) return;
      if (speedStateRef.current === kind) return; // pas de transition
      speedStateRef.current = kind;
      const wantNav = kind === "moving";
      if (navModeRef.current === wantNav) return; // déjà dans le bon mode
      setNavMode(wantNav);
      logger.event("nav", wantNav ? "auto_nav_start" : "auto_nav_stop", { speed: sp });
      void announceAutoSwitch(wantNav);
    }, 1000);
    return () => clearInterval(t);
  }, [voiceSettings.autoModeSwitch, announceAutoSwitch]);

  // Rayon effectif d'affichage/fetch : au moins DISPLAY_RADIUS_KM (200 km),
  // étendu si une Zone de veille le dépasse (Nav réglable jusqu'à 1000 km) —
  // sinon les signalements lointains ne seraient jamais chargés et la zone
  // étendue resterait silencieuse.
  const radius = Math.max(
    DISPLAY_RADIUS_KM,
    Math.ceil((voiceSettings.zoneNavM || 0) / 1000),
    Math.ceil((voiceSettings.zoneVigieM || 0) / 1000),
  );
  radiusRef.current = radius;

  // ── Alerte active : bannière « Stopper l'alerte » + répétitions ─────────
  // Quand le watcher déclenche une alerte, on affiche une bannière avec un
  // bouton STOP (coupe son + vibreur) et les réglages rapides. Si
  // l'utilisateur n'interrompt pas, l'alerte est répétée N fois (réglage
  // 0-2, défaut 2) toutes les 15 s puis disparaît. TOTAL diffusé = 1 annonce
  // + N répétitions, JAMAIS plus (le watcher ne re-déclenche pas tant qu'on
  // reste dans le périmètre — 13/07/2026).
  const [activeAlert, setActiveAlert] = useState<{ id: string; text: string; type: string; stopped: boolean } | null>(null);
  // Réglages de la popup d'alerte : REPLIÉS par défaut (12/07/2026) — la
  // roue dentée déplie uniquement le périmètre du mode actif.
  const [alertQuickOpen, setAlertQuickOpen] = useState(false);
  const [alertSettingsOpen, setAlertSettingsOpen] = useState(false);
  const alertTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const repsDoneRef = useRef(0);
  // 15/07/2026 (demande user, point 4) — VERROU STOP : une fois « Stopper
  // l'alerte » pressé, PLUS AUCUNE répétition ne doit sonner, même en cas de
  // course avec le timer. Seule la réactivation explicite le lève.
  const alertStoppedRef = useRef(false);
  // 15/07/2026 (demande user) — la pastille « Alerte stoppée / Réactiver »
  // disparaît automatiquement 5 s après l'appui sur « Stopper l'alerte »
  // (sauf réactivation entre-temps).
  const stopPillTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearStopPillTimer = useCallback(() => {
    if (stopPillTimerRef.current) { clearTimeout(stopPillTimerRef.current); stopPillTimerRef.current = null; }
  }, []);

  const clearAlertTimer = useCallback(() => {
    if (alertTimerRef.current) { clearInterval(alertTimerRef.current); alertTimerRef.current = null; }
  }, []);

  const startAlertRepetitions = useCallback((text: string) => {
    clearAlertTimer();
    repsDoneRef.current = 0;
    const delayMs = Math.max(5, voiceSettingsRef.current.repeatDelaySec ?? 15) * 1000;
    alertTimerRef.current = setInterval(() => {
      // VERROU STOP (15/07/2026) : alerte stoppée → silence total, quoi
      // qu'il arrive (défense en profondeur en plus du clearAlertTimer).
      if (alertStoppedRef.current) { clearAlertTimer(); return; }
      const s = voiceSettingsRef.current;
      if (repsDoneRef.current < Math.max(0, Math.min(2, s.repetitions ?? 2))) {
        repsDoneRef.current += 1;
        // 14/07/2026 — chaque répétition = corne de brume + vibration.
        if (s.enabled !== false) playAlertHorn();
        if (s.vibrationEnabled !== false) vibrateAlert();
      } else {
        // Déclenchement initial + répétitions écoulés → extinction auto.
        clearAlertTimer();
        setActiveAlert(null);
      }
    }, delayMs);
  }, [clearAlertTimer]);

  // Stop = coupe son + vibreur + répétitions, mais RÉDUIT l'alerte en
  // pastille persistante (réactivable en cas de clic par mégarde).
  const stopActiveAlert = useCallback(() => {
    alertStoppedRef.current = true;
    clearAlertTimer();
    try { stopAlertHorn(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
    setActiveAlert((a) => (a ? { ...a, stopped: true } : null));
    // Auto-fermeture de la pastille après 5 s (demande user 15/07/2026).
    clearStopPillTimer();
    stopPillTimerRef.current = setTimeout(() => {
      stopPillTimerRef.current = null;
      setActiveAlert((a) => (a && a.stopped ? null : a));
    }, 5_000);
  }, [clearAlertTimer, clearStopPillTimer]);

  const reactivateAlert = useCallback(() => {
    clearStopPillTimer();
    setActiveAlert((a) => {
      if (!a) return null;
      alertStoppedRef.current = false;
      if (voiceSettingsRef.current.enabled !== false) playAlertHorn();
      if (voiceSettingsRef.current.vibrationEnabled !== false) vibrateAlert();
      startAlertRepetitions(a.text);
      return { ...a, stopped: false };
    });
  }, [startAlertRepetitions, clearStopPillTimer]);

  const closeAlert = useCallback(() => {
    alertStoppedRef.current = true;
    clearAlertTimer();
    clearStopPillTimer();
    try { stopAlertHorn(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
    setActiveAlert(null);
  }, [clearAlertTimer, clearStopPillTimer]);

  const handleAlertStarted = useCallback((report: ReportItem, text: string) => {
    // Une nouvelle alerte remplace la précédente (timers compris) ;
    // les réglages repartent REPLIÉS.
    alertStoppedRef.current = false;
    clearStopPillTimer();
    setAlertQuickOpen(false);
    setActiveAlert({ id: report.id, text, type: report.type, stopped: false });
    startAlertRepetitions(text);
  }, [startAlertRepetitions, clearStopPillTimer]);

  // 16/07/2026 (retour terrain) — premier fix GPS reçu APRÈS que la carte
  // soit prête : centrage automatique UNE FOIS sur l'utilisateur (le cas
  // « fix déjà connu au chargement » est géré par le handler `ready` de
  // MarineMap). Sans ça, la carte restait sur le centre par défaut.
  const firstCenterDoneRef = useRef(false);
  useEffect(() => {
    if (!userLoc || firstCenterDoneRef.current) return;
    firstCenterDoneRef.current = true;
    mapRef.current?.flyTo(userLoc.lat, userLoc.lng, 12);
  }, [userLoc]);

  // ── Confirmation « à la Waze » par passage à ≤ 500 m (15/07/2026) ──
  // Jamais pendant une alerte, jamais pour ses signalements, 1 fois par
  // signalement/session, bateau en route uniquement (voir proximity-confirm).
  const { question: proximityQuestion, dismiss: dismissProximity } = useProximityConfirm({
    userLoc,
    userSpeedMs: userSpeed,
    reports,
    myUserId: user?.user_id ?? null,
    alertVisible: activeAlert != null,
    enabled: !demoMode && !!user,
  });

  const answerProximityYes = useCallback(async () => {
    const rep = proximityQuestion?.report;
    dismissProximity();
    if (!rep) return;
    try {
      const r = await api.confirmReport(rep.id, "proximity");
      const pts = Number(r.confirmer_points_awarded ?? 0);
      showToast("success", pts > 0
        ? `Merci ! Signalement confirmé (+${pts} pt de grade)`
        : "Merci ! Signalement confirmé");
      void fetchReports();
    } catch (e) {
      showToast("error", e instanceof Error ? e.message : "Confirmation impossible");
    }
  }, [proximityQuestion, dismissProximity, fetchReports]);

  const answerProximityNo = useCallback(async () => {
    const rep = proximityQuestion?.report;
    dismissProximity();
    if (!rep) return;
    try {
      const r = await api.denyReport(rep.id);
      if (r.effect === "removed") {
        showToast("success", "Merci — signalement retiré de la carte.");
        void fetchReports();
      } else if (r.effect === "ttl_reduced") {
        showToast("info", "Merci — l'info est prise en compte.");
      } else {
        showToast("info", "Merci pour votre retour.");
      }
    } catch {
      showToast("error", "Envoi impossible");
    }
  }, [proximityQuestion, dismissProximity, fetchReports]);

  // Nettoyage des timers/son/vibreur au démontage de l'écran.
  useEffect(() => () => {
    if (alertTimerRef.current) clearInterval(alertTimerRef.current);
    if (stopPillTimerRef.current) clearTimeout(stopPillTimerRef.current);
    try { stopAlertHorn(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
  }, []);

  // Audit 12/07/2026 — le déclenchement vit désormais dans le module central
  // sound-alert.ts : Vigie = 360° permanent (zoneVigieM) ; Navigation = cône
  // uniquement avec 3 s de présence continue (anti-jitter de cap) ; vibreur
  // découplé de la voix ; ré-armement à la sortie du périmètre ; préchauffage
  // TTS Bluetooth à l'approche.
  useSoundAlertWatcher({
    userLoc: userLoc,
    userSpeedMs: userSpeed,
    reports: reports,
    voiceSettings: voiceSettings,
    navMode: navMode,
    userHeading: userHeading,
    coneHalfAngleDeg: navMode ? coneAngleDeg / 2 : null,
    onAlert: handleAlertStarted,
  });

  // Phase 3c — Poll unread notifications count.
  // Runs whenever the map is focused: initial fetch on mount, then every 45s.
  // Also refreshes when returning to the tab (useFocusEffect below).
  // The welcome banner shows ONLY on the first mount of the session, when the
  // count is > 0, and can be dismissed. Reopening the app (JS reload) shows it
  // again — this matches the user's requirement "uniquement au 1er chargement".
  const refreshUnread = useCallback(async () => {
    if (!user) return;
    try {
      const r = await api.notificationsCount();
      const n = r.unread_count ?? 0;
      setUnreadCount(n);
      // Trigger welcome banner exactly once per session (only if we have news).
      if (!welcomeBannerShownInSession && n > 0) {
        welcomeBannerShownInSession = true;
        setWelcomeCount(n);
        setWelcomeVisible(true);
      }
    } catch {
      // silent — this is a cosmetic badge, not a critical path.
    }
  }, [user]);
  useEffect(() => {
    if (!user) return;
    void refreshUnread();
    const t = setInterval(() => { void refreshUnread(); }, 45_000);
    return () => clearInterval(t);
  }, [user, refreshUnread]);

  useFocusEffect(
    useCallback(() => {
      // Phase K.2 — Force re-sync of navMode into the WebView on focus. When
      // returning from a report detail the JS map is still mounted but its
      // internal navMode flag may have drifted (rare); we push the current
      // React state again so the boat marker + cone + follow-mode come back
      // immediately without needing to re-tap the button.
      // 13/07/2026 — retour depuis un détail de signalement : on NE recentre
      // PLUS immédiatement (vidéo user : « éjection » vers la position GPS).
      // La carte reste où l'utilisateur la consultait ; le recentrage auto
      // reprend après 5 s d'inactivité (grâce accordée ci-dessous).
      mapRef.current?.grantRecenterGrace();
      if (navMode) {
        mapRef.current?.setNavMode(true, true); // re-sync SANS recentrage
      }
      // Phase 3c — refresh unread count when returning to the map tab so the
      // bell badge stays accurate after users visit the notifications screen.
      void refreshUnread();
      // Phase 1 fix retained — surface a freshly-created report INSTANTLY:
      //   1) optimistic insert (no HTTP round-trip),
      //   2) expand the active filter set to include the new type if it would
      //      otherwise be hidden,
      //   3) refetch with the new selection (explicit override to avoid a
      //      stale closure on `selectedTypes`),
      //   4) fly to the marker + 6s glow halo.
      const created = consumeLastCreated();
      if (created) {
        const isAll = selectedTypes.size === 0;
        const needsExpand = !isAll && !selectedTypes.has(created.type as ReportTypeId);
        const effective: Set<ReportTypeId> = needsExpand
          ? new Set([...selectedTypes, created.type as ReportTypeId])
          : selectedTypes;
        if (needsExpand) setSelectedTypes(effective);
        setReports((prev) => {
          if (prev.some((r) => r.id === created.id)) return prev;
          return [created, ...prev];
        });
        setFocusId(created.id);
        setTimeout(() => mapRef.current?.flyTo(created.lat, created.lng, 14), 200);
        setTimeout(() => setFocusId((c) => (c === created.id ? null : c)), 6000);
        fetchReports(effective);
      } else {
        fetchReports();
      }
    }, [fetchReports, selectedTypes, refreshUnread, navMode]),
  );

  // Filter reports by type selection + hide-fakes toggle + radius (client-side).
  // The type filter is also applied here so toggling selection in the bottom-
  // sheet feels instant (no waiting for the refetch).
  const visibleReports = (() => {
    let list = reports;
    if (selectedTypes.size > 0 && selectedTypes.size < REPORT_TYPES.length) {
      list = list.filter((r) => selectedTypes.has(r.type as ReportTypeId));
    }
    if (hideFakes) list = list.filter((r) => !r.flagged_fake);
    if (!userLoc) return list;
    const R = 6371;
    list = list.filter((r) => {
      // Demo reports are always visible (showcase content — regardless of radius).
      if (r.is_demo) return true;
      const dLat = ((r.lat - userLoc.lat) * Math.PI) / 180;
      const dLon = ((r.lng - userLoc.lng) * Math.PI) / 180;
      const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos((userLoc.lat * Math.PI) / 180) *
          Math.cos((r.lat * Math.PI) / 180) *
          Math.sin(dLon / 2) ** 2;
      const km = 2 * R * Math.asin(Math.sqrt(a));
      return km <= radius;
    });
    return list;
  })();

  function recenter() {
    if (!userLoc) {
      showToast("info", "Localisation indisponible");
      return;
    }
    mapRef.current?.flyTo(userLoc.lat, userLoc.lng, 13);
  }

  function reportHere() {
    if (demoMode && !user) {
      showToast("info", "Connectez-vous pour publier un signalement.");
      router.push("/(auth)/login");
      return;
    }
    // Enter "picking mode": user drags the map; the crosshair points to the
    // future report position. Pre-select user's current position.
    const seed = userLoc ?? center;
    setPickedPoint(seed);
    setPicking(true);
    mapRef.current?.flyTo(seed.lat, seed.lng, 14);
  }

  function confirmPick() {
    if (shiftReportId) {
      setSubmittingShift(true);
      const rid = shiftReportId;
      const finish = (msg: string) => {
        showToast("success", msg);
        setSubmittingShift(false);
        setPicking(false);
        setShiftReportId(null);
        setAuthorShiftMode(false);
        router.replace(`/report/${rid}`);
      };
      if (authorShiftMode) {
        // Author edits their own report directly — no community vote.
        api
          .authorEdit(rid, { new_lat: pickedPoint.lat, new_lng: pickedPoint.lng })
          .then(() => finish("Position mise à jour."))
          .catch((e) => {
            showToast("error", (e as Error).message);
            setSubmittingShift(false);
          });
      } else {
        // Standard community-vote workflow.
        api
          .proposeEdit(rid, {
            kind: "shift",
            new_lat: pickedPoint.lat,
            new_lng: pickedPoint.lng,
          })
          .then(() => finish("Décalage proposé — la communauté décide."))
          .catch((e) => {
            showToast("error", (e as Error).message);
            setSubmittingShift(false);
          });
      }
      return;
    }
    setPicking(false);
    router.push({
      pathname: "/report/new",
      params: { lat: String(pickedPoint.lat), lng: String(pickedPoint.lng) },
    });
  }

  function cancelPick() {
    setPicking(false);
    if (shiftReportId) {
      const rid = shiftReportId;
      setShiftReportId(null);
      setAuthorShiftMode(false);
      router.replace(`/report/${rid}`);
    }
  }

  function toggleType(id: ReportTypeId) {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Phase J — Pousser le toggle navMode dans le MarineMap dès que ça change,
  // pour activer/désactiver le follow-mode (recentrage auto 5 s + ancrage 3/5).
  useEffect(() => {
    mapRef.current?.setNavMode(navMode);
  }, [navMode]);

  // Longueur du cône Navigation = Zone de veille Navigation (fixe).
  const coneDistanceKm = navMode ? voiceSettings.zoneNavM / 1000 : null;
  const coneHalfAngleDeg = navMode ? coneAngleDeg / 2 : null;

  return (
    <View style={styles.root}>
      <MarineMap
        ref={mapRef}
        center={center}
        zoom={10}
        userLocation={userLoc}
        userHeading={userHeading}
        userSpeed={userSpeed}
        showBoat={true}
        courseUp={navMode}
        coneHalfAngleDeg={coneHalfAngleDeg}
        coneDistanceKm={coneDistanceKm}
        radarPingRadiusM={!navMode && radarEnabled ? voiceSettings.zoneVigieM : null}
        reports={visibleReports}
        crosshair={picking}
        focusId={focusId}
        onMarkerPress={(id) => router.push(`/report/${id}`)}
        onMapMoved={(lat, lng) => {
          if (picking) setPickedPoint({ lat, lng });
        }}
        onMapLongPress={(lat, lng) => {
          // V1.1 — long-press = shortcut to create a signalement at the tapped
          // location. Route through /report/new with prefilled coordinates.
          // Geofence + dev-bypass are enforced server-side on report creation
          // (antoninlepinay@gmail.com bypasses everything, other accounts get
          // a clear error toast if they long-press outside the allowed area).
          if (shiftReportId || picking) return; // already in a picker flow
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
          router.push({
            pathname: "/report/new",
            params: { lat: String(lat), lng: String(lng), src: "longpress" },
          });
        }}
        mapUnit={mapUnit}
        onRulerTap={() => setUnitPickerOpen(true)}
      />

      <SafeAreaView
        style={[styles.topOverlay, isLandscape && styles.topOverlayLandscape]}
        edges={["top"]}
        pointerEvents="box-none"
      >
        <View style={styles.topRow}>
          {demoMode && !user ? (
            <TouchableOpacity
              style={styles.demoBadge}
              onPress={() => router.push("/(auth)/login")}
              testID="map-demo-banner"
            >
              <Ionicons name="eye" size={14} color={theme.warning} />
              <Text style={styles.demoText}>Mode démo — connectez-vous</Text>
              <Ionicons name="chevron-forward" size={14} color={theme.warning} />
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              style={styles.badge}
              onPress={() => {
                if (offline) {
                  fetchReports();
                } else if (userLoc) {
                  setCoordsPopupOpen(true);
                }
              }}
              activeOpacity={(offline || userLoc) ? 0.7 : 1}
              disabled={!offline && !userLoc}
              testID="map-status-badge"
            >
              <Ionicons
                name={offline ? "cloud-offline" : "navigate"}
                size={14}
                color={offline ? theme.warning : theme.primary}
              />
              <Text style={styles.badgeText} numberOfLines={1}>
                {offline
                  ? "Hors-ligne · taper pour réessayer"
                  : userLoc
                    ? formatDM(userLoc.lat, userLoc.lng)
                    : "GPS…"}
              </Text>
            </TouchableOpacity>
          )}
          {/* Compteur de vitesse — remonté dans la barre du haut (10/07).
              Tap → compteur AGRANDI (overlay bande « Verre »). */}
          <TouchableOpacity
            style={styles.topSpeedPill}
            onPress={() => setSpeedoOpen(true)}
            activeOpacity={0.8}
            testID="map-speed-pill"
            accessibilityLabel="Agrandir le compteur de vitesse"
          >
            <Ionicons name="speedometer" size={13} color={theme.primary} />
            <Text style={styles.topSpeedText}>
              {userSpeed != null && userSpeed * 3.6 >= 3
                ? `${(userSpeed * 1.9438445).toFixed(1)} kn`
                : "0 kn"}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.radiusBtn}
            onPress={() => setFilterSheetOpen(true)}
            testID="map-filter-trigger"
          >
            <Ionicons name="options" size={14} color={theme.primary} />
            <Text style={styles.radiusBtnText}>
              {selectedTypes.size === 0
                ? "Tous types"
                : selectedTypes.size === 1
                  ? (REPORT_TYPES.find((t) => t.id === Array.from(selectedTypes)[0])?.short ?? "1 type")
                  : `${selectedTypes.size} types`}
            </Text>
          </TouchableOpacity>
          {/* Bouton Réglages — ouvre la page dédiée (10/07). */}
          <TouchableOpacity
            style={styles.bellBtn}
            onPress={() => router.push("/profile/settings")}
            activeOpacity={0.85}
            testID="map-open-settings"
            accessibilityLabel="Réglages"
          >
            <Ionicons name="settings-outline" size={16} color={theme.primary} />
          </TouchableOpacity>
          {/* Phase 3c — Bell icon with unread badge. Opens the in-app
              notifications drawer. Hidden in demo mode (no user account). */}
          {user && (
            <TouchableOpacity
              style={styles.bellBtn}
              onPress={() => router.push("/profile/notifications")}
              activeOpacity={0.85}
              testID="map-notif-bell"
              accessibilityLabel={
                unreadCount > 0
                  ? `Notifications, ${unreadCount} non lues`
                  : "Notifications"
              }
            >
              <Ionicons
                name={unreadCount > 0 ? "notifications" : "notifications-outline"}
                size={16}
                color={theme.primary}
              />
              {unreadCount > 0 && (
                <View style={styles.bellBadge}>
                  <Text style={styles.bellBadgeText} numberOfLines={1}>
                    {unreadCount > 99 ? "99+" : String(unreadCount)}
                  </Text>
                </View>
              )}
            </TouchableOpacity>
          )}
        </View>

        {/* Phase 3c — Welcome banner (in-app notif summary). Shown once per
            session on the map when unread notifications exist. Reopening the
            app re-triggers it; navigating away does not. */}
        {welcomeVisible && (
          <View style={styles.welcomeCard} testID="map-welcome-notif">
            <View style={styles.welcomeIcon}>
              <Ionicons name="notifications" size={18} color={theme.bg} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.welcomeTitle} numberOfLines={1}>
                Salut {user?.pseudo || user?.name || "SignalMar"} 👋
              </Text>
              <Text style={styles.welcomeText} numberOfLines={2}>
                {welcomeCount === 1
                  ? "Vous avez 1 nouvelle notification."
                  : `Vous avez ${welcomeCount} nouvelles notifications.`}
              </Text>
            </View>
            <TouchableOpacity
              style={styles.welcomeBtn}
              onPress={() => {
                setWelcomeVisible(false);
                router.push("/profile/notifications");
              }}
              testID="map-welcome-see"
              activeOpacity={0.85}
            >
              <Text style={styles.welcomeBtnText}>Voir</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.welcomeClose}
              onPress={() => setWelcomeVisible(false)}
              testID="map-welcome-dismiss"
              hitSlop={8}
            >
              <Ionicons name="close" size={16} color={theme.textDim} />
            </TouchableOpacity>
          </View>
        )}

        {/* Phase E.5 — "N nouveaux signalements" banner (top). */}
        {pollNewCount > 0 && (
          <TouchableOpacity
            style={styles.newBanner}
            onPress={() => {
              pollDismiss();
              // Fly-to the newest report near the user (if any).
              const newest = reports[0];
              if (newest) mapRef.current?.flyTo(newest.lat, newest.lng, 12);
            }}
            testID="map-new-reports-banner"
            activeOpacity={0.85}
          >
            <View style={styles.newBannerDot} />
            <Text style={styles.newBannerText}>
              {pollNewCount === 1
                ? "1 nouveau signalement près de vous"
                : `${pollNewCount} nouveaux signalements près de vous`}
            </Text>
            <Ionicons name="arrow-forward" size={16} color={theme.bg} />
          </TouchableOpacity>
        )}

        {/* Bascule AUTO Vigie ⇄ Navigation — bannière d'info affichée UNE
            seule fois (1ʳᵉ bascule auto, flag persisté), avec accès direct
            au réglage dans la page Paramètres. */}
        {autoSwitchBanner && (
          <View style={styles.autoSwitchCard} testID="map-autoswitch-banner">
            <View style={styles.autoSwitchIcon}>
              <Ionicons
                name={autoSwitchBanner === "nav" ? "navigate" : "radio"}
                size={16}
                color={theme.bg}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.welcomeTitle} numberOfLines={1}>
                Bascule auto en mode {autoSwitchBanner === "nav" ? "Navigation" : "Vigie"}
              </Text>
              <Text style={styles.welcomeText} numberOfLines={3}>
                {autoSwitchBanner === "nav"
                  ? "Votre bateau avance (≥ 3 km/h) — SignalMar passe en Navigation. Désactivable dans les réglages."
                  : "Votre bateau est à l'arrêt — retour en mode Vigie 360°. Désactivable dans les réglages."}
              </Text>
            </View>
            <TouchableOpacity
              style={styles.welcomeBtn}
              onPress={() => {
                setAutoSwitchBanner(null);
                router.push({ pathname: "/profile/settings", params: { focus: "autoswitch" } });
              }}
              testID="map-autoswitch-settings"
              activeOpacity={0.85}
            >
              <Text style={styles.welcomeBtnText}>Régler</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.welcomeClose}
              onPress={() => setAutoSwitchBanner(null)}
              testID="map-autoswitch-dismiss"
              hitSlop={8}
            >
              <Ionicons name="close" size={16} color={theme.textDim} />
            </TouchableOpacity>
          </View>
        )}

        <View style={{ height: spacing.sm }} />

        {permDenied && (
          <View style={styles.permBox}>
            <Ionicons name="information-circle" size={18} color={theme.warning} />
            <Text style={styles.permText}>
              Localisation refusée. Activez le GPS pour le rayon et la position.
            </Text>
          </View>
        )}
      </SafeAreaView>

      {/* ── Alerte sonore active : STOP + réglages rapides ─────────────────
          Affichée dès que le watcher déclenche une alerte. Le bouton
          « Stopper l'alerte » coupe immédiatement le son et le vibreur.
          En dessous : réglages rapides (rayon / types / répétitions). Sans
          interruption, la bannière s'éteint seule après le déclenchement
          + le nombre de répétitions configuré. */}
      {activeAlert && (() => {
        const t = TYPE_BY_ID[activeAlert.type as ReportTypeId];
        const color = t?.color || "#E63946";
        // Alerte stoppée → pastille compacte persistante : réactivable en
        // cas de clic par mégarde, ou fermeture définitive via la croix.
        if (activeAlert.stopped) {
          return (
            <View style={[styles.stoppedAlertPill, { top: insets.top + 58, borderColor: color }]} testID="map-stopped-alert">
              <Ionicons name={(t?.icon as never) || "warning"} size={14} color={color} />
              <Text style={styles.stoppedAlertText} numberOfLines={1}>Alerte stoppée</Text>
              <TouchableOpacity
                style={[styles.reactivateBtn, { backgroundColor: color }]}
                onPress={reactivateAlert}
                testID="map-reactivate-alert"
              >
                <Ionicons name="notifications" size={13} color={theme.bg} />
                <Text style={styles.reactivateBtnText}>Réactiver</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.stoppedAlertClose} onPress={closeAlert} testID="map-close-alert">
                <Ionicons name="close" size={16} color={theme.textMute} />
              </TouchableOpacity>
            </View>
          );
        }
        return (
          <View style={[styles.activeAlertCard, { top: insets.top + 58, borderColor: color }]} testID="map-active-alert">
            <View style={styles.activeAlertHead}>
              <Ionicons name={(t?.icon as never) || "warning"} size={18} color={color} />
              <Text style={[styles.activeAlertText, { color }]} numberOfLines={3}>
                {activeAlert.text}
              </Text>
            </View>
            <TouchableOpacity
              style={styles.stopAlertBtn}
              onPress={() => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
                stopActiveAlert();
              }}
              activeOpacity={0.85}
              testID="map-stop-alert"
            >
              <Ionicons name="stop-circle" size={20} color="#fff" />
              <Text style={styles.stopAlertText}>Stopper l&apos;alerte</Text>
            </TouchableOpacity>
            {/* Réglages REPLIÉS par défaut (12/07) — la roue dentée déplie
                UNIQUEMENT le périmètre du mode actif ; les réglages avancés
                restent dans la page Réglages. */}
            <TouchableOpacity
              style={styles.alertGearRow}
              onPress={() => setAlertQuickOpen((v) => !v)}
              activeOpacity={0.8}
              testID="map-alert-gear"
            >
              <Ionicons name="settings-outline" size={15} color={theme.textDim} />
              <Text style={styles.alertGearText}>
                Périmètre d&apos;alerte — {navMode ? "Navigation" : "Vigie"}
              </Text>
              <Ionicons
                name={alertQuickOpen ? "chevron-up" : "chevron-down"}
                size={15}
                color={theme.textDim}
              />
            </TouchableOpacity>
            {alertQuickOpen && (
              <ScrollView style={styles.quickSettingsScroll} keyboardShouldPersistTaps="handled">
                <AlertSettingsPanel
                  variant="alert"
                  mode={navMode ? "nav" : "vigie"}
                  onOpenFullSettings={() => router.push("/profile/settings")}
                />
              </ScrollView>
            )}
          </View>
        );
      })()}

      {/* ── Popup « Signalement toujours là ? » (passage ≤ 500 m, 15/07) —
          jamais superposée à la séquence d'alerte. ── */}
      {!activeAlert && proximityQuestion && (
        <View style={[styles.proximityWrap, { top: insets.top + 58 }]} pointerEvents="box-none">
          <ProximityConfirmCard
            report={proximityQuestion.report}
            onYes={answerProximityYes}
            onNo={answerProximityNo}
            onTimeout={dismissProximity}
          />
        </View>
      )}

      {/* ── Popup unité d'échelle km/NM (tap sur une règle) — 16/07/2026 ── */}
      <Modal
        visible={unitPickerOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setUnitPickerOpen(false)}
      >
        <Pressable style={styles.unitPickerBackdrop} onPress={() => setUnitPickerOpen(false)}>
          <Pressable style={styles.unitPickerSheet} onPress={() => {}}>
            <View style={styles.unitPickerHeader}>
              <Ionicons name="settings-outline" size={18} color={theme.primary} />
              <Text style={styles.unitPickerTitle}>Unité des échelles</Text>
            </View>
            <TouchableOpacity
              style={[styles.unitPickerRow, mapUnit === "km" && styles.unitPickerRowActive]}
              onPress={() => { setMapUnit("km"); setUnitPickerOpen(false); }}
              testID="unit-picker-km"
            >
              <Ionicons
                name={mapUnit === "km" ? "radio-button-on" : "radio-button-off"}
                size={20}
                color={mapUnit === "km" ? theme.primary : theme.textDim}
              />
              <View style={{ flex: 1 }}>
                <Text style={styles.unitPickerLabel}>Kilomètres</Text>
                <Text style={styles.unitPickerHint}>Distances routières / usage général</Text>
              </View>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.unitPickerRow, mapUnit === "nm" && styles.unitPickerRowActive]}
              onPress={() => { setMapUnit("nm"); setUnitPickerOpen(false); }}
              testID="unit-picker-nm"
            >
              <Ionicons
                name={mapUnit === "nm" ? "radio-button-on" : "radio-button-off"}
                size={20}
                color={mapUnit === "nm" ? theme.primary : theme.textDim}
              />
              <View style={{ flex: 1 }}>
                <Text style={styles.unitPickerLabel}>Milles nautiques (NM)</Text>
                <Text style={styles.unitPickerHint}>1 NM = 1 852 m — usage marin</Text>
              </View>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>

      {/* ── Popup « Zone de veille » (bouton cloche+engrenage) — réglages
          rapides uniquement : zones Vigie/Nav + types de notification +
          accès à la page complète des paramètres. ── */}
      <Modal
        visible={alertSettingsOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setAlertSettingsOpen(false)}
      >
        <Pressable style={styles.alertSheetBackdrop} onPress={() => setAlertSettingsOpen(false)}>
          <Pressable style={styles.alertSheet} onPress={() => {}}>
            <View style={styles.alertSheetHandle} />
            <View style={styles.alertSheetHeader}>
              <Ionicons name="notifications" size={18} color="#F4A261" />
              <Text style={styles.alertSheetTitle}>Zone de veille</Text>
              <TouchableOpacity
                onPress={() => setAlertSettingsOpen(false)}
                style={styles.alertSheetClose}
                testID="alert-settings-close"
              >
                <Ionicons name="close" size={22} color={theme.textMute} />
              </TouchableOpacity>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: insets.bottom + 16 }}>
              <AlertSettingsPanel
                variant="quick"
                onOpenFullSettings={() => {
                  setAlertSettingsOpen(false);
                  router.push("/profile/settings");
                }}
              />
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>

      <View style={[styles.fabStack, { bottom: insets.bottom + 24 }]} pointerEvents="box-none">
        {!picking && (
          <View style={styles.fabRow} pointerEvents="box-none">
            {/* Signaler — décalé à GAUCHE de la colonne d'icônes (12/07) pour
                que toutes les icônes restent accessibles, même en paysage. */}
            <TouchableOpacity
              style={styles.fab}
              onPress={reportHere}
              activeOpacity={0.85}
              testID="map-report-fab"
            >
              <Ionicons name="add" size={30} color={theme.bg} />
              <Text style={styles.fabLabel}>Signaler</Text>
            </TouchableOpacity>
            <View style={styles.fabCol} pointerEvents="box-none">
            {/* Réglage des alertes sonores — cloche + engrenage : ouvre la
                popup rayon / types / répétitions. Visible dans les 2 modes. */}
            <TouchableOpacity
              style={styles.alertCfgBtn}
              onPress={() => {
                Haptics.selectionAsync().catch(() => {});
                setAlertSettingsOpen(true);
              }}
              activeOpacity={0.85}
              testID="map-alert-settings"
              accessibilityLabel="Zone de veille et alertes"
            >
              <Ionicons name="notifications" size={20} color="#F4A261" />
              <View style={styles.alertCfgGear}>
                <Ionicons name="settings-sharp" size={9} color={theme.bg} />
              </View>
            </TouchableOpacity>
            {/* Phase K.13 — Radar-effect toggle. Only visible in Vigie mode
                (basic/light mode). Placed at the top of the FAB stack, right
                above the navigation button. Solid red glow when ON to mirror
                the on-map radar ping; dimmed grey with a strike when OFF. */}
            {!navMode && (
              <TouchableOpacity
                style={[
                  styles.radarBtn,
                  radarEnabled ? styles.radarBtnOn : styles.radarBtnOff,
                ]}
                onPress={() => {
                  const next = !radarEnabled;
                  setRadarEnabled(next);
                  Haptics.selectionAsync().catch(() => {});
                  showToast(
                    "info",
                    next ? "Radar activé — pulsation d’alerte visible" : "Radar désactivé",
                  );
                }}
                activeOpacity={0.85}
                testID="map-radar-toggle"
                accessibilityRole="switch"
                accessibilityState={{ checked: radarEnabled }}
                accessibilityLabel={radarEnabled ? "Désactiver le radar" : "Activer le radar"}
              >
                <Ionicons
                  name={radarEnabled ? "radio" : "radio-outline"}
                  size={22}
                  color={radarEnabled ? "#E63946" : theme.textMute}
                />
                {!radarEnabled && <View style={styles.radarBtnStrike} />}
              </TouchableOpacity>
            )}
            <TouchableOpacity
              style={[styles.navBtn, navMode && styles.navBtnOn]}
              onPress={() => {
                const next = !navMode;
                setNavMode(next);
                if (next && permDenied) setPermDenied(false); // give it another try
                logger.event("nav", next ? "nav_start" : "nav_stop", {
                  hasUserLoc: !!userLoc,
                  speed: userSpeed,
                  heading: userHeading,
                  offlineState: offline,
                });
                showToast("info", next ? "Navigation activée — cône + projection" : "Mode Vigie — alertes 360°");
              }}
              onLongPress={() => {
                // Phase K — Long-press = quick access to cone angle config.
                // Only opens when nav mode is active so users understand the
                // link between the cone and the mode.
                if (!navMode) {
                  setNavMode(true);
                }
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
                setConeModalOpen(true);
              }}
              delayLongPress={450}
              activeOpacity={0.85}
              testID="map-nav-toggle"
            >
              {/* Phase I — Toggle navigation button. Off: grey outline arrow.
                  On: red filled arrow (matches the boat marker on the map). */}
              <View style={[styles.navArrow, navMode ? styles.navArrowOn : styles.navArrowOff]} />
            </TouchableOpacity>

            {/* Phase K — Dedicated mini-cone button, visible in Navigation
                mode only. Shape mimics a cone (triangle) so the affordance
                is obvious. Opens the same config modal as the long-press. */}
            {navMode && (
              <TouchableOpacity
                style={styles.coneBtn}
                onPress={() => setConeModalOpen(true)}
                activeOpacity={0.85}
                testID="map-cone-config"
                accessibilityLabel={`Réglage du cône Navigation, ${coneAngleDeg}°`}
              >
                <View style={styles.coneBtnArc} />
                <Text style={styles.coneBtnLabel}>{coneAngleDeg}°</Text>
              </TouchableOpacity>
            )}

            {/* Phase E.5 — Manual refresh button (between navigation & recenter). */}
            <TouchableOpacity
              style={styles.refreshBtn}
              onPress={() => { pollDismiss(); void pollRefresh(); }}
              disabled={pollRefreshing}
              activeOpacity={0.85}
              testID="map-refresh-button"
              accessibilityLabel={
                pollLastAt
                  ? `Rafraîchir les signalements. Dernier rafraîchissement ${formatLastRefresh(pollLastAt, nowTick)}.`
                  : "Rafraîchir les signalements"
              }
            >
              {pollRefreshing ? (
                <ActivityIndicator size="small" color={theme.text} />
              ) : (
                <Ionicons name="refresh" size={20} color={theme.text} />
              )}
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.locBtn}
              onPress={recenter}
              activeOpacity={0.85}
              testID="map-recenter-button"
            >
              <Ionicons name="locate" size={20} color={theme.text} />
            </TouchableOpacity>
            </View>
          </View>
        )}
      </View>

      {/* Boutons zoom +/- (12/07/2026) — déplaçables par appui long (13/07),
          position persistée dans le compte utilisateur. */}
      {!picking && (
        <DraggableZoomButtons
          bottom={insets.bottom + 24 + 44 + 12}
          serverPos={user?.zoom_btn_pos ?? null}
          onZoomIn={() => mapRef.current?.zoomIn()}
          onZoomOut={() => mapRef.current?.zoomOut()}
        />
      )}

      {/* Loupe (12/07/2026) — bas GAUCHE : recherche par ID COURT. */}
      {!picking && (
        <TouchableOpacity
          style={[styles.searchFab, { bottom: insets.bottom + 24 }]}
          onPress={() => { setSearchErr(null); setSearchOpen(true); }}
          activeOpacity={0.85}
          testID="map-search-fab"
        >
          <Ionicons name="search" size={20} color={theme.text} />
        </TouchableOpacity>
      )}

      {/* Modale de recherche par ID COURT. */}
      <Modal
        visible={searchOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setSearchOpen(false)}
      >
        <Pressable style={styles.searchBackdrop} onPress={() => setSearchOpen(false)}>
          <Pressable style={styles.searchSheet} onPress={() => {}}>
            <View style={styles.searchTitleRow}>
              <Ionicons name="search" size={18} color={theme.primary} />
              <Text style={styles.searchTitle}>Rechercher un signalement</Text>
            </View>
            <Text style={styles.searchHint}>
              Entrez le code affiché sur un post partagé (ex. K7M2PQ4X).
            </Text>
            <TextInput
              style={styles.searchInput}
              value={searchCode}
              onChangeText={(v) => { setSearchCode(v.toUpperCase()); setSearchErr(null); }}
              placeholder="CODE DU SIGNALEMENT"
              placeholderTextColor={theme.textDim}
              autoCapitalize="characters"
              autoCorrect={false}
              maxLength={12}
              autoFocus
              returnKeyType="search"
              onSubmitEditing={searchByCode}
              testID="map-search-input"
            />
            {searchErr ? <Text style={styles.searchErr}>{searchErr}</Text> : null}
            <TouchableOpacity
              style={[styles.searchBtn, (searchBusy || searchCode.trim().length < 4) && { opacity: 0.5 }]}
              onPress={searchByCode}
              disabled={searchBusy || searchCode.trim().length < 4}
              testID="map-search-submit"
            >
              {searchBusy ? (
                <ActivityIndicator color={theme.bg} />
              ) : (
                <>
                  <Ionicons name="search" size={18} color={theme.bg} />
                  <Text style={styles.searchBtnTxt}>Rechercher</Text>
                </>
              )}
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>

      {picking && (
        <View style={[styles.pickBar, { paddingBottom: insets.bottom + 12 }]}>
          <View style={styles.pickTitleRow}>
            <Ionicons
              name={shiftReportId ? "swap-horizontal" : "add-circle"}
              size={20}
              color={shiftReportId ? theme.warning : theme.danger}
            />
            <Text style={styles.pickTitle}>
              {shiftReportId
                ? (authorShiftMode
                    ? "Glissez la carte pour repositionner votre signalement"
                    : "Glissez la carte vers la vraie position")
                : "Faites glisser la carte pour placer le point"}
            </Text>
          </View>
          <Text style={styles.pickCoords}>
            {pickedPoint.lat.toFixed(5)}°, {pickedPoint.lng.toFixed(5)}°
          </Text>
          <View style={styles.pickActions}>
            <TouchableOpacity
              style={styles.pickCancel}
              onPress={cancelPick}
              disabled={submittingShift}
              testID="pick-cancel"
            >
              <Ionicons name="close" size={20} color={theme.text} />
              <Text style={styles.pickCancelText}>Annuler</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.pickContinue, submittingShift && { opacity: 0.6 }]}
              onPress={confirmPick}
              disabled={submittingShift}
              testID="pick-continue"
            >
              {submittingShift ? (
                <ActivityIndicator color={theme.bg} />
              ) : (
                <>
                  <Ionicons name="checkmark" size={20} color={theme.bg} />
                  <Text style={styles.pickContinueText}>
                    {shiftReportId
                      ? (authorShiftMode ? "Modifier mon point" : "Proposer ce point")
                      : "Signaler ici"}
                  </Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        </View>
      )}

      {loading && Platform.OS !== "web" && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.primary} />
        </View>
      )}

      {/* PHASE 4 — Filter bottom-sheet (multi-select). Lives above the map. */}
      <Modal
        visible={filterSheetOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setFilterSheetOpen(false)}
      >
        <Pressable style={styles.sheetBackdrop} onPress={() => setFilterSheetOpen(false)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation?.()}>
            <View style={styles.sheetHandle} />
            <View style={styles.sheetHeader}>
              <Text style={styles.sheetTitle}>Affichage de la carte</Text>
              <TouchableOpacity onPress={() => setFilterSheetOpen(false)} testID="map-filter-close">
                <Ionicons name="close" size={22} color={theme.text} />
              </TouchableOpacity>
            </View>

            <View style={styles.sheetSectionRow}>
              <Text style={styles.sheetSection}>Types de signalements</Text>
              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                <TouchableOpacity
                  onPress={() => setSelectedTypes(new Set())}
                  testID="map-filter-select-all"
                >
                  <Text style={styles.sheetLink}>Tout afficher</Text>
                </TouchableOpacity>
                <Text style={styles.sheetLinkSep}>·</Text>
                <TouchableOpacity
                  onPress={() => setSelectedTypes(new Set(REPORT_TYPES.map((t) => t.id)))}
                  testID="map-filter-invert"
                >
                  <Text style={styles.sheetLink}>Inverser</Text>
                </TouchableOpacity>
              </View>
            </View>

            <ScrollView style={{ maxHeight: 340 }} contentContainerStyle={{ paddingBottom: spacing.sm }}>
              {/* When the Set is empty we treat it as "all selected" for display purposes. */}
              {REPORT_TYPES.map((t) => {
                const isAll = selectedTypes.size === 0;
                const on = isAll || selectedTypes.has(t.id);
                return (
                  <TouchableOpacity
                    key={t.id}
                    style={[styles.sheetRow, on && styles.sheetRowOn]}
                    onPress={() => {
                      // First explicit toggle when in "all" mode: keep ALL EXCEPT this one
                      // (= unselect t). This matches the natural mental model.
                      if (isAll) {
                        const next = new Set(REPORT_TYPES.map((x) => x.id));
                        next.delete(t.id);
                        setSelectedTypes(next);
                      } else {
                        toggleType(t.id);
                      }
                    }}
                    testID={`map-filter-type-${t.id}`}
                  >
                    <View style={[styles.sheetDot, { backgroundColor: t.color }]}>
                      <Ionicons name={t.icon as never} size={16} color={theme.bg} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.sheetRowLabel}>{t.label}</Text>
                      <Text style={styles.sheetRowDesc}>{t.short}</Text>
                    </View>
                    <Ionicons
                      name={on ? "checkbox" : "square-outline"}
                      size={22}
                      color={on ? theme.primary : theme.textMute}
                    />
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            <View style={styles.sheetDivider} />

            <Text style={styles.sheetSection}>Préférences d&apos;affichage</Text>
            <View style={styles.sheetTogglesRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.sheetRowLabel}>Masquer les faux signalements</Text>
                <Text style={styles.sheetRowDesc}>
                  Cache les points marqués comme faux par la communauté.
                </Text>
              </View>
              <Switch
                value={hideFakes}
                onValueChange={setHideFakes}
                trackColor={{ false: theme.border, true: theme.primary }}
                thumbColor={hideFakes ? theme.bg : theme.textDim}
                testID="map-hide-fakes-toggle"
              />
            </View>

            <TouchableOpacity
              style={styles.sheetApply}
              onPress={() => {
                setFilterSheetOpen(false);
                fetchReports();
              }}
              testID="map-filter-apply"
            >
              <Text style={styles.sheetApplyText}>Appliquer</Text>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>

      <CoordsPopup
        visible={coordsPopupOpen}
        lat={userLoc?.lat ?? null}
        lng={userLoc?.lng ?? null}
        onClose={() => setCoordsPopupOpen(false)}
      />

      {/* Phase K — Cone config modal. Presets + slider (via chips of common
          values) to keep it thumb-friendly. Live preview with a mini SVG-ish
          cone illustration built out of rotated rectangles. */}
      <Modal
        visible={coneModalOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setConeModalOpen(false)}
      >
        <Pressable style={styles.sheetBackdrop} onPress={() => setConeModalOpen(false)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation?.()}>
            <View style={styles.sheetHandle} />
            <View style={styles.sheetHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.sheetTitle}>Cône Navigation</Text>
                <Text style={styles.sheetSubtitle}>
                  Reste focus sur les signalements devant toi.
                </Text>
              </View>
              <TouchableOpacity onPress={() => setConeModalOpen(false)} testID="map-cone-close">
                <Ionicons name="close" size={22} color={theme.text} />
              </TouchableOpacity>
            </View>

            {/* Phase K — Live preview of the double-cone shape (flare +
                corridor). Boat is at the bottom apex; the shape opens
                upward. The corridor rectangle above the flare uses the same
                width as the flare's base, exactly like on the map. */}
            {(() => {
              const halfDeg = coneAngleDeg / 2;
              // Flare = 40 px tall, its base width scales with tan(halfAngle).
              const flareHeightPx = 40;
              const halfWidthPx = Math.max(6, flareHeightPx * Math.tan((halfDeg * Math.PI) / 180));
              const corridorWidthPx = halfWidthPx * 2;
              const corridorHeightPx = 78;
              return (
                <View style={styles.conePreviewBox}>
                  <View style={{ alignItems: "center", justifyContent: "flex-end", flex: 1, paddingBottom: 4 }}>
                    <View style={[
                      styles.conePreviewCorridor,
                      { width: corridorWidthPx, height: corridorHeightPx },
                    ]} />
                    <View style={[
                      styles.conePreviewFlare,
                      {
                        borderLeftWidth: halfWidthPx,
                        borderRightWidth: halfWidthPx,
                        borderTopWidth: flareHeightPx,
                      },
                    ]} />
                    <View style={styles.conePreviewBoatDot} />
                  </View>
                  <Text style={styles.conePreviewLabel}>{coneAngleDeg}°</Text>
                  <Text style={styles.conePreviewDim}>
                    évasement 1.0 km · corridor {(2 * 1 * Math.sin((halfDeg * Math.PI) / 180)).toFixed(2)} km
                  </Text>
                </View>
              );
            })()}

            <View style={styles.coneSliderRow}>
              <Text style={styles.sheetSection}>Angle du cône</Text>
              <Text style={styles.coneSliderValue}>{coneAngleDeg}°</Text>
            </View>
            <Slider
              testID="map-cone-slider"
              style={styles.coneSlider}
              minimumValue={CONE_ANGLE_MIN}
              maximumValue={CONE_ANGLE_MAX}
              step={1}
              value={coneAngleDeg}
              onValueChange={(v) => setConeAngleDeg(Math.round(v))}
              minimumTrackTintColor="#F4A261"
              maximumTrackTintColor={theme.border}
              thumbTintColor="#F4A261"
            />
            <View style={styles.coneSliderScale}>
              <Text style={styles.coneSliderScaleText}>{CONE_ANGLE_MIN}°</Text>
              <Text style={styles.coneSliderScaleText}>{CONE_ANGLE_MAX}°</Text>
            </View>

            {/* 15/07/2026 (demande user) — distance du cône réglable ICI,
                sans passer par la page Réglages. Même réglage que « Zone de
                veille — Navigation » (zoneNavM), mêmes bornes. */}
            <View style={styles.coneDistanceBlock}>
              <ZoneField
                icon="navigate"
                label="Distance du cône"
                hint=""
                valueM={voiceSettings.zoneNavM ?? 9260}
                onCommitM={(m) => { void updateVoiceSettings({ zoneNavM: m }); }}
                testIDPrefix="map-cone-distance"
                showHint={false}
                sliderMaxKm={NAV_SLIDER_MAX_KM}
                inputMaxKm={NAV_INPUT_MAX_KM}
              />
            </View>

            <View style={styles.coneInfoRow}>
              <Ionicons name="information-circle-outline" size={16} color={theme.textDim} />
              <Text style={styles.coneInfoText}>
                Évasement fixe 1 km, puis corridor parallèle (largeur constante) jusqu&apos;à la distance choisie.{"\n"}
                Signalements HORS corridor : grisés à 30 % (visibles mais non-alertants).
              </Text>
            </View>

            <TouchableOpacity
              style={styles.sheetApply}
              onPress={() => setConeModalOpen(false)}
              testID="map-cone-apply"
            >
              <Text style={styles.sheetApplyText}>Terminé</Text>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>

      {/* Compteur de vitesse agrandi — bande « Verre ». */}
      <SpeedometerOverlay
        visible={speedoOpen}
        onClose={() => setSpeedoOpen(false)}
        speedMs={userSpeed}
        heading={userHeading}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  topOverlay: { position: "absolute", top: 0, left: 0, right: 0, gap: spacing.sm, paddingTop: spacing.sm },
  // Paysage : couloir libre à droite (44 px d'icône + marge) pour que les
  // pills ET les bandeaux ne passent JAMAIS sous la colonne de FABs.
  topOverlayLandscape: { paddingRight: 44 + spacing.md + spacing.sm },
  topRow: {
    flexDirection: "row", justifyContent: "space-between", gap: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  badge: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(11,19,43,0.85)", paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.border,
    flexShrink: 1,
  },
  badgeText: {
    color: theme.text, fontWeight: "700", fontSize: 11,
    fontVariant: ["tabular-nums"], flexShrink: 1,
  },
  // Compteur de vitesse — pill compacte de la barre du haut (10/07).
  topSpeedPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(11,19,43,0.85)", paddingHorizontal: 8, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.border,
  },
  topSpeedText: {
    color: theme.text, fontWeight: "800", fontSize: 11,
    fontVariant: ["tabular-nums"],
  },
  demoBadge: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(244,162,97,0.18)",
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.warning,
  },
  demoText: { color: theme.warning, fontWeight: "800", fontSize: 12 },
  radiusBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(11,19,43,0.85)", paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.border,
  },
  radiusBtnText: { color: theme.primary, fontWeight: "800", fontSize: 12 },
  // Phase 3c — bell button (in-app notifications). Compact circular pill next
  // to the radius button. Shows a red badge with the unread count.
  bellBtn: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: "rgba(11,19,43,0.85)",
    borderWidth: 1, borderColor: theme.border,
    alignItems: "center", justifyContent: "center",
    position: "relative",
  },
  bellBadge: {
    position: "absolute", top: -4, right: -4,
    minWidth: 18, height: 18, borderRadius: 9,
    backgroundColor: "#E63946",
    alignItems: "center", justifyContent: "center",
    paddingHorizontal: 4,
    borderWidth: 1.5, borderColor: theme.bg,
  },
  bellBadgeText: {
    color: "#FFFFFF", fontWeight: "900", fontSize: 10,
    letterSpacing: 0,
  },
  // Phase 3c — welcome banner (one-shot, first mount of the session).
  welcomeCard: {
    marginTop: spacing.sm,
    marginHorizontal: spacing.md,
    paddingHorizontal: spacing.sm, paddingVertical: 10,
    borderRadius: radii.md,
    backgroundColor: "rgba(28, 37, 65, 0.96)",
    borderWidth: 1, borderColor: theme.primary,
    flexDirection: "row", alignItems: "center", gap: 10,
    shadowColor: "#000",
    shadowOpacity: 0.35,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 8,
  },
  welcomeIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  welcomeTitle: { color: theme.text, fontWeight: "900", fontSize: 13 },
  welcomeText: { color: theme.textDim, fontSize: 12, marginTop: 2, lineHeight: 15 },
  welcomeBtn: {
    backgroundColor: theme.primary,
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: radii.pill,
    minHeight: 36,
    alignItems: "center", justifyContent: "center",
  },
  welcomeBtnText: { color: theme.bg, fontWeight: "900", fontSize: 12 },
  // Bascule auto Vigie ⇄ Navigation — bannière (mêmes textes/boutons que la
  // welcome card, accent orange pour la distinguer).
  autoSwitchCard: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: "#F4A261",
    padding: spacing.sm, marginTop: spacing.sm,
  },
  autoSwitchIcon: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: "#F4A261",
    alignItems: "center", justifyContent: "center",
  },
  welcomeClose: {
    width: 22, height: 22, borderRadius: 11,
    alignItems: "center", justifyContent: "center",
    marginLeft: 2,
  },
  filterRow: { height: 48, justifyContent: "center" },
  chip: {
    flexShrink: 0, flexDirection: "row", alignItems: "center", gap: 6,
    height: 36, paddingHorizontal: 14, borderRadius: radii.pill,
    backgroundColor: "rgba(11,19,43,0.92)", borderWidth: 1, borderColor: theme.border,
  },
  chipText: { color: theme.text, fontWeight: "800", fontSize: 12 },
  permBox: {
    flexDirection: "row", gap: 8, alignItems: "center", marginHorizontal: spacing.md,
    backgroundColor: "rgba(244,162,97,0.15)", borderColor: theme.warning, borderWidth: 1,
    padding: spacing.sm, borderRadius: radii.md,
  },
  permText: { color: theme.text, flex: 1, fontSize: 12 },
  fabStack: { position: "absolute", right: spacing.md, alignItems: "flex-end", gap: spacing.sm },
  // 12/07 — Signaler à GAUCHE de la colonne d'icônes ; icônes légèrement
  // réduites (44 px) pour que la pile tienne aussi en mode paysage.
  fabRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  fabCol: { alignItems: "center", gap: spacing.sm },
  // Boutons zoom → composant DraggableZoomButtons (13/07/2026).
  // Loupe ID COURT — bas gauche, discret (12/07/2026).
  searchFab: {
    position: "absolute", left: spacing.md,
    width: 44, height: 44, borderRadius: 22,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.borderStrong,
    shadowColor: "#000", shadowOpacity: 0.3, shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 }, elevation: 4,
  },
  searchBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  searchSheet: {
    width: "100%", maxWidth: 420, backgroundColor: theme.bg2,
    borderRadius: radii.lg, padding: spacing.lg, gap: spacing.sm,
    borderWidth: 1, borderColor: theme.border,
  },
  searchTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  searchTitle: { color: theme.text, fontWeight: "800", fontSize: 16 },
  searchHint: { color: theme.textDim, fontSize: 13 },
  searchInput: {
    backgroundColor: theme.bg, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    color: theme.text, fontWeight: "800", fontSize: 18, letterSpacing: 2,
    paddingHorizontal: spacing.md, paddingVertical: 12, textAlign: "center",
  },
  searchErr: { color: theme.danger, fontSize: 13, fontWeight: "600" },
  searchBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.primary, borderRadius: radii.md, paddingVertical: 12,
  },
  searchBtnTxt: { color: theme.bg, fontWeight: "900", fontSize: 15 },
  locBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border,
  },
  // Phase E.5 — Manual refresh button; sits between nav toggle and locate.
  refreshBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border,
  },
  // Phase E.5 — "N nouveaux signalements" banner (top). Full-width chip that
  // sits below the top filters row, above the map markers.
  newBanner: {
    marginTop: spacing.sm,
    marginHorizontal: 0,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radii.md,
    backgroundColor: theme.primary,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    shadowColor: "#000",
    shadowOpacity: 0.25,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
    elevation: 6,
  },
  newBannerDot: {
    width: 8, height: 8, borderRadius: 4,
    backgroundColor: theme.bg,
  },
  newBannerText: {
    flex: 1,
    color: theme.bg,
    fontWeight: "800",
    fontSize: 13,
    letterSpacing: 0.2,
  },
  // Phase I — Toggle nav button. Same circular footprint as locBtn, sits
  // right above it in the FAB stack. Triangle is built with CSS borders
  // so we don't ship another asset.
  // Phase K.13 — Radar toggle button (Vigie mode only). Same 48×48 footprint
  // as navBtn to align vertically. Uses Ionicons "radio" glyph which reads
  // universally as radar/wave emission. Toggled visually via colour + border
  // + a small strike bar overlay when disabled.
  alertCfgBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.bg2,
    borderWidth: 1.5,
    borderColor: "#F4A261",
    shadowColor: "#000",
    shadowOpacity: 0.35,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
    elevation: 5,
  },
  alertCfgGear: {
    position: "absolute",
    right: 4,
    bottom: 4,
    width: 15,
    height: 15,
    borderRadius: 8,
    backgroundColor: "#F4A261",
    alignItems: "center",
    justifyContent: "center",
  },
  activeAlertCard: {
    position: "absolute",
    left: 12,
    right: 12,
    zIndex: 60,
    backgroundColor: "rgba(11,19,43,0.96)",
    borderWidth: 1.5,
    borderRadius: 16,
    padding: 14,
    gap: 10,
  },
  activeAlertHead: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  activeAlertText: { flex: 1, fontWeight: "800", fontSize: 13, lineHeight: 18 },
  stopAlertBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#E63946",
    borderRadius: 12,
    paddingVertical: 13,
    minHeight: 48,
  },
  stopAlertText: { color: "#fff", fontWeight: "900", fontSize: 15 },
  alertGearRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 8, minHeight: 36,
  },
  alertGearText: { color: theme.textDim, fontWeight: "800", fontSize: 12 },
  quickSettingsScroll: { maxHeight: 290 },
  stoppedAlertPill: {
    position: "absolute",
    left: 12,
    zIndex: 60,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(11,19,43,0.94)",
    borderWidth: 1,
    borderRadius: 20,
    paddingLeft: 12,
    paddingRight: 6,
    paddingVertical: 7,
  },
  stoppedAlertText: { color: theme.textMute, fontWeight: "700", fontSize: 12 },
  reactivateBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 14,
    minHeight: 30,
  },
  reactivateBtnText: { color: theme.bg, fontWeight: "900", fontSize: 12 },
  stoppedAlertClose: { padding: 6 },
  alertSheetBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  alertSheet: {
    backgroundColor: theme.bg2,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 18,
    paddingTop: 8,
    maxHeight: "82%",
  },
  alertSheetHandle: {
    alignSelf: "center",
    width: 42,
    height: 4,
    borderRadius: 2,
    backgroundColor: theme.border,
    marginBottom: 8,
  },
  alertSheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 10,
  },
  alertSheetTitle: { flex: 1, color: theme.text, fontWeight: "900", fontSize: 16 },
  alertSheetClose: { padding: 6 },
  radarBtn: {
    width: 44, height: 44, borderRadius: 22,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1,
  },
  radarBtnOn: {
    backgroundColor: "rgba(230,57,70,0.15)",
    borderColor: "#E63946",
    shadowColor: "#E63946", shadowOpacity: 0.55, shadowRadius: 10,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
  radarBtnOff: {
    backgroundColor: theme.bg2,
    borderColor: theme.border,
  },
  radarBtnStrike: {
    position: "absolute",
    left: 8, right: 8, top: 22,
    height: 2, borderRadius: 1,
    backgroundColor: theme.textMute,
    transform: [{ rotate: "-45deg" }],
  },
  navBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border,
  },
  navBtnOn: {
    backgroundColor: "rgba(230,57,70,0.15)",
    borderColor: "#E63946",
    shadowColor: "#E63946", shadowOpacity: 0.55, shadowRadius: 10,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
  navArrow: {
    width: 0, height: 0,
    borderLeftWidth: 9, borderRightWidth: 9, borderBottomWidth: 18,
    borderLeftColor: "transparent", borderRightColor: "transparent",
  },
  navArrowOff: { borderBottomColor: theme.textMute },
  navArrowOn: { borderBottomColor: "#E63946" },
  // Phase K — Mini-cone config button (visible when navMode is ON).
  coneBtn: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "rgba(244,162,97,0.18)",
    borderWidth: 1, borderColor: "#F4A261",
    alignItems: "center", justifyContent: "center",
    shadowColor: "#F4A261", shadowOpacity: 0.4, shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 }, elevation: 6,
  },
  coneBtnArc: {
    width: 0, height: 0,
    borderLeftWidth: 8, borderRightWidth: 8, borderBottomWidth: 14,
    borderLeftColor: "transparent", borderRightColor: "transparent",
    borderBottomColor: "#F4A261",
    marginBottom: 1,
  },
  coneBtnLabel: {
    color: "#F4A261", fontWeight: "900", fontSize: 9, letterSpacing: 0,
    marginTop: -1,
  },
  sheetSubtitle: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  // Cone preview: double-cone (flare + corridor) with the boat at the bottom
  // apex. Corridor rectangle sits above the flare triangle (which points
  // DOWN, apex at bottom). Colors + subtle border echo the map cone.
  conePreviewBox: {
    height: 170,
    marginBottom: spacing.md, marginTop: 4,
    backgroundColor: "rgba(11,19,43,0.55)",
    borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    position: "relative",
    overflow: "hidden",
  },
  conePreviewCorridor: {
    backgroundColor: "rgba(244,162,97,0.18)",
    borderTopWidth: 2.2, borderLeftWidth: 2.2, borderRightWidth: 2.2,
    borderColor: "#F4A261",
    borderTopLeftRadius: 3, borderTopRightRadius: 3,
  },
  conePreviewFlare: {
    // Triangle pointing DOWN (apex at bottom): borderTop is filled, others
    // are transparent. Sizes are set inline based on the angle so the flare
    // aligns pixel-perfect with the corridor width.
    width: 0, height: 0,
    borderStyle: "solid",
    borderLeftColor: "transparent",
    borderRightColor: "transparent",
    borderTopColor: "rgba(244,162,97,0.28)",
    marginTop: -1,
  },
  conePreviewBoatDot: {
    width: 14, height: 14, borderRadius: 7,
    backgroundColor: "#E63946",
    borderWidth: 2, borderColor: "#0B132B",
    marginTop: -6,
    shadowColor: "#E63946", shadowOpacity: 0.5,
    shadowRadius: 6, shadowOffset: { width: 0, height: 0 },
  },
  conePreviewLabel: {
    position: "absolute", top: 10, right: 14,
    color: "#F4A261", fontWeight: "900", fontSize: 20,
    letterSpacing: 0.5,
  },
  conePreviewDim: {
    position: "absolute", left: 12, bottom: 8, right: 60,
    color: "rgba(232,236,251,0.55)", fontSize: 10,
    fontWeight: "500", letterSpacing: 0.2,
  },
  conePresetRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 8,
    marginTop: spacing.xs, marginBottom: spacing.md,
  },
  // Phase K — Slider row: label ⟷ current value in bold amber.
  coneSliderRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: spacing.xs,
  },
  coneSliderValue: {
    color: "#F4A261", fontWeight: "900", fontSize: 20,
    letterSpacing: 0.5,
  },
  coneSlider: {
    width: "100%",
    // 16/07/2026 (retour terrain) — hauteur portée à 56 px pour élargir la
    // zone tactile sur la popup de réglage rapide du cône.
    height: 56,
    marginTop: 2,
  },
  // ── Popup unité d'échelle (16/07/2026) ────────────────────────────────
  unitPickerBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center", alignItems: "center", padding: spacing.lg,
  },
  unitPickerSheet: {
    width: "100%", maxWidth: 380,
    backgroundColor: theme.bg2, borderRadius: 14,
    borderWidth: 1, borderColor: theme.border,
    padding: spacing.md, gap: 10,
  },
  unitPickerHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  unitPickerTitle: { color: theme.text, fontSize: 15, fontWeight: "800" },
  unitPickerRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    minHeight: 56,
    borderRadius: 10, backgroundColor: theme.bg3,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 12, paddingVertical: 10,
  },
  unitPickerRowActive: { borderColor: theme.primary },
  unitPickerLabel: { color: theme.text, fontSize: 14, fontWeight: "800" },
  unitPickerHint: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  coneSliderScale: {
    flexDirection: "row", justifyContent: "space-between",
    paddingHorizontal: 6, marginTop: -6, marginBottom: spacing.md,
  },
  coneSliderScaleText: {
    color: theme.textDim, fontSize: 11, fontWeight: "600",
  },
  coneInfoRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    paddingHorizontal: 4, paddingVertical: 8,
    marginBottom: spacing.sm,
  },
  coneDistanceBlock: {
    borderTopWidth: 1, borderTopColor: theme.border,
    paddingTop: spacing.md, marginBottom: spacing.sm,
  },
  proximityWrap: { position: "absolute", left: 12, right: 12, zIndex: 40 },
  coneInfoText: { color: theme.textDim, fontSize: 11, lineHeight: 15, flex: 1 },
  fab: {
    backgroundColor: theme.primary, paddingHorizontal: 18, paddingVertical: 14,
    borderRadius: radii.pill, flexDirection: "row", alignItems: "center", gap: 6,
    minHeight: 56, elevation: 8,
  },
  fabLabel: { color: theme.bg, fontWeight: "900", fontSize: 16, marginLeft: 2 },
  pickBar: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: theme.bg2, borderTopWidth: 2, borderTopColor: theme.primary,
    padding: spacing.md, gap: spacing.sm,
  },
  pickTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  pickTitle: { color: theme.text, fontWeight: "800", fontSize: 14, flex: 1 },
  pickCoords: { color: theme.primary, fontWeight: "900", fontSize: 16 },
  pickActions: { flexDirection: "row", gap: spacing.sm },
  pickCancel: {
    flex: 1, backgroundColor: theme.bg3, padding: 14, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderWidth: 1, borderColor: theme.border, minHeight: 52,
  },
  pickCancelText: { color: theme.text, fontWeight: "800" },
  pickContinue: {
    flex: 2, backgroundColor: theme.primary, padding: 14, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 52,
  },
  pickContinueText: { color: theme.bg, fontWeight: "900", fontSize: 15 },
  loading: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  // PHASE 4 — Bottom-sheet filter.
  sheetBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.bg2, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    paddingHorizontal: spacing.md, paddingTop: spacing.sm, paddingBottom: spacing.lg,
    borderTopWidth: 1, borderColor: theme.border,
  },
  sheetHandle: {
    width: 44, height: 4, borderRadius: 2, backgroundColor: theme.border,
    alignSelf: "center", marginBottom: spacing.sm,
  },
  sheetHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  sheetTitle: { color: theme.text, fontWeight: "900", fontSize: 18 },
  sheetSectionRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    marginTop: spacing.xs, marginBottom: spacing.xs,
  },
  sheetSection: { color: theme.textDim, fontWeight: "800", fontSize: 12, textTransform: "uppercase", letterSpacing: 0.6 },
  sheetLink: { color: theme.primary, fontWeight: "800", fontSize: 12 },
  sheetLinkSep: { color: theme.textMute, fontWeight: "800", fontSize: 12 },
  sheetRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 12, paddingHorizontal: 10, borderRadius: radii.md,
    backgroundColor: theme.bg3, marginVertical: 4, borderWidth: 1, borderColor: "transparent",
  },
  sheetRowOn: { borderColor: theme.primary },
  sheetDot: { width: 30, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center" },
  sheetRowLabel: { color: theme.text, fontWeight: "800", fontSize: 14 },
  sheetRowDesc: { color: theme.textDim, fontSize: 12, marginTop: 1 },
  sheetDivider: { height: 1, backgroundColor: theme.border, marginVertical: spacing.sm },
  sheetTogglesRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 10, marginBottom: spacing.sm,
  },
  sheetApply: {
    backgroundColor: theme.primary, paddingVertical: 14, borderRadius: radii.md,
    alignItems: "center", justifyContent: "center", marginTop: spacing.sm,
  },
  sheetApplyText: { color: theme.bg, fontWeight: "900", fontSize: 15 },
});
