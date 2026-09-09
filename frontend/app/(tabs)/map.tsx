import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  ScrollView,
  Share,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter, useFocusEffect, useLocalSearchParams } from "expo-router";
import * as Location from "expo-location";
import * as Haptics from "expo-haptics";

import { MarineMap, type MarineMapHandle, type RouteTapDanger } from "@/src/components/MarineMap";
import { api, type ComputedRoute, type ReportItem, type RouteErrorDetail, type SavedRoute, type Seamark } from "@/src/api/client";
import { theme, spacing } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";
import { REPORT_TYPES, TYPE_BY_ID, type ReportTypeId } from "@/src/lib/report-types";
import { useAuth } from "@/src/auth/AuthContext";
import { saveReportsCache, loadReportsCache } from "@/src/lib/reports-cache";
import { consumeLastCreated } from "@/src/lib/last-created";
import { useVoiceSettings } from "@/src/lib/voice-settings";
import { useSoundAlertWatcher } from "@/src/lib/sound-alert";
import { getWarmLocation, startGpsWarmup } from "@/src/lib/gps-warmup";
import { vibrateAlert, stopAlertFeedback } from "@/src/lib/alert-vibration";
import { playAlertHorn, playAnchorAlarmSound, playRouteDeviationSound, stopAlertHorn, stopAnchorAlarmSound, stopRouteDeviationSound } from "@/src/lib/alert-sound";
import { useProximityConfirm } from "@/src/lib/proximity-confirm";
import { ProximityConfirmCard } from "@/src/components/ProximityConfirmCard";
import { AlertSettingsPanel } from "@/src/components/AlertSettingsPanel";
import { SpeedometerOverlay } from "@/src/components/SpeedometerOverlay";
import { RouteCard } from "@/src/components/RouteCard";
import { RouteCompareBar, BASE_COLOR, VARIANT_COLOR } from "@/src/components/RouteCompareBar";
import { EnginePickerModal } from "@/src/components/EnginePickerModal";
import { compareRoutes, diffCount, type RouteDiff } from "@/src/lib/routeCompare";
import { RouteNavPanel } from "@/src/components/RouteNavPanel";
import {
  ANCHOR_RADIUS_DEFAULT_M,
  getAnchorPos,
  getAnchorRadiusM,
  setAnchorPos as setAnchorPosStored,
  type AnchorPos,
} from "@/src/lib/anchor";
import { BOAT_CRUISE_DEFAULT_KN, getBoatSettings } from "@/src/lib/boat-settings";
import {
  ROUTE_GUARD_HYSTERESIS,
  ROUTE_GUARD_REPEAT_MS,
  dynamicCorridorAt,
  getRouteGuardSettings,
  routeNavProgress,
  routePosition,
  type RouteNavState,
} from "@/src/lib/route-guard";import { storage } from "@/src/utils/storage";
import { logger } from "@/src/lib/logger";
import { checkFineTiles, downloadDalles, downloadSeamarkPack, getManifest, isLocalCovered, listDallesForPolygon, type DalleInfo, type OfflineManifest } from "@/src/lib/offline-dalles";
import { formatDM } from "@/src/lib/coords";
import { CoordsPopup } from "@/src/components/CoordsPopup";
import {
  useAdaptiveReportsPolling,
  formatLastRefresh,
} from "@/src/lib/adaptive-polling";
import NetInfo from "@react-native-community/netinfo";
import { useMapUnit } from "@/src/lib/map-unit";
import { useConeState } from "@/src/lib/cone-state";
import { styles } from "@/src/screens/map/map-styles";

// 27/08/2026 (refactor map.tsx) — constantes, helpers purs et modals
// déplacés dans src/screens/map/ (déplacement PUR, zéro changement).
import {
  AUTO_SWITCH_SPEED_MS,
  AUTO_SWITCH_SUSTAIN_MS,
  CONE_ANGLE_DEFAULT,
  CONE_ANGLE_MAX,
  CONE_ANGLE_MIN,
  DEFAULT_CENTER,
  DISPLAY_RADIUS_KM,
} from "@/src/screens/map/map-constants";
import { nearestSegOnRoute, nearestWpIdx } from "@/src/screens/map/route-geometry";
import { AlertSettingsModal } from "@/src/screens/map/modals/AlertSettingsModal";
import { AnchorModal } from "@/src/screens/map/modals/AnchorModal";
import { BathyOpacityModal } from "@/src/screens/map/modals/BathyOpacityModal";
import { LongPressMenuModal } from "@/src/screens/map/modals/LongPressMenuModal";
import { RiskConfirmModal } from "@/src/screens/map/modals/RiskConfirmModal";
import { RouteChoiceModal } from "@/src/screens/map/modals/RouteChoiceModal";
import { RouteMenuModal } from "@/src/screens/map/modals/RouteMenuModal";
import { SaveRouteNameModal } from "@/src/screens/map/modals/SaveRouteNameModal";
import { SeamarkInfoModal } from "@/src/screens/map/modals/SeamarkInfoModal";
import { UnitPickerModal } from "@/src/screens/map/modals/UnitPickerModal";
// 26/08/2026 (fin du refactor map.tsx) — recherche, filtres, cône et barres
// (manuelle / édition / départ / placement) : déplacements PURS.
import { SearchByCodeModal } from "@/src/screens/map/modals/SearchByCodeModal";
import { MapFilterSheet } from "@/src/screens/map/modals/MapFilterSheet";
import { ConeConfigModal } from "@/src/screens/map/modals/ConeConfigModal";
import { ManualRouteBar, PickPlaceBar, RouteEditBar, RoutePickBar } from "@/src/screens/map/RouteBars";

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
    /** 26/07 — route enregistrée ouverte depuis le PROFIL. */
    saved_route_id?: string;
    saved_route_action?: string;
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
  // 19/07/2026 — PROTOTYPE bathymétrie SHOM (toggle persisté, OFF par défaut).
  const [bathyOn, setBathyOn] = useState(false);
  // 24/07/2026 — COMPAS DE MESURE (segment A→B, distance + relèvement).
  const [measureOn, setMeasureOn] = useState(false);
  // 24/07/2026 — ROUTE DOUTEUSE (tronçon rouge) : acceptation du risque.
  const [riskAccepted, setRiskAccepted] = useState(false);
  const [riskConfirmOpen, setRiskConfirmOpen] = useState(false);
  // 09/09/2026 (V1.6) — l'accusé de lecture « Ok, j'ai compris » est
  // SUPPRIMÉ : accès direct au bouton « Suivre cette route ».
  // 28/07 — unité de vitesse (partagée avec le compteur, persistée).
  const [speedUnit, setSpeedUnit] = useState<"kn" | "kmh">("kn");
  // 24/07/2026 — HAUTEUR D'EAU au point cliqué (clic court sur l'eau).
  // 24/07 soir (demande armateur) — ACTIVABLE/DÉSACTIVABLE via le bouton
  // goutte d'eau de la colonne droite (off par défaut).
  const [waterTapOn, setWaterTapOn] = useState(false);
  const [waterInfo, setWaterInfo] = useState<{
    lat: number; lng: number; loading: boolean; covered?: boolean;
    water?: boolean; depth_zh_m?: number; tide_m?: number;
    height_now_m?: number; error?: boolean;
  } | null>(null);
  const [bathyLoaded, setBathyLoaded] = useState(false);
  // 28/07 — numéro du DERNIER tap hauteur d'eau (les réponses périmées d'un
  // tap précédent sont ignorées : affichage « parfois lent, parfois rapide »).
  const waterReqRef = useRef(0);
  // 26/07 — pastille hauteur d'eau AU POINT cliqué : texte construit ici,
  // affiché par leaflet (__setWaterPoint). Fermeture auto 5 s.
  const waterPoint = useMemo(() => {
    if (!waterInfo) return null;
    if (waterInfo.loading) return { lat: waterInfo.lat, lng: waterInfo.lng, loading: true };
    const f = (v?: number) => v?.toFixed(1).replace(".", ",");
    const text = waterInfo.error
      ? "Hauteur d'eau indisponible — réessayez"
      : waterInfo.covered === false
        ? "Hors couverture cartographique"
        : waterInfo.water === false
          ? "Terre — pas de donnée de fond ici"
          : waterInfo.height_now_m != null
            ? waterInfo.height_now_m <= 0
              ? `À sec en ce moment — carte ${f(waterInfo.depth_zh_m)} m, marée ${f(waterInfo.tide_m)} m`
              : `Hauteur d'eau ${f(waterInfo.height_now_m)} m · carte ${f(waterInfo.depth_zh_m)} m + marée ${f(waterInfo.tide_m)} m`
            : `Fond carte ${f(waterInfo.depth_zh_m)} m (marée indisponible)`;
    return { lat: waterInfo.lat, lng: waterInfo.lng, text };
  }, [waterInfo]);
  useEffect(() => {
    if (!waterInfo || waterInfo.loading) return;
    const t = setTimeout(() => setWaterInfo(null), waterInfo.error ? 4000 : 5000);
    return () => clearTimeout(t);
  }, [waterInfo]);

  const isAdmin = !!user?.is_signalmar_admin;
  // 09/09/2026 (V1.6) — le popup clic-carte (coordonnées/hauteur/capture
  // support) est SUPPRIMÉ : un clic simple ne déclenche plus rien.
  // Opacité de la surcouche (retour armateur 19/07) : 0.3-1, défaut 0.7,
  // réglée via appui LONG sur le bouton goutte d'eau (popup chips).
  const [bathyOpacity, setBathyOpacity] = useState(0.7);
  const [bathyModalOpen, setBathyModalOpen] = useState(false);
  // N0 (20/07/2026) — menu appui long « Signaler ici / Naviguer ici » :
  // point tapé mémorisé le temps d'afficher le menu (null = fermé).
  const [longPressPoint, setLongPressPoint] = useState<{ lat: number; lng: number } | null>(null);
  // 26/07 (bug vidéo armateur) — doigt maintenu TROP longtemps : le relâché
  // arrivait sur le fond de la modale et la fermait aussitôt. On ignore tout
  // tap sur le fond pendant les 700 ms qui suivent l'ouverture.
  const longPressOpenedAtRef = useRef(0);
  // N1 (20/07/2026) — route sûre active (affichée sur la carte + RouteCard).
  const [route, setRoute] = useState<ComputedRoute | null>(null);
  const [routeBusy, setRouteBusy] = useState(false);
  // 21/07 — fenêtre route : plein / réduite (pill) / masquée. Fermer la
  // fenêtre NE SUPPRIME PLUS la route (règle armateur) ; suppression via
  // tap sur le tracé → menu.
  const [routeCardMode, setRouteCardMode] = useState<"full" | "min" | "hidden">("full");
  const [routeMenuOpen, setRouteMenuOpen] = useState(false);
  // 26/08/2026 (demande armateur) — tap sur une ZONE ROUGE du tracé : le
  // menu de la route s'ouvre AVEC un bandeau « faible hauteur d'eau ».
  const [routeMenuDanger, setRouteMenuDanger] = useState<RouteTapDanger | null>(null);
  // ── 02/08/2026 (demande armateur) — A/B TESTING DE MOTEURS ──────────────
  // Une route affichée peut être RECALCULÉE avec un autre moteur : les deux
  // tracés sont superposés sur la carte, les écarts surlignés, chaque tracé
  // étiqueté « moteur · ID ».
  const [enginePickerOpen, setEnginePickerOpen] = useState(false);
  const [compareBusy, setCompareBusy] = useState(false);
  const [compare, setCompare] = useState<{
    base: ComputedRoute;
    variant: ComputedRoute;
    diff: RouteDiff;
    engineName: string;
    engineId: string;
  } | null>(null);
  // Route enregistrée en cours de consultation (contexte du recalcul A/B).
  const [savedCtx, setSavedCtx] = useState<{ id: string; name: string } | null>(null);
  // ── 02/08/2026 (armateur) — 429 / coupure réseau pendant un calcul : le
  // DÉPART ET LA DESTINATION sont conservés ici pour un ré-essai en un tap.
  const [routeRetry, setRouteRetry] = useState<{
    dest: { lat: number; lng: number };
    from: { lat: number; lng: number };
    tide: number | null;
    reason: "429" | "net" | "stop";
  } | null>(null);
  // 20/07 — « Créer une route » : destination mémorisée pendant que
  // l'utilisateur place librement le DÉPART à la croix (auto-recentrage
  // suspendu). null = mode inactif.
  const [routePickDest, setRoutePickDest] = useState<{ lat: number; lng: number } | null>(null);
  // 22/07/2026 — « Créer une route » : choix AUTO / MANUELLE / enregistrées.
  const [routeChoicePt, setRouteChoicePt] = useState<{ lat: number; lng: number } | null>(null);
  // 22/07 — route MANUELLE en création : liste des étapes (null = inactif).
  const [manualPoints, setManualPoints] = useState<{ lat: number; lng: number }[] | null>(null);
  const [manualBusy, setManualBusy] = useState(false);
  // 10/09/2026 (V1.6 finale) — editBusy déclaré ICI (avant le chrono) : le
  // bouton STOP couvre TOUS les écrans de calcul (auto, manuelle, édition de
  // points, recalcul moteur A/B admin).
  const [editBusy, setEditBusy] = useState(false);
  // 22/07 — point de BLOCAGE (route impossible) : affiché en rouge pulsant,
  // la route existante n'est JAMAIS effacée (demande armateur).
  const [blocked, setBlocked] = useState<{ blocked_at: { lat: number; lng: number }; partial_waypoints?: { lat: number; lng: number }[]; message?: string } | null>(null);
  // 22/07 — enregistrement de la route (nom) + liste des routes enregistrées.
  const [saveNameOpen, setSaveNameOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [savingRoute, setSavingRoute] = useState(false);
  // 26/07 — la liste des routes enregistrées vit désormais dans le PROFIL.
  // 22/07 — fiche d'une balise tapée sur la carte.
  const [seamarkInfo, setSeamarkInfo] = useState<Seamark | null>(null);
  // 22/07 (GO armateur) — MARÉE intégrée au calcul de route : null = sans
  // (marée basse, sécuritaire), sinon décalage du départ en heures (0 = now).
  const [tideChoice, setTideChoice] = useState<number | null>(0);
  // 20/07 — machine d'état de l'alerte d'écart de route (hors corridor ?
  // dernière alerte ?). Réinitialisée à chaque nouvelle route.
  const routeGuardRef = useRef({ outside: false, lastAlertAt: 0 });
  // 26/07 (demande armateur) — bannière d'ÉCART DE ROUTE persistante
  // (remplace le toast) : coupable (mute), lien Réglages, ré-ouvrable via
  // une pastille si fermée.
  const [deviation, setDeviation] = useState<{ distM: number } | null>(null);
  // 29/07 (retour mer, choix armateur) — GPS dégradé : simple avertissement
  // « Précision GPS réduite », rien de bloquant. Hystérésis 35 m / 22 m pour
  // ne pas clignoter à la frontière ; setState uniquement au changement.
  const gpsPoorRef = useRef(false);
  const [gpsPoor, setGpsPoor] = useState(false);
  const noteGpsAccuracy = useCallback((acc: number | null | undefined) => {
    if (typeof acc !== "number" || acc <= 0) return;
    const poor = gpsPoorRef.current ? acc > 22 : acc > 35;
    if (poor !== gpsPoorRef.current) {
      gpsPoorRef.current = poor;
      setGpsPoor(poor);
    }
  }, []);
  const [deviationHidden, setDeviationHidden] = useState(false);
  const [deviationMuted, setDeviationMuted] = useState(false);
  const deviationMutedRef = useRef(false);
  // ── 23/07/2026 — SUIVI DE ROUTE (GO armateur) ─────────────────────────
  // navFollow = suivi actif ; navProgress = progression recalculée à chaque
  // tick GPS (dernier waypoint dépassé, distances, cap à suivre, projection
  // du bateau sur la route pour le grisage du tronçon parcouru).
  const [navFollow, setNavFollow] = useState(false);
  const [navProgress, setNavProgress] = useState<RouteNavState | null>(null);
  // Index de waypoint MONOTONE : un waypoint dépassé le RESTE (pas de
  // retour arrière si la projection GPS saute brièvement en arrière).
  const passedIdxRef = useRef(-1);
  const [cruiseKn, setCruiseKn] = useState(BOAT_CRUISE_DEFAULT_KN);
  // ── 23/07/2026 — ALARME DE MOUILLAGE (GO armateur) ────────────────────
  const [anchor, setAnchor] = useState<AnchorPos | null>(null);
  const [anchorRadiusM, setAnchorRadiusM] = useState(ANCHOR_RADIUS_DEFAULT_M);
  const [anchorModalOpen, setAnchorModalOpen] = useState(false);
  const [anchorAlarm, setAnchorAlarm] = useState(false);
  const anchorAlarmRef = useRef({ outside: false, lastAlertAt: 0, muted: false });
  // 26/07 (décision armateur) — contexte de la DERNIÈRE route auto calculée :
  // permet « Actualiser la route » (recalcul avec la marée de MAINTENANT).
  const routeCtxRef = useRef<{
    dest: { lat: number; lng: number };
    from: { lat: number; lng: number };
  } | null>(null);
  // 08/09/2026 (remise à plat armateur) — CHRONO visible pendant le calcul +
  // bouton « ARRÊTER LE CALCUL » (jeton d'annulation du polling).
  const routeCancelRef = useRef<{ cancelled: boolean } | null>(null);
  const [routeElapsedS, setRouteElapsedS] = useState(0);
  // 10/09/2026 (V1.6 finale, ordre armateur) — STOP + chrono sur TOUS les
  // écrans de calcul : route auto, manuelle, modification de points (User)
  // et recalcul avec un autre moteur (Admin).
  const anyBusy = routeBusy || manualBusy || editBusy || compareBusy;
  useEffect(() => {
    if (!anyBusy) return;
    setRouteElapsedS(0);
    const t0 = Date.now();
    const iv = setInterval(() => setRouteElapsedS(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(iv);
  }, [anyBusy]);
  // 08/09/2026 — tirant d'eau du bateau (affiché sur le bandeau « Route
  // conseillée »), rafraîchi à chaque calcul.
  const [boatDraftM, setBoatDraftM] = useState<number | null>(null);
  // 09/09/2026 (V1.6) — temps de calcul DÉFINITIF affiché sur le bandeau.
  const [routeComputeS, setRouteComputeS] = useState<number | null>(null);
  // ── 09/09/2026 (V1.6 armateur) — OUTIL « Cartes 📥 » : carré de 50 km de
  // rayon aux coins ajustables (dessiné côté Leaflet), puis téléchargement
  // du PACK complet de la zone (dalles bathy + balisage/mouillages/dangers)
  // stocké sur l'appareil, avec barre de progression en Mo.
  const [zoneCorners, setZoneCorners] = useState<{ lat: number; lng: number }[] | null>(null);
  const [offlineTiles, setOfflineTiles] = useState<{ tiles: DalleInfo[]; total_bytes: number } | null>(null);
  const [offlineBusy, setOfflineBusy] = useState(false);
  const [offlineProg, setOfflineProg] = useState<{ done: number; total: number } | null>(null);
  const offlineCancelRef = useRef<{ cancelled: boolean } | null>(null);
  // 09/09/2026 (V1.6) — pastille source de données : verte « LOCAL » si le
  // centre de la carte est couvert par une dalle stockée sur l'appareil.
  const [offlineManifest, setOfflineManifest] = useState<OfflineManifest>({});
  const [badgeCenter, setBadgeCenter] = useState<{ lat: number; lng: number } | null>(null);
  const badgeThrottleRef = useRef(0);
  useEffect(() => {
    void getManifest().then(setOfflineManifest);
  }, []);
  const dataIsLocal = useMemo(
    () => (badgeCenter ? isLocalCovered(offlineManifest, badgeCenter.lat, badgeCenter.lng) : false),
    [badgeCenter, offlineManifest],
  );
  const computeSafeRoute = useCallback(async (
    dest: { lat: number; lng: number },
    startOverride?: { lat: number; lng: number },
  ): Promise<ComputedRoute | null> => {
    const from = startOverride ?? userLocRef.current;
    if (!from) {
      showToast("error", "Position GPS inconnue — utilisez « Créer une route » pour choisir un départ.");
      return null;
    }
    setRouteBusy(true);
    setRouteRetry(null);
    const cancelTok = { cancelled: false };
    routeCancelRef.current = cancelTok;
    const tStart = Date.now();
    try {
      const bs = await getBoatSettings();
      setBoatDraftM(bs.draftM);
      const r = await api.computeRoute({
        start: { lat: from.lat, lng: from.lng },
        end: dest,
        draft_m: bs.draftM,
        depth_margin_m: bs.depthMarginM,
        // 23/07 (demande armateur) — marge latérale : AUTO par défaut (le
        // moteur adapte au chenal) ; en manuel, la valeur des réglages est
        // envoyée telle quelle.
        ...(bs.marginMode === "manual" ? { lateral_margin_m: bs.marginM } : {}),
        // 22/07 (GO armateur) — marée à l'heure de départ (null = marée basse).
        use_tide: tideChoice != null,
        ...(tideChoice != null && tideChoice > 0
          ? { departure_ts: Date.now() / 1000 + tideChoice * 3600 }
          : {}),
      }, cancelTok);
      setRoute(r);
      // 08/09/2026 (remise à plat armateur) — TEMPS DE CALCUL EFFECTIF dans
      // les logs de l'appareil pour CHAQUE route générée (serveur + total).
      const elapsedS = +((Date.now() - tStart) / 1000).toFixed(1);
      setRouteComputeS(elapsedS);
      console.log(`[route] calcul terminé en ${elapsedS}s (moteur serveur : ${r.compute_s ?? "?"}s) — ${(r.distance_m / 1000).toFixed(1)} km`);
      logger.event("api", "route_computed", {
        route_id: r.route_id ?? null,
        engine: r.engine?.id ?? null,
        km: +(r.distance_m / 1000).toFixed(2),
        min_depth_m: r.min_depth_m,
        threshold_m: r.threshold_m,
        draft_m: bs.draftM,
        depth_margin_m: bs.depthMarginM,
        lateral_used_m: r.lateral_margin_used_m ?? null,
        tide_m: r.tide_m ?? null,
        risk: !!r.risk,
        warnings: (r.warnings || []).length,
        compute_s: r.compute_s ?? null,
        elapsed_s: elapsedS,
      });
      routeCtxRef.current = { dest, from: { lat: from.lat, lng: from.lng } };
      setRouteCardMode("full");
      setBlocked(null);
      // 26/07 (demande armateur) — le recentrage auto ne doit PAS reprendre
      // à la création d'une route : on consulte le tracé. Il reprend au
      // démarrage du suivi (startFollowForced).
      mapRef.current?.suspendFollow(true);
      showToast(
        "success",
        "Route conseillée calculée — " +
          `${(r.distance_m / 1000).toFixed(1)} km` +
          (r.tide
            ? ` (marée +${(r.tide.height_start_m ?? r.tide.height_min_m).toFixed(1)} m au moment du calcul)`
            : ""),
      );
      return r;
    } catch (e) {
      // 08/09/2026 — calcul ARRÊTÉ par l'utilisateur : on rend la main sans
      // bandeau d'erreur ni ré-essai (le départ/destination restent posés).
      if ((e as Error & { cancelled?: boolean }).cancelled) {
        console.log(`[route] calcul arrêté par l'utilisateur après ${((Date.now() - tStart) / 1000).toFixed(1)}s`);
        // 08/09/2026 — après l'ARRÊT : bandeau persistant — l'utilisateur
        // peut MODIFIER SES POINTS (replacer le départ) ou relancer ;
        // l'admin peut en plus CHANGER DE MOTEUR avant de relancer.
        setRouteRetry({
          dest, from: { lat: from.lat, lng: from.lng },
          tide: tideChoice, reason: "stop",
        });
        showToast("info", "Calcul arrêté.");
        return null;
      }
      // 22/07/2026 — route impossible : on N'EFFACE PAS la route existante,
      // on AFFICHE le point de blocage (rouge pulsant) + tronçon atteignable.
      const det = (e as Error & { detail?: RouteErrorDetail }).detail;
      if (det?.fallback_route && (det.fallback_route.waypoints?.length ?? 0) >= 2) {
        // 24/07/2026 (demande armateur) — ROUTE DOUTEUSE : pas de route sûre,
        // on livre quand même tronçon sûr + segment DIRECT (rouge) jusqu'à la
        // destination. Suivi possible UNIQUEMENT après acceptation du risque.
        const fb = det.fallback_route;
        setBlocked(null);
        setRiskAccepted(false);
        setRoute({
          waypoints: fb.waypoints,
          distance_m: fb.distance_m,
          min_depth_m: null,
          threshold_m: 0,
          depth_profile: [],
          warnings: [
            "Tronçon ROUGE non vérifié (direct jusqu'à destination) : fond insuffisant ou obstacle possible — acceptation du risque exigée avant de suivre.",
            ...(det.message ? [det.message] : []),
          ],
          disclaimer: "",
          mode: "auto",
          compromised_legs: [fb.compromised_from],
          risk: true,
        });
        setRouteCardMode("full");
        mapRef.current?.suspendFollow(true);
        showToast("error", "Aucune route sûre — route douteuse créée (tronçon rouge).");
      } else if (det?.blocked_at) {
        // 23/07 — message PERSISTANT (carte « blocage » avec bouton Mon
        // bateau) : le toast de 3,5 s était trop court pour être lu.
        setBlocked({
          blocked_at: det.blocked_at,
          partial_waypoints: det.partial_waypoints,
          message: det.message || "Passage impossible avec ces réglages.",
        });
      } else {
        // 02/08/2026 (armateur : « à chaque 429 le départ de la route saute »)
        // — panne RÉSEAU/ingress (429, 502-504, coupure) : ce n'est PAS un
        // problème de navigation. On conserve départ + destination et on
        // propose un ré-essai en un tap au lieu de tout perdre.
        const st = (e as Error & { status?: number }).status;
        const transient = st == null || st === 429 || (st >= 500 && st <= 504);
        logger.error("api", "route_failed", {
          status: st ?? null,
          transient,
          message: (e as Error).message,
        });
        if (transient) {
          setRouteRetry({
            dest, from: { lat: from.lat, lng: from.lng },
            tide: tideChoice, reason: st === 429 ? "429" : "net",
          });
          showToast(
            "error",
            "Réseau saturé — calcul interrompu. Départ conservé : appuyez sur « Réessayer ».",
          );
        } else {
          showToast("error", (e as Error).message || "Calcul de route impossible.");
        }
      }
      return null;
    } finally {
      setRouteBusy(false);
    }
  }, [tideChoice]);
  // 22/07/2026 — ROUTE MANUELLE : « Créer cette route » → distance + profil
  // de profondeur calculés par le backend sur les étapes de l'utilisateur.
  const createManualRoute = useCallback(async () => {
    const pts = manualPoints;
    if (!pts || pts.length < 2) return;
    setManualBusy(true);
    const cancelTok = { cancelled: false };
    routeCancelRef.current = cancelTok;
    try {
      const bs = await getBoatSettings();
      setBoatDraftM(bs.draftM);
      const r = await api.manualRoute({
        waypoints: pts,
        draft_m: bs.draftM,
        depth_margin_m: bs.depthMarginM,
        // 27/07 (vidéo 15h45) — marée aussi sur les routes manuelles : plus
        // de « zones rouges » au ZH quand il y a largement assez d'eau.
        use_tide: tideChoice != null,
        ...(tideChoice != null && tideChoice > 0
          ? { departure_ts: Date.now() / 1000 + tideChoice * 3600 }
          : {}),
      }, cancelTok);
      // 24/07 — risk posé aussi côté client (défense en profondeur : le
      // suivi doit TOUJOURS passer par l'acceptation du risque si rouge).
      setRoute({ ...r, risk: r.risk || !!r.compromised_legs?.length });
      setRouteCardMode("full");
      setManualPoints(null);
      setBlocked(null);
      setRiskAccepted(false);
      // 26/07 — pas de reprise du recentrage auto à la création.
      mapRef.current?.suspendFollow(true);
      // 24/07/2026 (demande armateur) — plus de popup d'enregistrement à la
      // création : on propose seulement de SUIVRE (bouton de la fiche).
      // L'enregistrement reste accessible en tapant le tracé.
      if (r.compromised_legs?.length) {
        showToast("error", "Route créée avec tronçon(s) ROUGE(S) — risque à accepter avant de la suivre.");
      } else {
        showToast("success", "Route créée — « Suivre cette route » pour démarrer.");
      }
    } catch (e) {
      if ((e as { cancelled?: boolean }).cancelled) showToast("info", "Calcul arrêté.");
      else showToast("error", (e as Error).message || "Création de la route impossible.");
    } finally {
      setManualBusy(false);
    }
  }, [manualPoints, tideChoice]);
  // ── 26/07 (demande armateur) — ÉDITION DE ROUTE PAR WAYPOINTS : appui
  // long SUR le tracé → waypoint draggable inséré ; tap À CÔTÉ → validation
  // backend (même mécanique d'alerte que la route auto dangereuse).
  const [editPoints, setEditPoints] = useState<{ lat: number; lng: number }[] | null>(null);
  // 11/08 (règle armateur) — UN SEUL waypoint éditable : le plus proche de
  // la zone touchée. Une fois déplacé → « Recalculer la route » (calcul
  // complet re-contrôlé par le moteur). Ajustement fin, carte lisible.
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [editMoved, setEditMoved] = useState(false);
  const closeEdit = useCallback(() => {
    setEditPoints(null);
    setEditIdx(null);
    setEditMoved(false);
  }, []);
  const commitEdit = useCallback(async () => {
    const pts = editPoints;
    if (!pts || pts.length < 2 || editBusy) return;
    setEditBusy(true);
    const cancelTok = { cancelled: false };
    routeCancelRef.current = cancelTok;
    try {
      const bs = await getBoatSettings();
      const r = await api.manualRoute({
        waypoints: pts,
        draft_m: bs.draftM,
        depth_margin_m: bs.depthMarginM,
        // 27/07 — l'édition d'une route est contrôlée à la marée ACTUELLE
        // (H+30 min) comme la route auto qu'elle modifie.
        use_tide: true,
        // 11/08 — recalcul par LE MOTEUR de la route affichée (test A/B).
        ...(route?.engine_id ? { engine_id: route.engine_id } : {}),
      }, cancelTok);
      setRoute({ ...r, mode: "manual", risk: r.risk || !!r.compromised_legs?.length });
      setRouteCardMode("full");
      setRiskAccepted(false);
      closeEdit();
      mapRef.current?.suspendFollow(true);
      if (r.compromised_legs?.length) {
        showToast("error", "Route modifiée — tronçon(s) ROUGE(S), risque à accepter avant de la suivre.");
      } else {
        showToast("success", "Modification de la route enregistrée.");
      }
    } catch (e) {
      if ((e as { cancelled?: boolean }).cancelled) showToast("info", "Calcul arrêté.");
      else showToast("error", (e as Error).message || "Validation de la modification impossible.");
    } finally {
      setEditBusy(false);
    }
  }, [editPoints, editBusy, route?.engine_id, closeEdit]);
  const loadSavedRoute = useCallback(async (sr: SavedRoute) => {
    setRouteBusy(true);
    const cancelTok = { cancelled: false };
    routeCancelRef.current = cancelTok;
    try {
      const bs = await getBoatSettings();
      setBoatDraftM(bs.draftM);
      const r = await api.manualRoute({
        waypoints: sr.waypoints,
        draft_m: bs.draftM,
        depth_margin_m: bs.depthMarginM,
        // 27/07 — consultation d'une route enregistrée : contrôlée aux
        // conditions de marée ACTUELLES.
        use_tide: true,
        // 02/08/2026 — la route est re-contrôlée par LE MOTEUR QUI L'A
        // PRODUITE (référence du test A/B) quand il est encore disponible.
        ...(sr.engine_id ? { engine_id: sr.engine_id } : {}),
      }, cancelTok);
      setRoute({ ...r, mode: sr.mode });
      setRouteCardMode("full");
      setBlocked(null);
      // 26/07 — consultation d'une route enregistrée : pas de recentrage auto.
      mapRef.current?.suspendFollow(true);
      showToast("success", `Route « ${sr.name} » affichée.`);
      return true;
    } catch (e) {
      if ((e as { cancelled?: boolean }).cancelled) showToast("info", "Calcul arrêté.");
      else showToast("error", (e as Error).message || "Affichage de la route impossible.");
      return false;
    } finally {
      setRouteBusy(false);
    }
  }, []);
  // ── 26/07 (demande armateur) — ROUTE OUVERTE DEPUIS LE PROFIL : la carte
  // affiche la route (+ bouton retour), et démarre le suivi si demandé.
  const [fromProfile, setFromProfile] = useState(false);
  const pendingFollowRef = useRef(false);
  const savedRouteHandledRef = useRef<string | null>(null);
  useEffect(() => {
    const id = shiftParams.saved_route_id;
    if (!id || savedRouteHandledRef.current === id) return;
    savedRouteHandledRef.current = id;
    const action = shiftParams.saved_route_action;
    (async () => {
      try {
        const r = await api.savedRoutes();
        const sr = r.routes.find((x) => x.id === id);
        if (!sr) {
          showToast("error", "Route introuvable.");
          return;
        }
        setFromProfile(true);
        setSavedCtx({ id: sr.id, name: sr.name });
        const ok = await loadSavedRoute(sr);
        if (ok && action === "follow") pendingFollowRef.current = true;
      } catch (e) {
        showToast("error", (e as Error).message || "Chargement de la route impossible.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shiftParams.saved_route_id, shiftParams.saved_route_action]);
  const submitSaveRoute = useCallback(async () => {
    const name = saveName.trim();
    const r = route;
    if (!r || !name) return;
    setSavingRoute(true);
    try {
      // 01/08/2026 — on relit les réglages actuels pour tagger la route
      // enregistrée avec ses paramètres d'entrée (utiles pour recalculer
      // plus tard avec un autre moteur).
      const bs = await getBoatSettings().catch(() => null);
      await api.saveRoute({
        name,
        mode: r.mode === "manual" ? "manual" : "auto",
        waypoints: r.waypoints,
        distance_m: r.distance_m,
        // Traçabilité multi-moteurs : la route enregistrée conserve le
        // moteur qui l'a produite + les paramètres d'entrée.
        engine_id: r.engine?.id ?? null,
        engine_name: r.engine?.name ?? null,
        algo_id: r.engine?.algo ?? null,
        draft_m: bs?.draftM,
        depth_margin_m: bs?.depthMarginM,
        lateral_margin_m: bs?.marginMode === "manual" ? bs.marginM : undefined,
        source_route_id: r.route_id ?? null,
        // 02/08/2026 — points DEMANDÉS (recalcul A/B fidèle avec un autre
        // moteur : les waypoints du tracé sont des nœuds de grille).
        start: (r.mode !== "manual" ? routeCtxRef.current?.from : null)
          ?? { lat: r.waypoints[0].lat, lng: r.waypoints[0].lng },
        end: (r.mode !== "manual" ? routeCtxRef.current?.dest : null) ?? {
          lat: r.waypoints[r.waypoints.length - 1].lat,
          lng: r.waypoints[r.waypoints.length - 1].lng,
        },
      });
      setSaveNameOpen(false);
      setSaveName("");
      showToast("success", `Route « ${name} » enregistrée.`);
    } catch (e) {
      showToast("error", (e as Error).message || "Enregistrement impossible.");
    } finally {
      setSavingRoute(false);
    }
  }, [saveName, route]);
  // ── 02/08/2026 (demande armateur) — RECALCUL A/B AVEC UN AUTRE MOTEUR ───
  // La route affichée sert de RÉFÉRENCE ; le moteur choisi produit la
  // VARIANTE. Les deux tracés restent affichés (écarts surlignés) jusqu'à ce
  // que l'armateur adopte la variante ou ferme la comparaison.
  const runEngineCompare = useCallback(async (engine: { id: string; name: string }) => {
    const base = route;
    if (!base || base.waypoints.length < 2) return;
    setCompareBusy(true);
    const cancelTok = { cancelled: false };
    routeCancelRef.current = cancelTok;
    try {
      let variant: ComputedRoute;
      if (savedCtx) {
        const res = await api.recomputeSavedRoute(savedCtx.id, [engine.id], cancelTok);
        const got = res.results[engine.id] as ComputedRoute & { error?: string };
        if (!got || got.error || !got.waypoints?.length) {
          throw new Error(got?.error || "Ce moteur n'a pas pu recalculer cette route.");
        }
        variant = got;
      } else {
        const bs = await getBoatSettings().catch(() => null);
        const draft = bs?.draftM ?? 1.5;
        const marginM = bs?.depthMarginM ?? 0.5;
        if (base.mode === "manual") {
          variant = await api.manualRoute({
            waypoints: base.waypoints.map((w) => ({ lat: w.lat, lng: w.lng })),
            draft_m: draft, depth_margin_m: marginM, use_tide: false,
            engine_id: engine.id,
          }, cancelTok);
        } else {
          const ctx = routeCtxRef.current;
          const wps = base.waypoints;
          variant = await api.computeRoute({
            start: ctx?.from ?? { lat: wps[0].lat, lng: wps[0].lng },
            end: ctx?.dest ?? { lat: wps[wps.length - 1].lat, lng: wps[wps.length - 1].lng },
            draft_m: draft, depth_margin_m: marginM,
            ...(bs?.marginMode === "manual" ? { lateral_margin_m: bs.marginM } : {}),
            use_tide: false,
            engine_id: engine.id,
          }, cancelTok);
        }
      }
      const diff = compareRoutes(base.waypoints, variant.waypoints, 25);
      setCompare({
        base, variant, diff,
        engineName: variant.engine?.name ?? engine.name,
        engineId: variant.engine?.id ?? engine.id,
      });
      setEnginePickerOpen(false);
      setRouteCardMode("hidden");
      mapRef.current?.suspendFollow(true);
      showToast(
        diff.identical ? "info" : "success",
        diff.identical
          ? `${engine.name} produit exactement le même tracé.`
          : `${diffCount(diff)} écart(s) — variante ${(variant.distance_m / 1000).toFixed(1)} km (écart maxi ${Math.round(diff.maxDevM)} m).`,
      );
    } catch (e) {
      if ((e as { cancelled?: boolean }).cancelled) showToast("info", "Calcul arrêté.");
      else showToast("error", (e as Error).message || "Recalcul impossible avec ce moteur.");
    } finally {
      setCompareBusy(false);
    }
  }, [route, savedCtx]);
  useEffect(() => {
    routeGuardRef.current = { outside: false, lastAlertAt: 0 };
    // 23/07 — nouvelle route (ou suppression) → le suivi repart de zéro.
    passedIdxRef.current = -1;
    setNavProgress(null);
    // 26/07 — reset bannière d'écart.
    setDeviation(null);
    setDeviationHidden(false);
    setDeviationMuted(false);
    deviationMutedRef.current = false;
    // 02/08/2026 — toute nouvelle route (ou suppression) ferme la
    // comparaison A/B de moteurs en cours.
    setCompare(null);
    if (!route) {
      setNavFollow(false);
      setSavedCtx(null);
    }
  }, [route]);
  // 02/08/2026 — payload de comparaison A/B poussé à la carte (variante +
  // portions divergentes + étiquettes « moteur · ID »).
  const routeComparePayload = useMemo(() => {
    if (!compare) return null;
    const b = compare.base;
    const baseLabel = b.engine
      ? `${b.engine.name} · ${b.engine.id}`
      : "Route de référence";
    return {
      key: `${b.route_id ?? "base"}|${compare.variant.route_id ?? compare.engineId}`,
      base: {
        waypoints: b.waypoints.map((w) => ({ lat: w.lat, lng: w.lng })),
        label: baseLabel, color: BASE_COLOR, anchor: compare.diff.anchorBase,
      },
      variant: {
        waypoints: compare.variant.waypoints.map((w) => ({ lat: w.lat, lng: w.lng })),
        label: `${compare.engineName} · ${compare.engineId}`,
        color: VARIANT_COLOR, anchor: compare.diff.anchorVariant,
      },
      diff_base: compare.diff.diffBase,
      diff_variant: compare.diff.diffVariant,
    };
  }, [compare]);
  // ── 23/07/2026 — SUIVI DE ROUTE : démarrage / arrêt ────────────────────
  const startFollowForced = useCallback(async () => {
    passedIdxRef.current = -1;
    setNavProgress(null);
    setNavFollow(true);
    setRouteCardMode("hidden");
    // 25/07 (demande armateur) — RECENTRAGE IMMÉDIAT sur le bateau avec un
    // zoom adapté à la route suivie (avant : on restait au zoom courant,
    // souvent bien trop éloigné pour lire la navigation).
    const loc = userLocRef.current;
    if (loc && route?.waypoints?.length) {
      // Distance au waypoint le plus proche → échelle utile : on veut voir
      // le bateau ET le prochain objectif confortablement.
      const mPerDegLat = 111_320;
      const mPerDegLng = 111_320 * Math.cos((loc.lat * Math.PI) / 180);
      let dMin = Infinity;
      for (const w of route.waypoints) {
        const d = Math.hypot((w.lat - loc.lat) * mPerDegLat, (w.lng - loc.lng) * mPerDegLng);
        if (d < dMin) dMin = d;
      }
      const z = dMin <= 600 ? 16 : dMin <= 1500 ? 15 : dMin <= 3500 ? 14 : dMin <= 8000 ? 13 : 12;
      mapRef.current?.suspendFollow(false); // la caméra reprend le bateau
      mapRef.current?.flyTo(loc.lat, loc.lng, z);
    }
    try {
      const bs = await getBoatSettings();
      setCruiseKn(bs.cruiseKn);
    } catch { /* défaut conservé */ }
    showToast("success", "Suivi de route activé — cap et ETA en haut de l'écran.");
  }, [route]);
  const startFollow = useCallback(async () => {
    // 24/07 (demande armateur) — route douteuse (tronçon rouge) : acceptation
    // EXPLICITE du risque obligatoire avant de pouvoir la suivre.
    if (route?.risk && !riskAccepted) {
      setRiskConfirmOpen(true);
      return;
    }
    await startFollowForced();
  }, [route, riskAccepted, startFollowForced]);
  // 26/07 — « Suivre cette route » depuis le PROFIL : le suivi démarre dès
  // que la route chargée est affichée (gating risque/marge conservé).
  useEffect(() => {
    if (route && pendingFollowRef.current) {
      pendingFollowRef.current = false;
      void startFollow();
    }
  }, [route, startFollow]);
  const stopFollow = useCallback(() => {
    // 28/07 — chemin durci (gel signalé le 28/07 au tap « stop ») : chaque
    // remise à zéro est indépendante, un échec n'en bloque pas une autre.
    try { setNavFollow(false); } catch { /* noop */ }
    try { setNavProgress(null); } catch { /* noop */ }
    passedIdxRef.current = -1;
    // 26/07 — fin de suivi → la bannière d'écart disparaît.
    try {
      setDeviation(null);
      setDeviationHidden(false);
      setDeviationMuted(false);
    } catch { /* noop */ }
    deviationMutedRef.current = false;
    // 29/07 (« Oui, tout s'arrête », retour mer) — l'alarme d'écart est
    // coupée NET à l'arrêt : garde-fou remis à zéro + son stoppé s'il joue.
    routeGuardRef.current = { outside: false, lastAlertAt: 0 };
    try { stopRouteDeviationSound(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
  }, []);
  // 28/07 — unité de vitesse persistée (partagée avec le compteur agrandi).
  useEffect(() => {
    storage.getItem<"kn" | "kmh">("sm.speedo.unit", "kn")
      .then((u) => setSpeedUnit(u === "kmh" ? "kmh" : "kn"))
      .catch(() => {});
  }, []);
  const toggleSpeedUnit = useCallback(() => {
    setSpeedUnit((prev) => {
      const next = prev === "kn" ? "kmh" : "kn";
      storage.setItem("sm.speedo.unit", next).catch(() => {});
      return next;
    });
  }, []);
  // Progression recalculée à chaque tick GPS pendant le suivi.
  useEffect(() => {
    if (!navFollow || !route || !userLoc) return;
    const p = routeNavProgress(userLoc, route.waypoints);
    if (!p) return;
    // 23/07 (retour armateur) — un waypoint n'est FRANCHI (grisé) que si le
    // bateau est passé à moins de ~100 m LATÉRALEMENT de la route. Loin du
    // couloir, la progression est gelée (plus de points grisés « à distance »).
    const idx = p.offRouteM <= 100
      ? Math.max(passedIdxRef.current, p.passedIdx)
      : passedIdxRef.current;
    passedIdxRef.current = idx;
    setNavProgress({ ...p, passedIdx: idx });
    // Arrivée (< 25 m de la destination) → fin de suivi automatique.
    if (p.distToEndM < 25) {
      setNavFollow(false);
      showToast("success", "Vous êtes arrivé à destination 🏁");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userLoc, navFollow, route]);
  // ── 23/07/2026 — ALARME DE MOUILLAGE : pose / levée + surveillance ─────
  const dropAnchor = useCallback(async () => {
    const loc = userLocRef.current;
    if (!loc) {
      showToast("error", "Position GPS inconnue — impossible de poser l'ancre.");
      return;
    }
    const pos: AnchorPos = { lat: loc.lat, lng: loc.lng, since: Date.now() };
    anchorAlarmRef.current = { outside: false, lastAlertAt: 0, muted: false };
    setAnchor(pos);
    setAnchorAlarm(false);
    setAnchorModalOpen(false);
    setAnchorPosStored(pos).catch(() => {});
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    showToast("success", `Ancre posée — rayon de garde ${anchorRadiusM} m.`);
  }, [anchorRadiusM]);
  const liftAnchor = useCallback(() => {
    anchorAlarmRef.current = { outside: false, lastAlertAt: 0, muted: false };
    setAnchor(null);
    setAnchorAlarm(false);
    setAnchorModalOpen(false);
    try { stopAnchorAlarmSound(); } catch { /* noop */ }
    setAnchorPosStored(null).catch(() => {});
    showToast("info", "Ancre levée — surveillance arrêtée.");
  }, []);
  // Ancre + rayon PERSISTÉS (mouillage de nuit : survit au redémarrage).
  useEffect(() => {
    (async () => {
      try {
        const [pos, r] = await Promise.all([getAnchorPos(), getAnchorRadiusM()]);
        setAnchorRadiusM(r);
        if (pos) setAnchor(pos);
      } catch { /* défauts */ }
    })();
  }, []);
  // Distance bateau ↔ ancre (m) — approximation plane, suffisante ≤ 1 km.
  const anchorDriftM = (() => {
    if (!anchor || !userLoc) return null;
    const mLng = 111_320 * Math.cos((anchor.lat * Math.PI) / 180);
    return Math.hypot((userLoc.lng - anchor.lng) * mLng, (userLoc.lat - anchor.lat) * 110_574);
  })();
  // 23/07 (bug « scintillement ») — payloads carte MÉMOÏSÉS : sans useMemo,
  // un nouvel objet à CHAQUE render déclenchait une réinjection JS (redraw
  // Leaflet) permanente dans la WebView → clignotements sur tablette.
  const routeProgressPayload = useMemo(
    () =>
      navFollow && navProgress
        ? { passedIdx: navProgress.passedIdx, lat: navProgress.projLat, lng: navProgress.projLng }
        : null,
    [navFollow, navProgress],
  );
  // 28/07 (demande armateur) — MODE PLEIN ÉCRAN de navigation : le tableau
  // de bord REMPLACE les icônes du haut (refresh, vitesse, filtres, cloche).
  const navActive = navFollow && navProgress != null && route != null;
  const anchorPayload = useMemo(
    () => (anchor ? { lat: anchor.lat, lng: anchor.lng, radiusM: anchorRadiusM, alarm: anchorAlarm } : null),
    [anchor, anchorRadiusM, anchorAlarm],
  );
  // Surveillance : hors du rayon → son dédié (anchor_alarm) + vibration,
  // répétés toutes les 15 s tant qu'on reste dehors (sauf « Couper le
  // son »). Retour < 80 % du rayon → réarmement automatique.
  useEffect(() => {
    if (!anchor || anchorDriftM == null) return;
    const st = anchorAlarmRef.current;
    const now = Date.now();
    if (anchorDriftM > anchorRadiusM) {
      setAnchorAlarm(true);
      if (!st.muted && (!st.outside || now - st.lastAlertAt >= 15_000)) {
        st.lastAlertAt = now;
        playAnchorAlarmSound();
        vibrateAlert();
      }
      st.outside = true;
    } else if (st.outside && anchorDriftM < anchorRadiusM * 0.8) {
      st.outside = false;
      st.muted = false;
      setAnchorAlarm(false);
      try { stopAnchorAlarmSound(); } catch { /* noop */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userLoc, anchor, anchorRadiusM]);
  // 20/07 — ALERTE D'ÉCART DE ROUTE (GO armateur) : à chaque tick GPS, si une
  // route est active et l'option activée, on mesure la distance au corridor.
  // Sortie (> seuil) → vibration + son dédié (fichier à venir) + toast,
  // rappel toutes les 30 s dehors ; retour < 80 % du seuil → réarmement.
  // Uniquement bateau en mouvement (≥ 0,8 m/s) pour éviter les faux positifs
  // à l'arrêt/en dérive GPS.
  useEffect(() => {
    // 23/07/2026 (demande armateur) — l'alerte d'écart ne se déclenche QU'EN
    // mode « Suivre cette route » : en planification (route calculée depuis
    // la maison, position à des km du corridor), le bandeau rouge était
    // permanent et sans objet.
    if (!navFollow) return;
    if (!route || !userLoc) return;
    if (userSpeed != null && userSpeed < 0.8) return;
    let cancelled = false;
    (async () => {
      const s = await getRouteGuardSettings();
      if (cancelled || !s.on) return;
      // 23/07 — corridor DYNAMIQUE (largeur par segment calculée par le
      // moteur de route, resserrée près des dangers) ou seuil MANUEL fixe,
      // selon le réglage utilisateur (Réglages → Navigation & routes).
      const rp = routePosition(userLoc, route.waypoints);
      if (!rp) return;
      const d = rp.distM;
      const thresholdM = s.mode === "dynamic"
        ? dynamicCorridorAt(rp.segIdx, route.corridor_m)
        : s.thresholdM;
      const st = routeGuardRef.current;
      const now = Date.now();
      if (d > thresholdM) {
        // 26/07 — bannière persistante (distance rafraîchie à chaque tick).
        setDeviation({ distM: Math.round(d) });
        if (!st.outside || now - st.lastAlertAt >= ROUTE_GUARD_REPEAT_MS) {
          st.outside = true;
          st.lastAlertAt = now;
          // 26/07 — « Couper l'alerte » : plus de son/vibration tant qu'on
          // n'est pas revenu sur la route (la bannière reste affichée).
          if (!deviationMutedRef.current) {
            vibrateAlert();
            playRouteDeviationSound();
          }
        }
      } else if (st.outside && d < thresholdM * ROUTE_GUARD_HYSTERESIS) {
        st.outside = false;
        setDeviation(null);
        setDeviationHidden(false);
        setDeviationMuted(false);
        deviationMutedRef.current = false;
        showToast("success", "Retour sur la route.");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userLoc, route, navFollow]);
  useEffect(() => {
    (async () => {
      try {
        const saved = await storage.getItem<boolean>("sm.map.bathy", false);
        if (saved === true) setBathyOn(true);
        const op = await storage.getItem<number>("sm.map.bathy_opacity", 0.7);
        if (typeof op === "number" && op >= 0.3 && op <= 1) setBathyOpacity(op);
      } catch { /* keep default */ }
      finally { setBathyLoaded(true); }
    })();
  }, []);
  useEffect(() => {
    if (!bathyLoaded) return;
    storage.setItem("sm.map.bathy", bathyOn).catch(() => {});
    storage.setItem("sm.map.bathy_opacity", bathyOpacity).catch(() => {});
  }, [bathyOn, bathyOpacity, bathyLoaded]);
  // Latest-speed ref used inside the heading callback (avoids stale closures).
  const speedRef = useRef<number | null>(null);
  // Refs miroirs (position + rayon) lus par fetchReports sans figurer dans
  // ses dépendances — voir la note anti-boucle dans fetchReports.
  const userLocRef = useRef<{ lat: number; lng: number } | null>(null);
  const radiusRef = useRef<number>(200);
  // 14/08/2026 (audit QA FND-011) — centre COURANT de la carte (événement
  // move de la WebView) : sert de repli de géofiltrage quand le GPS est
  // refusé/absent (web) pour ne plus charger TOUTE la base de signalements.
  const mapCenterRef = useRef<{ lat: number; lng: number } | null>(null);
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
  // 02/08/2026 — miroir des signalements affichés : permet de les CONSERVER
  // quand l'ingress renvoie un 429 (au lieu de basculer « hors-ligne »).
  const reportsRef = useRef<ReportItem[]>([]);

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
    // 14/08 (audit QA FND-011) — SANS GPS (web, permission refusée), le
    // géofiltre utilise le CENTRE COURANT de la carte : plus jamais toute
    // la base dessinée sur n'importe quel viewport.
    const geo = loc ?? mapCenterRef.current ?? DEFAULT_CENTER;
    const userRadius = Math.max(1, Math.min(1000, radiusRef.current ?? 200));
    try {
      const list = await api.listReports({
        types,
        lat: geo.lat,
        lng: geo.lng,
        radius_km: userRadius,
      });
      setReports(list);
      setOffline(false);
      logger.event("api", "listReports OK", { count: list.length, ms: Date.now() - t0, types });
      await saveReportsCache(list);
      return list;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const st = (e as Error & { status?: number }).status;
      // 02/08/2026 (armateur) — un 429 de l'ingress (rafale de requêtes) N'EST
      // PAS une perte de réseau : basculer « hors-ligne » + toast pendant
      // chaque calcul de route côtier était très pénible et faux. On garde
      // l'affichage en cours, on note l'incident et on retentera au prochain
      // cycle de polling.
      if (st === 429) {
        logger.error("api", "listReports 429 (ingress) → conservé", {
          error: msg, ms: Date.now() - t0, types,
        });
        return reportsRef.current;
      }
      const cached = await loadReportsCache(12);
      const filtered = sel.size === 0
        ? cached
        : cached.filter((r) => sel.has(r.type as ReportTypeId));
      setReports(filtered);
      setOffline(true);
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
    reportsRef.current = reports;
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
          noteGpsAccuracy(p.coords.accuracy);
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
            noteGpsAccuracy(p.coords.accuracy);
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
    try { stopAnchorAlarmSound(); } catch { /* noop */ }
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
      // 23/07 — le rayon de garde du mouillage a pu être modifié dans les
      // Réglages (Alarme de mouillage) : on le relit au retour sur la carte.
      getAnchorRadiusM().then(setAnchorRadiusM).catch(() => {});
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
    mapRef.current?.suspendFollow(false); // 20/07 — reprise de l'auto-recentrage
    // 29/07 (retour mer) — le recentrage GARDE le zoom actif de l'utilisateur
    // (avant : zoom 13 forcé ≈ échelle 3 km, perte du zoom de travail).
    mapRef.current?.flyTo(userLoc.lat, userLoc.lng);
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
  // 26/07 (demande armateur) — le cône est MASQUÉ quand le mode « hauteur
  // d'eau au toucher » est actif : il gênait la lecture du fond devant le
  // bateau (les alertes sonores du cône restent actives).
  // 29/07 (retour mer « pas de cône en navigation ») — le cône est actif en
  // mode Navigation ET pendant le SUIVI DE ROUTE (avant : seul navMode).
  const coneOn = (navMode || navFollow) && !waterTapOn;
  const coneDistanceKm = coneOn ? voiceSettings.zoneNavM / 1000 : null;
  const coneHalfAngleDeg = coneOn ? coneAngleDeg / 2 : null;

  // ── 17/07/2026 (v2 cône coloré) ──────────────────────────────────────
  // État couleur du cône : vert / orange / rouge (voir cone-state.ts).
  // NB : `useConeState` est INDÉPENDANT de sound-alert.ts (aucun couplage,
  // garantit zéro régression audio) mais utilise les mêmes règles
  // géométriques (isInCone) pour rester parfaitement synchro visuellement
  // avec le déclenchement sonore (rouge = son).
  const coneState = useConeState({
    userLoc,
    userHeading,
    coneHalfAngleDeg,
    zoneNavM: voiceSettings.zoneNavM,
    alertDistanceNavM: voiceSettings.alertDistanceNavM ?? voiceSettings.zoneNavM,
    reports: visibleReports,
    navMode: navMode || navFollow,
    enabled: !demoMode,
  });
  // Pousse l'état couleur vers l'iframe Leaflet à chaque changement.
  useEffect(() => {
    mapRef.current?.setConeState?.(coneState);
  }, [coneState]);
  // 17/07/2026 — force le rafraîchissement du WebView Leaflet quand une
  // alerte apparaît / disparaît, et quand une modale (réglages) se ferme :
  // corrige les cas de « carte noire » observés en terrain (Android).
  useEffect(() => {
    mapRef.current?.refreshMap?.();
  }, [activeAlert, alertSettingsOpen, unitPickerOpen]);

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
        radarPingRadiusM={!navMode && !navFollow && radarEnabled ? voiceSettings.zoneVigieM : null}
        reports={visibleReports}
        crosshair={picking || routePickDest != null}
        focusId={focusId}
        onMarkerPress={(id) => router.push(`/report/${id}`)}
        onMapMoved={(lat, lng) => {
          mapCenterRef.current = { lat, lng };
          // 09/09/2026 (V1.6) — pastille LOCAL/SERVER : suivi du centre
          // (limité à 1 mise à jour/s pour ne pas re-rendre en continu).
          const now = Date.now();
          if (now - badgeThrottleRef.current > 1000) {
            badgeThrottleRef.current = now;
            setBadgeCenter({ lat, lng });
          }
          if (picking || routePickDest != null) setPickedPoint({ lat, lng });
        }}
        onZoneCorners={(corners) => setZoneCorners(corners)}
        onMapLongPress={(lat, lng) => {
          // 22/07/2026 — mode route MANUELLE : chaque appui long AJOUTE une étape.
          if (manualPoints != null) {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
            setManualPoints((prev) => (prev ? [...prev, { lat, lng }] : [{ lat, lng }]));
            return;
          }
          // 11/08 (règle armateur) — en édition, un appui long près du
          // tracé SÉLECTIONNE le waypoint le plus proche (un seul éditable).
          if (editPoints != null) {
            const near = nearestSegOnRoute(lat, lng, editPoints);
            if (near.distM < 150) {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
              setEditIdx(nearestWpIdx(lat, lng, editPoints));
            }
            return;
          }
          // 26/07 — appui long SUR une route affichée (auto ou « Naviguer
          // ici ») → ENTRE en édition. 11/08 (règle armateur) : seul le
          // waypoint LE PLUS PROCHE de la zone touchée devient éditable.
          if (route && !navFollow && route.waypoints.length >= 2) {
            const near = nearestSegOnRoute(lat, lng, route.waypoints);
            if (near.distM < 80) {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
              mapRef.current?.suspendFollow(true);
              const wps = route.waypoints.map((w) => ({ lat: w.lat, lng: w.lng }));
              const idx = nearestWpIdx(lat, lng, wps);
              setEditPoints(wps);
              setEditIdx(idx);
              setEditMoved(false);
              setRouteCardMode("hidden");
              showToast("info", `Waypoint ${idx + 1} sélectionné — déplacez-le, puis « Recalculer la route ».`);
              return;
            }
          }
          // N0 (20/07/2026) — l'appui long ouvre un MENU 2 choix :
          // « Signaler ici » (flux V1 inchangé — geofence + dev-bypass côté
          // serveur à la création) et « Naviguer ici » (préparation V2).
          if (shiftReportId || picking || routePickDest) return; // already in a picker flow
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
          // 20/07 — consultation libre : l'auto-recentrage est mis en PAUSE
          // dès l'appui long ; il ne reprendra qu'au tap sur le bouton de
          // recentrage (règle armateur).
          mapRef.current?.suspendFollow(true);
          longPressOpenedAtRef.current = Date.now();
          setLongPressPoint({ lat, lng });
        }}
        mapUnit={mapUnit}
        onRulerTap={() => setUnitPickerOpen(true)}
        bathymetry={bathyOn}
        bathymetryOpacity={bathyOpacity}
        route={route}
        routeCompare={routeComparePayload}
        netQuiet={anyBusy}
        onRouteTap={(danger) => {
          if (!editPoints) {
            setRouteMenuDanger(danger ?? null);
            setRouteMenuOpen(true);
          }
        }}
        manualPoints={manualPoints ?? editPoints}
        draftEditIndex={editPoints != null ? editIdx : null}
        onDraftMove={(index, lat, lng) => {
          // 22/07 — drag & drop d'un point (création manuelle OU édition).
          // 11/08 — en édition, seul le waypoint sélectionné est déplaçable ;
          // son déplacement active « Recalculer la route ».
          const apply = (prev: { lat: number; lng: number }[] | null) => {
            if (!prev || index < 0 || index >= prev.length) return prev;
            const next = [...prev];
            next[index] = { lat, lng };
            return next;
          };
          if (editPoints != null) {
            if (editIdx != null && index !== editIdx) return;
            setEditPoints(apply);
            setEditMoved(true);
          } else setManualPoints(apply);
        }}
        blocked={blocked}
        onSeamarkTap={(m) => setSeamarkInfo(m)}
        routeProgress={routeProgressPayload}
        // 29/07 (retour mer) — ligne VERTE « cap à suivre » RETIRÉE : elle
        // doublonnait la projection de cap rouge (quasi superposées sur
        // l'eau). Infra conservée (targetBearingDeg par défaut null) si
        // l'armateur souhaite la réactiver.
        showHeadingLine={(navMode || navFollow) && !waterTapOn}
        anchor={anchorPayload}
        measure={measureOn}
        onMeasureSnap={() => {
          // Accroche magnétique (balise, route, bateau…) → retour haptique.
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
        }}
        onMapTap={(lat, lng) => {
          // 11/08 (règle armateur) — en édition : le tap à côté ne valide
          // plus (validation UNIQUEMENT via « Recalculer la route »).
          if (editPoints) return;
          if (manualPoints) return;
          // 09/09/2026 (V1.6, NETTOYAGE CLIC armateur) — un clic simple sur
          // la carte ne déclenche PLUS RIEN (l'ancien mini-popup coordonnées/
          // hauteur/photo est supprimé). Seule la GOUTTE D'EAU (mesure
          // manuelle, bouton dédié) reste active.
          if (!waterTapOn) return;
          setWaterInfo({ lat, lng, loading: true });
          // 28/07 (vidéo 15h45 « hyper lente, parfois rapide ») — COURSE de
          // requêtes : une réponse LENTE d'un ancien tap pouvait écraser la
          // pastille d'un tap plus récent (affichage qui saute/retarde). On
          // numérote chaque tap et on ignore toute réponse périmée.
          const reqId = ++waterReqRef.current;
          // 26/07 (bug armateur « ça mouline puis disparaît sans donnée ») —
          // 1 nouvel essai automatique, puis message d'erreur VISIBLE.
          const attempt = (n: number) => {
            api.depthAt(lat, lng)
              .then((d) => {
                if (waterReqRef.current !== reqId) return;
                setWaterInfo({ lat, lng, loading: false, ...d });
              })
              .catch(() => {
                if (waterReqRef.current !== reqId) return;
                if (n < 1) setTimeout(() => attempt(n + 1), 800);
                else setWaterInfo({ lat, lng, loading: false, error: true });
              });
          };
          attempt(0);
        }}
        waterPoint={waterPoint}
        onWaterClose={() => {
          setWaterTapOn(false);
          setWaterInfo(null);
          showToast("info", "Hauteur d'eau au toucher désactivée.");
        }}
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
          {/* 24/07 soir (demande armateur) — REFRESH déplacé ici : petit
              bouton à côté des coordonnées (avant : colonne droite).
              28/07 — masqué en NAVIGATION (plein écran). */}
          {!navActive && (
          <TouchableOpacity
            style={styles.topRefreshBtn}
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
              <Ionicons name="refresh" size={15} color={theme.text} />
            )}
          </TouchableOpacity>
          )}
          {/* Compteur de vitesse — remonté dans la barre du haut (10/07).
              Tap → compteur AGRANDI (overlay bande « Verre »).
              28/07 — masqué en NAVIGATION (la vitesse LIVE est dans le
              tableau de bord, unité affichée selon le réglage partagé). */}
          {!navActive && (
          <TouchableOpacity
            style={styles.topSpeedPill}
            onPress={() => setSpeedoOpen(true)}
            activeOpacity={0.8}
            testID="map-speed-pill"
            accessibilityLabel="Agrandir le compteur de vitesse"
          >
            <Ionicons name="speedometer" size={13} color={theme.primary} />
            <Text style={styles.topSpeedText}>
              {(() => {
                const kmh = userSpeed != null && userSpeed * 3.6 >= 3 ? userSpeed * 3.6 : 0;
                return speedUnit === "kn" ? `${(kmh / 1.852).toFixed(1)} kn` : `${kmh.toFixed(1)} km/h`;
              })()}
            </Text>
          </TouchableOpacity>
          )}
          {!navActive && (
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
          )}
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
              notifications drawer. Hidden in demo mode (no user account).
              28/07 — masquée en NAVIGATION (plein écran). */}
          {user && !navActive && (
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

        {/* ── 28/07 (refonte armateur) — NAVIGATION PLEIN ÉCRAN : tableau de
            bord sur UNE ligne (cap, vitesse LIVE, WP, arrivée) qui remplace
            les icônes du haut, + bouton « Stopper la navigation ». Le CAP À
            SUIVRE est projeté sur la carte (ligne vert foncé). ── */}
        {navActive && navProgress && route ? (
          <RouteNavPanel
            progress={navProgress}
            headingDeg={userHeading}
            speedMps={userSpeed}
            cruiseKn={cruiseKn}
            unit={mapUnit}
            speedUnit={speedUnit}
            onToggleSpeedUnit={toggleSpeedUnit}
            nextIsEnd={navProgress.passedIdx >= route.waypoints.length - 2}
            onStop={stopFollow}
          />
        ) : null}

        {/* ── 23/07/2026 — ALARME DE MOUILLAGE : bannière de dérive. ── */}
        {anchorAlarm && anchor ? (
          <View style={styles.anchorAlarmCard} testID="anchor-alarm-banner">
            <View style={styles.anchorAlarmHead}>
              <MaterialCommunityIcons name="anchor" size={18} color="#FFD3D5" />
              <Text style={styles.anchorAlarmTitle}>ALARME DE MOUILLAGE</Text>
            </View>
            <Text style={styles.anchorAlarmTxt}>
              Le bateau a dérivé à {anchorDriftM != null ? Math.round(anchorDriftM) : "—"} m de
              l&apos;ancre (rayon de garde {anchorRadiusM} m). Vérifiez votre mouillage !
            </Text>
            <View style={styles.anchorAlarmBtnRow}>
              <TouchableOpacity
                style={[styles.anchorAlarmBtn, { backgroundColor: "rgba(255,255,255,0.14)" }]}
                onPress={() => {
                  anchorAlarmRef.current.muted = true;
                  try { stopAnchorAlarmSound(); } catch { /* noop */ }
                  try { stopAlertFeedback(); } catch { /* noop */ }
                }}
                testID="anchor-alarm-mute"
              >
                <Ionicons name="volume-mute" size={16} color="#FFECEC" />
                <Text style={[styles.anchorAlarmTxt, { fontWeight: "900" }]}>Couper le son</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.anchorAlarmBtn, { backgroundColor: "#E5383B" }]}
                onPress={liftAnchor}
                testID="anchor-alarm-lift"
              >
                <MaterialCommunityIcons name="anchor" size={16} color="#fff" />
                <Text style={[styles.anchorAlarmTxt, { color: "#fff", fontWeight: "900" }]}>
                  Lever l&apos;ancre
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : null}

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

      {/* ── 17/07/2026 — Bandeau one-shot « distance d'alerte NAV » ────────
          Affiché une seule fois (dismiss → navAlertDistanceIntroSeen=true).
          Aucun impact sonore : c'est purement pédagogique. ──────────────── */}
      {!voiceSettings.navAlertDistanceIntroSeen && !activeAlert && !proximityQuestion && (
        <View
          style={[styles.introBannerWrap, { top: insets.top + 58 }]}
          pointerEvents="box-none"
        >
          <View style={styles.introBanner} pointerEvents="auto">
            <Ionicons name="sparkles" size={16} color={theme.primary} style={{ marginTop: 2 }} />
            <View style={{ flex: 1 }}>
              <Text style={styles.introBannerTitle}>Cône coloré + distance d&apos;alerte</Text>
              <Text style={styles.introBannerBody}>
                Le cône de navigation devient <Text style={{ color: "#22C55E", fontWeight: "800" }}>vert</Text>
                {" · "}<Text style={{ color: "#F59E0B", fontWeight: "800" }}>orange</Text>
                {" · "}<Text style={{ color: "#EF4444", fontWeight: "800" }}>rouge</Text> selon la présence
                de signalements. La distance d&apos;alerte est réglable séparément dans Réglages —
                identique à la longueur du cône par défaut (aucun changement sur ton audio).
              </Text>
              <TouchableOpacity
                style={styles.introBannerBtn}
                onPress={() => { void updateVoiceSettings({ navAlertDistanceIntroSeen: true }); }}
                testID="intro-banner-dismiss"
              >
                <Text style={styles.introBannerBtnText}>OK, compris</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      )}

      {/* ── Popup unité d'échelle km/NM (tap sur une règle) — 16/07/2026 ── */}
      <UnitPickerModal
        visible={unitPickerOpen}
        mapUnit={mapUnit}
        onPick={(u) => { setMapUnit(u); setUnitPickerOpen(false); }}
        onClose={() => setUnitPickerOpen(false)}
      />

      {/* ── Popup bathymétrie SHOM (appui long sur la goutte d'eau) —
          réglage d'opacité de la surcouche (19/07/2026). ── */}
      <BathyOpacityModal
        visible={bathyModalOpen}
        opacity={bathyOpacity}
        onChangeOpacity={setBathyOpacity}
        onClose={() => setBathyModalOpen(false)}
      />

      {/* ── 23/07/2026 — ALARME DE MOUILLAGE (bouton ancre) : pose/levée +
          rayon de garde (aussi réglable dans Réglages → Alarme de mouillage). ── */}
      <AnchorModal
        visible={anchorModalOpen}
        anchor={anchor}
        anchorDriftM={anchorDriftM}
        radiusM={anchorRadiusM}
        onChangeRadius={setAnchorRadiusM}
        canDrop={!!userLoc}
        onDrop={() => void dropAnchor()}
        onLift={liftAnchor}
        onClose={() => setAnchorModalOpen(false)}
      />

      {/* ── Menu appui long (N0, 20/07/2026) — « Signaler ici » /
          « Naviguer ici » / « Créer une route ». ── */}
      <LongPressMenuModal
        point={longPressPoint}
        openedAt={() => longPressOpenedAtRef.current}
        onClose={() => setLongPressPoint(null)}
        onReport={(pt) => {
          setLongPressPoint(null);
          router.push({
            pathname: "/report/new",
            params: { lat: String(pt.lat), lng: String(pt.lng), src: "longpress" },
          });
        }}
        onNavigate={(pt) => {
          setLongPressPoint(null);
          void computeSafeRoute(pt);
        }}
        onCreateRoute={(pt) => {
          setLongPressPoint(null);
          setRouteChoicePt(pt);
        }}
      />

      {/* ── 09/09/2026 (V1.6 armateur) — BARRE « CARTES 📥 » : carré 50 km
          ajustable (coins déplaçables côté carte) → « Lancer le
          téléchargement » récupère TOUT le pack de la zone (dalles bathy +
          balisage + mouillages + dangers) sur l'appareil, avec barre de
          progression en Mo. ── */}
      {zoneCorners != null ? (
        <View style={styles.routeCardWrap} pointerEvents="box-none">
          <View style={styles.blockedCard} testID="offline-zone-bar">
            <View style={styles.blockedHead}>
              <Ionicons name="cloud-download" size={18} color="#48CAE4" />
              <Text style={styles.blockedTitle}>
                {offlineBusy && offlineProg
                  ? `Téléchargement ${offlineProg.done}/${offlineProg.total} · ${(offlineProg.done * 1.0).toFixed(0)}/${(offlineProg.total * 1.0).toFixed(0)} Mo`
                  : offlineTiles
                    ? `${offlineTiles.tiles.length} dalle(s) · ~${(offlineTiles.total_bytes / 1e6).toFixed(0)} Mo + balisage`
                    : "Cartes hors ligne — ajustez le carré"}
              </Text>
              <TouchableOpacity
                onPress={() => {
                  if (offlineCancelRef.current) offlineCancelRef.current.cancelled = true;
                  mapRef.current?.stopZonePicker();
                  setZoneCorners(null);
                  setOfflineTiles(null);
                  setOfflineBusy(false);
                  setOfflineProg(null);
                }}
                hitSlop={10}
                testID="offline-zone-close"
              >
                <Ionicons name="close" size={20} color={theme.textMute} />
              </TouchableOpacity>
            </View>
            {offlineBusy && offlineProg ? (
              <View style={styles.offlineProgTrack}>
                <View style={[styles.offlineProgFill, { width: `${Math.round((offlineProg.done / Math.max(1, offlineProg.total)) * 100)}%` }]} />
              </View>
            ) : (
              <Text style={styles.blockedMsg}>
                {offlineTiles
                  ? "Pack complet : bathy fine + balisage + mouillages + dangers, stocké sur l'appareil."
                  : "Déplacez les coins du carré pour ajuster la zone, puis lancez le téléchargement."}
              </Text>
            )}
            {!offlineBusy ? (
              <View style={styles.blockedBtnRow}>
                <TouchableOpacity
                  style={styles.blockedBtn}
                  onPress={() => {
                    // 1) analyse de la zone ; 2) téléchargement du pack.
                    void listDallesForPolygon(zoneCorners)
                      .then(async (r) => {
                        setOfflineTiles(r);
                        if (!r.tiles.length) {
                          showToast("error", "Aucune dalle bathy de l'index dans cette zone.");
                          return;
                        }
                        const tok = { cancelled: false };
                        offlineCancelRef.current = tok;
                        setOfflineBusy(true);
                        setOfflineProg({ done: 0, total: r.tiles.length });
                        try {
                          const res = await downloadDalles(
                            r.tiles, (done, total) => setOfflineProg({ done, total }), tok);
                          const pack = await downloadSeamarkPack(zoneCorners).catch(() => null);
                          showToast(res.failed ? "error" : "success",
                            `${res.done}/${r.tiles.length} dalles stockées` +
                            (pack ? ` + ${pack.count} balises/mouillages/dangers` : "") +
                            `${res.failed ? ` (${res.failed} échec(s))` : ""}.`);
                          const fine = await checkFineTiles().catch(() => 0);
                          if (fine > 0) showToast("success", `${fine} dalle(s) fines 5 m/2 m récupérées.`);
                          setOfflineManifest(await getManifest());
                          mapRef.current?.stopZonePicker();
                          setZoneCorners(null);
                          setOfflineTiles(null);
                        } finally {
                          setOfflineBusy(false);
                          setOfflineProg(null);
                        }
                      })
                      .catch((e) => showToast("error", (e as Error).message));
                  }}
                  testID="offline-zone-download"
                >
                  <Ionicons name="download" size={16} color={theme.bg} />
                  <Text style={styles.blockedBtnTxt}>Lancer le téléchargement</Text>
                </TouchableOpacity>
              </View>
            ) : null}
          </View>
        </View>
      ) : null}

      {/* ── Popup « Zone de veille » (bouton cloche+engrenage) — réglages
          rapides uniquement. ── */}
      <AlertSettingsModal
        visible={alertSettingsOpen}
        bottomInset={insets.bottom}
        onClose={() => setAlertSettingsOpen(false)}
        onOpenFullSettings={() => {
          setAlertSettingsOpen(false);
          router.push("/profile/settings");
        }}
      />

      {/* ── N1 (20/07/2026) — Route sûre : pill de calcul puis RouteCard
          (distance, profil de profondeur, avertissements, fermer). ── */}
      {anyBusy ? (
        /* 10/09/2026 (V1.6 finale) — CHRONO + bouton « ARRÊTER LE CALCUL »
           sur TOUS les écrans de calcul (auto, manuelle, édition de points,
           recalcul moteur admin) : rend la main immédiatement. */
        <View style={styles.routeCardWrap} pointerEvents="box-none">
          <View style={styles.routeBusyPill}>
            <ActivityIndicator size="small" color="#48CAE4" />
            <Text style={styles.routeBusyTxt} testID="route-busy-chrono">
              Calcul de la route… {routeElapsedS} s
            </Text>
          </View>
          <TouchableOpacity
            style={styles.routeStopBtn}
            onPress={() => {
              if (routeCancelRef.current) routeCancelRef.current.cancelled = true;
            }}
            activeOpacity={0.85}
            testID="route-stop-btn"
          >
            <Ionicons name="stop-circle" size={18} color="#fff" />
            <Text style={styles.routeStopTxt}>ARRÊTER LE CALCUL</Text>
          </TouchableOpacity>
        </View>
      ) : blocked ? (
        /* 23/07 (demande armateur) — carte PERSISTANTE de blocage : message
           complet (réglage en cause + où le corriger) + accès direct aux
           réglages bateau. La carte a été recadrée sur le point rouge. */
        <View style={styles.routeCardWrap} pointerEvents="box-none">
          <View style={styles.blockedCard} testID="blocked-card">
            <View style={styles.blockedHead}>
              <Ionicons name="alert-circle" size={20} color={theme.danger} />
              <Text style={styles.blockedTitle}>Passage impossible</Text>
              <TouchableOpacity
                onPress={() => setBlocked(null)}
                hitSlop={10}
                testID="blocked-close"
              >
                <Ionicons name="close" size={20} color={theme.textMute} />
              </TouchableOpacity>
            </View>
            <Text style={styles.blockedMsg}>
              {blocked.message || "Passage impossible avec ces réglages : le point de blocage est affiché en rouge sur la carte."}
            </Text>
            <View style={styles.blockedBtnRow}>
              <TouchableOpacity
                style={styles.blockedBtn}
                onPress={() => router.push("/profile/boat")}
                testID="blocked-open-boat"
              >
                <Ionicons name="boat" size={16} color={theme.bg} />
                <Text style={styles.blockedBtnTxt}>Régler Mon bateau</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      ) : routeRetry ? (
        /* 02/08/2026 (armateur : « à chaque 429 le départ de la route saute »)
           — bandeau PERSISTANT : le départ et la destination sont conservés,
           un tap relance le calcul. */
        <View style={styles.routeCardWrap} pointerEvents="box-none">
          <View style={styles.blockedCard} testID="route-retry-card">
            <View style={styles.blockedHead}>
              <Ionicons name={routeRetry.reason === "stop" ? "stop-circle" : "cloud-offline"} size={20} color="#FFB703" />
              <Text style={styles.blockedTitle}>
                {routeRetry.reason === "stop" ? "Calcul arrêté" : "Calcul interrompu"}
              </Text>
              <TouchableOpacity
                onPress={() => setRouteRetry(null)}
                hitSlop={10}
                testID="route-retry-close"
              >
                <Ionicons name="close" size={20} color={theme.textMute} />
              </TouchableOpacity>
            </View>
            <Text style={styles.blockedMsg}>
              {routeRetry.reason === "stop"
                ? "Calcul arrêté à votre demande. Départ et destination conservés : modifiez vos points ou relancez."
                : routeRetry.reason === "429"
                  ? "Le serveur a refusé la demande (réseau saturé). Rien n'est perdu : votre départ et votre destination sont conservés."
                  : "Connexion interrompue pendant le calcul. Votre départ et votre destination sont conservés."}
            </Text>
            <View style={styles.blockedBtnRow}>
              <TouchableOpacity
                style={styles.blockedBtn}
                onPress={() => {
                  const rr = routeRetry;
                  setRouteRetry(null);
                  void computeSafeRoute(rr.dest, rr.from);
                }}
                testID="route-retry-again"
              >
                <Ionicons name="refresh" size={16} color={theme.bg} />
                <Text style={styles.blockedBtnTxt}>Réessayer</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.blockedBtn, styles.blockedBtnAlt]}
                onPress={() => {
                  const rr = routeRetry;
                  setRouteRetry(null);
                  // Replacer le départ SANS reperdre la destination.
                  mapRef.current?.flyTo(rr.from.lat, rr.from.lng, 15);
                  setRoutePickDest(rr.dest);
                }}
                testID="route-retry-repick"
              >
                <Ionicons name="locate" size={16} color="#48CAE4" />
                <Text style={styles.blockedBtnAltTxt}>Replacer le départ</Text>
              </TouchableOpacity>
              {routeRetry.reason === "stop" && isAdmin ? (
                /* 08/09/2026 — ADMIN : changer de MOTEUR avant de relancer
                   (le moteur actif se choisit dans Réglages ▸ Navigation). */
                <TouchableOpacity
                  style={[styles.blockedBtn, styles.blockedBtnAlt]}
                  onPress={() => router.push("/profile/settings")}
                  testID="route-retry-engine"
                >
                  <Ionicons name="cog" size={16} color="#48CAE4" />
                  <Text style={styles.blockedBtnAltTxt}>Changer de moteur</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          </View>
        </View>
      ) : compare ? (
        /* 02/08/2026 (demande armateur) — COMPARAISON A/B DE MOTEURS : la
           RouteCard laisse la place à la légende des deux tracés (la carte
           doit rester lisible pour juger les écarts). */
        <View style={styles.routeCardWrap} pointerEvents="box-none">
          <RouteCompareBar
            unit={mapUnit}
            base={{
              name: compare.base.engine?.name ?? "Route de référence",
              id: compare.base.engine?.id ?? "—",
              distanceM: compare.base.distance_m,
              minDepthM: compare.base.min_depth_m ?? null,
            }}
            variant={{
              name: compare.engineName,
              id: compare.engineId,
              distanceM: compare.variant.distance_m,
              minDepthM: compare.variant.min_depth_m ?? null,
            }}
            maxDevM={compare.diff.maxDevM}
            zones={diffCount(compare.diff)}
            identical={compare.diff.identical}
            // 27/08 (demande armateur) — coordonnées exactes du trajet comparé.
            start={compare.base.waypoints[0] ?? null}
            end={compare.base.waypoints[compare.base.waypoints.length - 1] ?? null}
            onFocusDiff={() => {
              const a = compare.diff.anchorVariant ?? compare.diff.anchorBase;
              if (!a) return;
              mapRef.current?.suspendFollow(true);
              mapRef.current?.flyTo(a.lat, a.lng, 16);
            }}
            onKeepVariant={() => {
              const v = compare.variant;
              setCompare(null);
              setRoute({ ...v, mode: compare.base.mode });
              setRouteCardMode("full");
              showToast("success", `Variante ${compare.engineName} adoptée — enregistrez-la pour la conserver.`);
            }}
            onClose={() => {
              setCompare(null);
              setRouteCardMode("full");
            }}
          />
        </View>
      ) : route && routeCardMode === "full" ? (
        <View style={styles.routeCardWrap} pointerEvents="box-none">
          <RouteCard
            route={route}
            unit={mapUnit}
            draftM={boatDraftM}
            onClose={() => setRouteCardMode("hidden")}
            onMinimize={() => setRouteCardMode("min")}
            onSave={() => {
              setSaveName("");
              setSaveNameOpen(true);
            }}
            onEdit={navFollow ? undefined : () => {
              // 08/09/2026 — « Modifier » depuis le menu du bandeau : entre en
              // mode édition (même mécanique que l'appui long sur le tracé).
              if (!route || route.waypoints.length < 2) return;
              mapRef.current?.suspendFollow(true);
              setEditPoints(route.waypoints.map((w) => ({ lat: w.lat, lng: w.lng })));
              setEditIdx(null);
              setEditMoved(false);
              setRouteCardMode("hidden");
              showToast("info", "Appuyez longuement près du tracé pour choisir le waypoint à déplacer.");
            }}
            onShare={async () => {
              // 08/09/2026 — « Partager » : résumé texte de la route.
              const st = route.waypoints[0];
              const en = route.waypoints[route.waypoints.length - 1];
              const msg =
                `Route SignalMar — ${(route.distance_m / 1000).toFixed(1)} km` +
                (route.min_depth_m != null ? ` · fond mini ${route.min_depth_m.toFixed(1)} m` : "") +
                `\nDépart : ${st.lat.toFixed(6)}, ${st.lng.toFixed(6)}` +
                `\nArrivée : ${en.lat.toFixed(6)}, ${en.lng.toFixed(6)}` +
                (route.route_id ? `\nID : ${route.route_id}` : "") +
                "\nRoute conseillée — ne remplace pas les cartes officielles.";
              try {
                await Share.share({ message: msg });
              } catch {
                showToast("error", "Partage impossible sur cet appareil.");
              }
            }}
            onDelete={() => {
              setRoute(null);
              setBlocked(null);
              showToast("info", "Route supprimée.");
            }}
            onNavigate={() => void startFollow()}
            computeS={routeComputeS}
            onFocusDanger={(lat, lng, spanM) => {
              // 26/07 — tap sur la zone rouge du profil : centre + zoom sur
              // la section dangereuse (recentrage auto suspendu).
              mapRef.current?.suspendFollow(true);
              const zoom = Math.max(12, Math.min(17, Math.round(16 - Math.log2(Math.max(spanM, 100) / 400))));
              mapRef.current?.flyTo(lat, lng, zoom);
              setRouteCardMode("min");
            }}
            onCompareEngine={navFollow ? undefined : () => setEnginePickerOpen(true)}
          />
        </View>
      ) : route && routeCardMode === "min" ? (
        <View style={styles.routeCardWrap} pointerEvents="box-none">
          <TouchableOpacity
            style={styles.routeMinPill}
            onPress={() => setRouteCardMode("full")}
            activeOpacity={0.85}
            testID="route-min-pill"
          >
            <Ionicons name="navigate" size={14} color="#E5383B" />
            <Text style={styles.routeMinTxt}>
              {(route.distance_m / 1000).toFixed(1)} km
            </Text>
            <Ionicons name="chevron-up" size={16} color={theme.textMute} />
          </TouchableOpacity>
        </View>
      ) : null}

      {/* 26/07 — route ouverte depuis le PROFIL : bouton retour.
          28/07 — DÉSACTIVÉ pendant la navigation (il ne menait nulle part). */}
      {fromProfile && route && !navFollow ? (
        <TouchableOpacity
          style={[styles.backProfileBtn, { top: insets.top + 58 }]}
          onPress={() => {
            setFromProfile(false);
            router.back();
          }}
          activeOpacity={0.85}
          testID="map-back-profile"
        >
          <Ionicons name="arrow-back" size={16} color={theme.text} />
          <Text style={styles.backProfileTxt}>Retour au profil</Text>
        </TouchableOpacity>
      ) : null}

      {/* 29/07 (retour mer, choix armateur) — GPS dégradé : simple
          avertissement non bloquant. */}
      {gpsPoor ? (
        <View style={[styles.devWrap, { top: insets.top + 108 }]} pointerEvents="none">
          <View style={styles.gpsPoorPill} testID="gps-poor-pill">
            <Ionicons name="warning-outline" size={13} color="#0B132B" />
            <Text style={styles.gpsPoorTxt}>Précision GPS réduite</Text>
          </View>
        </View>
      ) : null}

      {/* 26/07 (demande armateur) — bannière d'ÉCART DE ROUTE persistante :
          couper l'alerte, lien Réglages, X → pastille ré-ouvrable. */}
      {navFollow && deviation ? (
        deviationHidden ? (
          <View style={[styles.devWrap, { top: insets.top + 148 }]} pointerEvents="box-none">
            <TouchableOpacity
              style={styles.devPill}
              onPress={() => setDeviationHidden(false)}
              activeOpacity={0.85}
              testID="deviation-pill"
            >
              <Ionicons name="warning" size={14} color="#fff" />
              <Text style={styles.devPillTxt}>Écart {deviation.distM} m</Text>
              <Ionicons name="chevron-down" size={14} color="#fff" />
            </TouchableOpacity>
          </View>
        ) : (
          <View style={[styles.devWrap, { top: insets.top + 148 }]} pointerEvents="box-none">
            <View style={[styles.blockedCard, styles.devCard]} testID="deviation-card">
              <View style={styles.blockedHead}>
                <Ionicons name="warning" size={18} color="#E5383B" />
                <Text style={styles.blockedTitle}>Écart de route — {deviation.distM} m du corridor</Text>
                <TouchableOpacity onPress={() => setDeviationHidden(true)} hitSlop={10} testID="deviation-close">
                  <Ionicons name="close" size={20} color={theme.textMute} />
                </TouchableOpacity>
              </View>
              <View style={styles.devBtnRow}>
                <TouchableOpacity
                  style={[styles.devBtn, deviationMuted && styles.devBtnMuted]}
                  onPress={() => {
                    const next = !deviationMuted;
                    setDeviationMuted(next);
                    deviationMutedRef.current = next;
                    if (next) {
                      try { stopAlertFeedback(); } catch { /* noop */ }
                    }
                  }}
                  testID="deviation-mute"
                >
                  <Ionicons
                    name={deviationMuted ? "volume-mute" : "volume-high"}
                    size={15}
                    color={deviationMuted ? theme.textMute : "#fff"}
                  />
                  <Text style={[styles.devBtnTxt, deviationMuted && { color: theme.textMute }]}>
                    {deviationMuted ? "Alerte coupée" : "Couper l'alerte"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.devBtnGhost}
                  onPress={() => router.push("/profile/settings")}
                  testID="deviation-settings"
                >
                  <Ionicons name="settings-outline" size={15} color={theme.text} />
                  <Text style={styles.devBtnGhostTxt}>Réglages</Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        )
      ) : null}

      {/* 26/07 — la hauteur d'eau s'affiche désormais AU POINT cliqué sur la
          carte (pastille leaflet, prop waterPoint) — plus de carte en bas. */}

      {/* 08/09/2026 (remise à plat armateur) — les popups « route dangereuse /
          route plus sûre » (règle des 150 %) sont SUPPRIMÉS : un seul bandeau
          « Route conseillée » (RouteCard) avec infobulle de responsabilité. */}

      {/* 24/07 — acceptation du risque avant de suivre une route douteuse. */}
      <RiskConfirmModal
        visible={riskConfirmOpen}
        onAccept={() => {
          setRiskAccepted(true);
          setRiskConfirmOpen(false);
          void startFollowForced();
        }}
        onClose={() => setRiskConfirmOpen(false)}
      />

      {/* 02/08/2026 (demande armateur) — A/B TESTING : choix du moteur de
          recalcul (liste triée par ID décroissant). */}
      <EnginePickerModal
        visible={enginePickerOpen}
        baseEngineId={route?.engine?.id ?? null}
        baseEngineName={route?.engine?.name ?? null}
        busy={compareBusy}
        onPick={(e) => void runEngineCompare({ id: e.id, name: e.name })}
        onClose={() => {
          if (!compareBusy) setEnginePickerOpen(false);
        }}
      />

      {/* 21/07 — menu du tracé (tap sur la route) : détails / supprimer.
          26/08 — bandeau danger si le tap vient d'une ZONE ROUGE. */}
      <RouteMenuModal
        visible={routeMenuOpen}
        danger={routeMenuDanger}
        canRefresh={route?.mode === "auto" && routeCtxRef.current != null}
        onFollow={() => { setRouteMenuOpen(false); void startFollow(); }}
        onDetails={() => { setRouteMenuOpen(false); setRouteCardMode("full"); }}
        onRefresh={() => {
          const ctx = routeCtxRef.current;
          setRouteMenuOpen(false);
          if (ctx) void computeSafeRoute(ctx.dest, ctx.from);
        }}
        onCompare={() => { setRouteMenuOpen(false); setEnginePickerOpen(true); }}
        onSave={() => { setRouteMenuOpen(false); setSaveName(""); setSaveNameOpen(true); }}
        onDelete={() => {
          setRouteMenuOpen(false);
          setRoute(null);
          setBlocked(null);
          showToast("info", "Route supprimée.");
        }}
        onClose={() => setRouteMenuOpen(false)}
      />

      {/* 22/07 — « Créer une route » : CHOIX auto / manuelle / enregistrées. */}
      <RouteChoiceModal
        point={routeChoicePt}
        onAuto={(pt) => {
          setRouteChoicePt(null);
          setPickedPoint(userLocRef.current ?? pt);
          setRoutePickDest(pt);
        }}
        onManual={(pt) => {
          setRouteChoicePt(null);
          setManualPoints([pt]);
          showToast("info", "Départ placé — appui long sur la carte pour ajouter des étapes.");
        }}
        onClose={() => setRouteChoicePt(null)}
      />

      {/* 22/07 — barre de création de route MANUELLE (appui long = étape). */}
      {manualPoints != null && (
        <ManualRouteBar
          insetsBottom={insets.bottom}
          count={manualPoints.length}
          busy={manualBusy}
          onCancel={() => setManualPoints(null)}
          onUndo={() => setManualPoints((p) => (p && p.length > 1 ? p.slice(0, -1) : p))}
          onCreate={() => void createManualRoute()}
        />
      )}

      {/* 26/07 — barre d'ÉDITION de route. 11/08 (règle armateur) : un seul
          waypoint éditable (le plus proche du toucher), recalcul complet
          après déplacement. */}
      {editPoints != null && (
        <RouteEditBar
          insetsBottom={insets.bottom}
          editIdx={editIdx}
          busy={editBusy}
          moved={editMoved}
          onCancel={closeEdit}
          onSave={() => void commitEdit()}
        />
      )}

      {/* 22/07 — nom de la route à ENREGISTRER (max 20 / compte). */}
      <SaveRouteNameModal
        visible={saveNameOpen}
        name={saveName}
        saving={savingRoute}
        onChangeName={setSaveName}
        onSubmit={() => void submitSaveRoute()}
        onClose={() => setSaveNameOpen(false)}
      />

      {/* 26/07 — le popup « Mes routes enregistrées » a été déplacé dans le
          PROFIL (section « Mes routes », au-dessus de l'historique). */}

      {/* 22/07 — fiche BALISE (tap sur un seamark de la carte). */}
      <SeamarkInfoModal seamark={seamarkInfo} onClose={() => setSeamarkInfo(null)} />

      {/* 19/07 (retour device armateur : bouton trop haut en PORTRAIT) —
          ne PAS ajouter insets.bottom : la barre d'échelle est positionnée
          par rapport au bas du CONTENEUR carte (la tab bar absorbe déjà la
          safe area en dessous) ; l'ajouter décalait le bouton de ~50 px sur
          Android. Référence commune = bas du conteneur : barre ≈ 39 px
          (bottom 10 + ~29 de hauteur) → bouton à 39 + 5 = 44 px, séparation
          5 px sur TOUS les devices et orientations. */}
      {/* ── 09/09/2026 (V1.6 armateur) — bouton « Cartes 📥 » en bas à
          gauche (à gauche de l'échelle) + pastille de SOURCE des données
          (verte LOCAL = dalle stockée sur l'appareil / grise SERVER). ── */}
      {!picking && manualPoints == null && editPoints == null && (
        <View style={[styles.cartesWrap, { bottom: 44 }]} pointerEvents="box-none">
          <TouchableOpacity
            style={styles.cartesBtn}
            testID="cartes-btn"
            activeOpacity={0.85}
            onPress={() => {
              if (zoneCorners != null) {
                mapRef.current?.stopZonePicker();
                setZoneCorners(null);
                setOfflineTiles(null);
                return;
              }
              mapRef.current?.suspendFollow(true);
              mapRef.current?.startZonePicker();
            }}
          >
            <Text style={styles.cartesTxt}>Cartes 📥</Text>
          </TouchableOpacity>
          <View style={styles.srcBadge} testID="data-source-badge">
            <View style={[styles.srcDot, { backgroundColor: dataIsLocal ? "#2EC46B" : "#8D99AE" }]} />
            <Text style={[styles.srcTxt, dataIsLocal && { color: "#2EC46B" }]}>
              {dataIsLocal ? "LOCAL" : "SERVER"}
            </Text>
          </View>
        </View>
      )}

      <View
        style={[
          styles.fabStack,
          // 24/07 — bandeau de navigation réduit docké en bas : on remonte
          // le bouton Signaler + la colonne d'icônes juste au-dessus.
          { bottom: 44 },
        ]}
        pointerEvents="box-none"
      >
        {!picking && manualPoints == null && (
          <View style={styles.fabRow} pointerEvents="box-none">
            {/* Signaler — CENTRÉ horizontalement (17/07, test armateur) ;
                la colonne d'icônes reste ancrée en bas à droite.
                27/07 (vidéo 15h45) — masqué pendant l'ÉDITION de route
                (il gênait la validation du tracé au 1er plan). */}
            {editPoints == null && (
            <TouchableOpacity
              style={styles.fab}
              onPress={reportHere}
              activeOpacity={0.85}
              testID="map-report-fab"
            >
              <Ionicons name="add" size={30} color={theme.bg} />
              <Text style={styles.fabLabel}>Signaler</Text>
            </TouchableOpacity>
            )}
            <View style={styles.fabCol} pointerEvents="box-none">
            {/* Réglage des alertes sonores — cloche + engrenage. 24/07/2026 :
                DÉSACTIVÉ (demande armateur, colonne droite surchargée) — le
                réglage reste accessible via Réglages ; code conservé pour
                réactivation ultérieure. */}
            {false && (
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
            )}
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

            {/* 24/07 soir (demande armateur) — l'emplacement du refresh est
                repris par le toggle HAUTEUR D'EAU AU TOUCHER (goutte d'eau) ;
                le refresh devient un petit bouton près des coordonnées. */}
            <TouchableOpacity
              style={[styles.bathyBtn, waterTapOn && styles.bathyBtnOn]}
              onPress={() => {
                const next = !waterTapOn;
                setWaterTapOn(next);
                if (!next) setWaterInfo(null);
                Haptics.selectionAsync().catch(() => {});
                showToast(
                  "info",
                  next
                    ? "Hauteur d'eau au toucher activée — touchez l'eau"
                    : "Hauteur d'eau au toucher désactivée",
                );
              }}
              activeOpacity={0.85}
              testID="map-water-toggle"
              accessibilityRole="switch"
              accessibilityState={{ checked: waterTapOn }}
              accessibilityLabel={waterTapOn ? "Désactiver la hauteur d'eau au toucher" : "Activer la hauteur d'eau au toucher"}
            >
              <Ionicons
                name={waterTapOn ? "water" : "water-outline"}
                size={20}
                color={waterTapOn ? "#48CAE4" : theme.textMute}
              />
            </TouchableOpacity>

            {/* 19/07/2026 — PROTOTYPE bathymétrie SHOM : surcouche profondeurs
                (open data SHOM, pas pour la navigation officielle). */}
            <TouchableOpacity
              style={[styles.bathyBtn, bathyOn && styles.bathyBtnOn]}
              onPress={() => {
                const next = !bathyOn;
                setBathyOn(next);
                Haptics.selectionAsync().catch(() => {});
                showToast(
                  "info",
                  next
                    ? "Bathymétrie SHOM activée — appui long : opacité"
                    : "Bathymétrie désactivée",
                );
              }}
              onLongPress={() => {
                // 19/07 (retour armateur) — appui long = réglage d'opacité.
                if (!bathyOn) setBathyOn(true);
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
                setBathyModalOpen(true);
              }}
              delayLongPress={450}
              activeOpacity={0.85}
              testID="map-bathy-toggle"
              accessibilityRole="switch"
              accessibilityState={{ checked: bathyOn }}
              accessibilityLabel={bathyOn ? "Désactiver la bathymétrie" : "Activer la bathymétrie"}
            >
              <Ionicons
                name={bathyOn ? "map" : "map-outline"}
                size={20}
                color={bathyOn ? "#48CAE4" : theme.textMute}
              />
            </TouchableOpacity>

            {/* 23/07/2026 — ALARME DE MOUILLAGE : bouton ancre (pose/levée +
                rayon de garde ; aussi réglable dans les Réglages). */}
            <TouchableOpacity
              style={[styles.bathyBtn, anchor && (anchorAlarm ? styles.anchorBtnAlarm : styles.anchorBtnOn)]}
              onPress={() => {
                Haptics.selectionAsync().catch(() => {});
                setAnchorModalOpen(true);
              }}
              activeOpacity={0.85}
              testID="map-anchor-toggle"
              accessibilityLabel={anchor ? "Alarme de mouillage active" : "Poser l'ancre (alarme de mouillage)"}
            >
              <MaterialCommunityIcons
                name="anchor"
                size={20}
                color={anchor ? (anchorAlarm ? "#E5383B" : "#2EC4B6") : theme.textMute}
              />
            </TouchableOpacity>

            {/* 24/07/2026 (demande armateur) — le recentrage est REMONTÉ sous
                les boutons de zoom ; tout en bas de la colonne : le COMPAS DE
                MESURE (segment A→B, distance au mètre + relèvement,
                magnétisme balises/routes/signalements/bateau). */}
            <TouchableOpacity
              style={[styles.locBtn, measureOn && styles.measureBtnOn]}
              onPress={() => {
                const next = !measureOn;
                setMeasureOn(next);
                Haptics.selectionAsync().catch(() => {});
                if (next) {
                  // Règle armateur : consultation libre pendant la mesure —
                  // l'auto-recentrage reprendra via le bouton de recentrage.
                  mapRef.current?.suspendFollow(true);
                  showToast("info", "Compas de mesure — déplacez A et B, tap sur la valeur : m ⇄ NM");
                }
              }}
              activeOpacity={0.85}
              testID="map-measure-toggle"
              accessibilityRole="switch"
              accessibilityState={{ checked: measureOn }}
              accessibilityLabel={measureOn ? "Fermer le compas de mesure" : "Ouvrir le compas de mesure"}
            >
              <MaterialCommunityIcons
                name="math-compass"
                size={22}
                color={measureOn ? "#FFD166" : theme.textMute}
              />
            </TouchableOpacity>
            </View>
          </View>
        )}
      </View>

      {/* 23/07/2026 (demande armateur) — boutons zoom FIXES en HAUT-DROITE,
          toujours SOUS le bouton notifications avec une marge (plus de pile
          déplaçable). Décalés vers le bas si le panneau de suivi de route ou
          la bannière d'alarme de mouillage occupent le haut de l'écran. */}
      {!picking && (
        <View
          style={[
            styles.zoomStackFixed,
            {
              top:
                insets.top + 8 + 44 + 12 +
                (navActive ? 96 : 0) +
                (anchorAlarm && anchor ? 168 : 0),
            },
          ]}
          testID="map-zoom-stack"
        >
          <TouchableOpacity
            style={styles.zoomBtnFixed}
            onPress={() => mapRef.current?.zoomIn()}
            activeOpacity={0.85}
            testID="map-zoom-in"
          >
            <Ionicons name="add" size={22} color={theme.text} />
          </TouchableOpacity>
          <View style={styles.zoomSepFixed} />
          <TouchableOpacity
            style={styles.zoomBtnFixed}
            onPress={() => mapRef.current?.zoomOut()}
            activeOpacity={0.85}
            testID="map-zoom-out"
          >
            <Ionicons name="remove" size={22} color={theme.text} />
          </TouchableOpacity>
          {/* 24/07/2026 (demande armateur) — recentrage déplacé SOUS les
              boutons de zoom (avant : bas de la colonne droite). */}
          <View style={styles.zoomSepFixed} />
          <TouchableOpacity
            style={styles.zoomBtnFixed}
            onPress={recenter}
            onLongPress={() => {
              // 26/07 (demande armateur) — appui LONG = auto-recentrage
              // DÉSACTIVÉ (consultation libre) ; tap normal = réactivation.
              mapRef.current?.suspendFollow(true);
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
              showToast("info", "Recentrage automatique désactivé — tap sur ce bouton pour le réactiver.");
            }}
            delayLongPress={450}
            activeOpacity={0.85}
            testID="map-recenter-button"
          >
            <Ionicons name="locate" size={20} color={theme.text} />
          </TouchableOpacity>
        </View>
      )}

      {/* Loupe (12/07/2026) — bas GAUCHE : recherche par ID COURT.
          17/07/2026 — MASQUÉE jusqu'à nouvel ordre (retour user : sera
          réactivée quand la recherche sera étendue par ID + par type
          d'objet, dans une prochaine itération). Le code est conservé
          en place pour ne pas casser la modale de recherche associée. */}
      {false && !picking && (
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
      <SearchByCodeModal
        visible={searchOpen}
        code={searchCode}
        err={searchErr}
        busy={searchBusy}
        onChangeCode={(v) => { setSearchCode(v.toUpperCase()); setSearchErr(null); }}
        onSubmit={searchByCode}
        onClose={() => setSearchOpen(false)}
      />

      {/* 20/07 — « Créer une route » : barre de choix du DÉPART. */}
      {routePickDest != null && (
        <RoutePickBar
          insetsBottom={insets.bottom}
          pickedPoint={pickedPoint}
          tideChoice={tideChoice}
          onTideChoice={setTideChoice}
          onCancel={() => setRoutePickDest(null)}
          onConfirm={() => {
            const dest = routePickDest;
            setRoutePickDest(null);
            if (!dest) return;
            void computeSafeRoute(dest, pickedPoint);
          }}
        />
      )}

      {picking && (
        <PickPlaceBar
          insetsBottom={insets.bottom}
          pickedPoint={pickedPoint}
          shiftMode={!!shiftReportId}
          authorShiftMode={authorShiftMode}
          busy={submittingShift}
          onCancel={cancelPick}
          onConfirm={confirmPick}
        />
      )}


      {loading && Platform.OS !== "web" && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.primary} />
        </View>
      )}

      {/* PHASE 4 — Filter bottom-sheet (multi-select). Lives above the map. */}
      <MapFilterSheet
        visible={filterSheetOpen}
        selectedTypes={selectedTypes}
        setSelectedTypes={setSelectedTypes}
        toggleType={toggleType}
        hideFakes={hideFakes}
        setHideFakes={setHideFakes}
        onApply={() => {
          setFilterSheetOpen(false);
          fetchReports();
        }}
        onClose={() => setFilterSheetOpen(false)}
      />

      <CoordsPopup
        visible={coordsPopupOpen}
        lat={userLoc?.lat ?? null}
        lng={userLoc?.lng ?? null}
        onClose={() => setCoordsPopupOpen(false)}
      />

      {/* Phase K — Cone config modal (angle + distance, aperçu live). */}
      <ConeConfigModal
        visible={coneModalOpen}
        coneAngleDeg={coneAngleDeg}
        setConeAngleDeg={setConeAngleDeg}
        zoneNavM={voiceSettings.zoneNavM ?? 9260}
        onCommitZoneNavM={(m) => { void updateVoiceSettings({ zoneNavM: m }); }}
        onClose={() => setConeModalOpen(false)}
      />

      {/* Compteur de vitesse agrandi — bande « Verre ». */}
      <SpeedometerOverlay
        visible={speedoOpen}
        onClose={() => {
          setSpeedoOpen(false);
          // 28/07 — l'unité a pu être basculée dans le compteur : resynchro.
          storage.getItem<"kn" | "kmh">("sm.speedo.unit", "kn")
            .then((u) => setSpeedUnit(u === "kmh" ? "kmh" : "kn"))
            .catch(() => {});
        }}
        speedMs={userSpeed}
        heading={userHeading}
      />
    </View>
  );
}

