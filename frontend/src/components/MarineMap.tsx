import { useMemo, useRef, useEffect, forwardRef, useImperativeHandle } from "react";
import { Platform, StyleSheet, View } from "react-native";
import { WebView, type WebViewMessageEvent } from "react-native-webview";
import { captureRef } from "react-native-view-shot";

import { TYPE_COLOR, buildHtml } from "./marine-map/leaflet-html";
import type { ComputedRoute, ReportItem, Seamark } from "@/src/api/client";

// Base URL du backend — utilisée DANS la WebView pour charger les isobathes.
const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

// 24/07/2026 (« sauts dans le Golfe ») — dernière vue carte partagée au
// niveau MODULE : survit au remontage du composant (retour d'un écran
// détail signalement, onglet recréé, WebView Android rechargée). Un simple
// ref interne était perdu à chaque recréation → la carte repartait sur le
// centre par défaut (large Golfe du Morbihan).
let lastKnownView: { lat: number; lng: number; zoom: number } | null = null;

export type MarineMapHandle = {
  flyTo: (lat: number, lng: number, zoom?: number) => void;
  /** Zoom instantané (non animé) — survit au recentrage du follow-mode. */
  setZoom: (zoom: number) => void;
  /** Boutons natifs +/- (12/07/2026) — zoom pas-à-pas instantané. */
  zoomIn: () => void;
  zoomOut: () => void;
  setCrosshair: (enabled: boolean) => void;
  /** Phase J — toggle navigation follow-mode (course-up + 3/5 vertical anchor + auto-recenter).
   *  skipRecenter=true : re-synchronise le mode sans recentrer immédiatement
   *  (retour depuis un détail de signalement — 13/07/2026). */
  setNavMode: (on: boolean, skipRecenter?: boolean) => void;
  /** Phase J — immediate recenter on the current user position, keeping zoom. */
  recenterOnUser: () => void;
  /** 20/07/2026 — pause/reprise de l'auto-recentrage (appui long carte). */
  suspendFollow: (on: boolean) => void;
  /** 13/07/2026 — repousse le recentrage automatique de 5 s (comme un geste
   *  utilisateur) sans bouger la carte. */
  grantRecenterGrace: () => void;
  /** Phase K — set/update the yellow projection cone (or clear with null). */
  setNavCone: (halfAngleDeg: number | null, distanceKm: number | null) => void;
  /** Phase K.5 — set/update the Vigie mode radar ping radius (m). Pass 0/null to clear. */
  setRadarPing: (radiusM: number | null) => void;
  /** 17/07/2026 (v2 cône coloré) — pousse l'état visuel du cône Nav :
   *   green  = rien dans le cône  ·  orange = signalement dans le cône hors zone d'alerte  ·
   *   red    = signalement dans la zone d'alerte (déclenche le son via sound-alert). */
  setConeState: (state: "green" | "orange" | "red") => void;
  /** 17/07/2026 — force Leaflet à recalculer la taille du conteneur (utile
   *  quand une bannière d'alerte plein largeur peut faire perdre les tuiles
   *  sur Android → carte noire). */
  refreshMap: () => void;
  /** 31/07/2026 — CAPTURE D'ÉCRAN de la WebView (map + route + balises +
   *  bathy). Retourne un data URL (data:image/jpeg;base64,...). Utilisé par
   *  la fonction « Envoyer au support » de l'armateur. */
  captureMap: () => Promise<string | null>;
};

type Props = {
  center: { lat: number; lng: number };
  zoom?: number;
  userLocation?: { lat: number; lng: number } | null;
  /** Phase I — true heading 0-360°. Null when unknown (boat not moving + no compass). */
  userHeading?: number | null;
  /** Phase I — speed-over-ground in m/s. Drives the projection line length. */
  userSpeed?: number | null;
  /** Phase I — when false, hide the boat marker + projection line entirely
   *  (legacy blue dot is shown instead so the user still sees their position). */
  showBoat?: boolean;
  /** Phase K — yellow projection cone half-angle (degrees). When null OR when
   *  showBoat is false, the cone is hidden. E.g. 22.5 → 45° total spread. */
  coneHalfAngleDeg?: number | null;
  /** Phase K — cone forward distance in km (typically speed × look-ahead).
   *  When null OR ≤ 0, the cone is hidden. */
  coneDistanceKm?: number | null;
  /** Phase K.5 — Vigie-mode radar ping radius (m). When >0, draws animated
   *  concentric red circles pulsing around the boat. Null/0 hides them. */
  radarPingRadiusM?: number | null;
  /** Phase K.8 — when true, the map rotates so the current heading points
   *  up (course-up mode). When false or missing, the map stays north-up
   *  even if a heading is known. Passed by map.tsx = navMode. */
  courseUp?: boolean;
  reports: ReportItem[];
  crosshair?: boolean;
  /** When set, the matching report's marker is rendered with a glowing halo. */
  focusId?: string | null;
  onMarkerPress?: (id: string) => void;
  onMapMoved?: (lat: number, lng: number) => void;
  onMapLongPress?: (lat: number, lng: number) => void;
  /** 16/07/2026 — unité d'affichage des échelles ('km' | 'nm'). */
  mapUnit?: "km" | "nm";
  /** Callback quand l'utilisateur tape sur une échelle (bascule d'unité). */
  onRulerTap?: () => void;
  /** 19/07/2026 — PROTOTYPE : surcouche bathymétrie SHOM (open data,
   *  Licence Ouverte — non utilisable pour la navigation officielle).
   *  false/absent = aucune requête WMS émise. */
  bathymetry?: boolean;
  /** 19/07/2026 — opacité de la surcouche bathymétrie (0.3-1, défaut 0.7). */
  bathymetryOpacity?: number;
  /** N1 (20/07/2026) — route sûre calculée (waypoints + profil) ou null. */
  route?: ComputedRoute | null;
  /** 21/07/2026 — tap sur le tracé de la route (menu détails/supprimer). */
  onRouteTap?: () => void;
  /** 22/07/2026 — waypoints de la route MANUELLE en cours de création. */
  manualPoints?: { lat: number; lng: number }[] | null;
  /** 11/08 (règle armateur) — édition : SEUL ce waypoint est déplaçable
   *  (les autres deviennent de simples repères). null = tous déplaçables. */
  draftEditIndex?: number | null;
  /** 22/07/2026 — drag & drop d'un point de la route manuelle (dragend). */
  onDraftMove?: (index: number, lat: number, lng: number) => void;
  /** 22/07/2026 — point de blocage (route impossible) + tronçon atteignable. */
  blocked?: { blocked_at: { lat: number; lng: number }; partial_waypoints?: { lat: number; lng: number }[] } | null;
  /** 22/07/2026 — tap sur une balise (seamark) → fiche détails. */
  onSeamarkTap?: (mark: Seamark) => void;
  /** 23/07/2026 — SUIVI DE ROUTE : dernier waypoint dépassé + projection du
   *  bateau sur la route (tronçon parcouru grisé). null = pas de suivi. */
  routeProgress?: { passedIdx: number; lat: number; lng: number } | null;
  /** 28/07/2026 — CAP À SUIVRE : projection VERT FONCÉ depuis le bateau
   *  pendant la navigation d'une route (tap → étiquette). null = masquée. */
  targetBearingDeg?: number | null;
  /** 28/07/2026 — force l'affichage de la projection de cap RÉEL (rouge) :
   *  true en mode Navigation ET pendant le suivi de route. */
  showHeadingLine?: boolean;
  /** 23/07/2026 — ALARME DE MOUILLAGE : cercle de garde autour de l'ancre. */
  anchor?: { lat: number; lng: number; radiusM: number; alarm?: boolean } | null;
  /** 24/07/2026 — COMPAS DE MESURE : segment A→B (distance + relèvement),
   *  magnétisme balises/routes/signalements/bateau. */
  measure?: boolean;
  /** 24/07/2026 — accroche magnétique déclenchée (retour haptique côté RN). */
  onMeasureSnap?: () => void;
  /** 24/07/2026 — clic court sur l'eau libre (hauteur d'eau au point). */
  onMapTap?: (lat: number, lng: number) => void;
  /** 26/07/2026 — pastille hauteur d'eau AU POINT cliqué (sur la carte). */
  waterPoint?: { lat: number; lng: number; text?: string; loading?: boolean } | null;
  /** 26/07/2026 — tap sur la pastille hauteur d'eau (désactive le mode). */
  onWaterClose?: () => void;
  /** 31/07/2026 — POPUP CLIC CARTE (mode goutte d'eau OFF) : coordonnées +
   *  hauteur ZH + bouton capture support (visible uniquement pour admin). */
  mapTapInfo?: {
    lat: number;
    lng: number;
    loading?: boolean;
    error?: boolean;
    covered?: boolean;
    water?: boolean;
    depth_zh_m?: number | null;
    showSupport?: boolean;
  } | null;
  /** 31/07/2026 — fermeture du popup clic carte (bouton ×). */
  onMapTapClose?: () => void;
  /** 31/07/2026 — appui sur le bouton capture support du popup clic carte. */
  onMapTapSupport?: (lat: number, lng: number, depth_zh_m: number | null) => void;
  /** 02/08/2026 — silence réseau pendant un calcul de route (anti-429). */
  netQuiet?: boolean;
  /** 02/08/2026 — COMPARAISON A/B de moteurs : tracé variante superposé +
   *  surlignage des écarts + étiquettes « moteur · ID ». null = pas de
   *  comparaison en cours. */
  routeCompare?: {
    key: string;
    base: {
      waypoints: { lat: number; lng: number }[];
      label: string; color: string;
      anchor: { lat: number; lng: number } | null;
    };
    variant: {
      waypoints: { lat: number; lng: number }[];
      label: string; color: string;
      anchor: { lat: number; lng: number } | null;
    };
    diff_base: { lat: number; lng: number }[][];
    diff_variant: { lat: number; lng: number }[][];
  } | null;
};

export const MarineMap = forwardRef<MarineMapHandle, Props>(function MarineMap(
  { center, zoom = 11, userLocation, userHeading, userSpeed, showBoat = true, coneHalfAngleDeg = null, coneDistanceKm = null, radarPingRadiusM = null, courseUp = false, reports, crosshair = false, focusId = null, onMarkerPress, onMapMoved, onMapLongPress, mapUnit = "km", onRulerTap, bathymetry = false, bathymetryOpacity = 0.7, route = null, onRouteTap, manualPoints = null, draftEditIndex = null, onDraftMove, blocked = null, onSeamarkTap, routeProgress = null, targetBearingDeg = null, showHeadingLine = false, anchor = null, measure = false, onMeasureSnap, onMapTap, waterPoint = null, onWaterClose, mapTapInfo = null, onMapTapClose, onMapTapSupport, routeCompare = null, netQuiet = false },
  ref,
) {
  const webRef = useRef<WebView | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const containerRef = useRef<View | null>(null);
  // 23/07/2026 — dernière vue carte connue (restaurée après un rechargement
  // de la WebView pour éviter le retour au centre par défaut).
  // 24/07/2026 — initialisée depuis la variable de MODULE pour survivre au
  // REMONTAGE du composant (retour d'un écran détail) — voir lastKnownView.
  const lastViewRef = useRef<{ lat: number; lng: number; zoom: number } | null>(lastKnownView);
  // Compteur de mises à jour consécutives « en mouvement » avant d'autoriser
  // la rotation course-up (filtre les pics GPS du démarrage à froid).
  const courseUpStreakRef = useRef(0);
  // 24/07/2026 (« sauts dans le Golfe » au clic sur certains signalements) —
  // si une vue est déjà connue dans la session, le HTML initial démarre
  // DIRECTEMENT dessus : plus aucun flash/retour au centre par défaut quand
  // la WebView est recréée (navigation détail → carte, onglet remonté…).
  const html = useMemo(() => {
    const c = lastKnownView ?? center;
    const z = lastKnownView?.zoom ?? zoom;
    return buildHtml(c, z, crosshair, API_BASE);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const sendJs = (js: string) => {
    if (Platform.OS === "web") {
      iframeRef.current?.contentWindow?.postMessage(
        JSON.stringify({ __sm_eval: js }),
        "*",
      );
    } else {
      webRef.current?.injectJavaScript(js + ";true;");
    }
  };

  useImperativeHandle(ref, () => ({
    flyTo: (lat, lng, z) => sendJs(`window.SM && SM.flyTo(${lat},${lng},${z ?? "undefined"})`),
    setZoom: (z) => sendJs(`window.SM && SM.setZoom(${z})`),
    zoomIn: () => sendJs(`window.SM && SM.zoomIn()`),
    zoomOut: () => sendJs(`window.SM && SM.zoomOut()`),
    setCrosshair: (on) => sendJs(`window.SM && SM.setCrosshair(${on})`),
    setNavMode: (on, skipRecenter) => sendJs(`window.SM && SM.setNavMode(${on},${skipRecenter ? "true" : "false"})`),
    recenterOnUser: () => sendJs(`window.SM && SM.recenterOnUser(true)`),
    suspendFollow: (on) => sendJs(`window.SM && SM.setFollowSuspended(${on ? "true" : "false"})`),
    grantRecenterGrace: () => sendJs(`window.SM && SM.grantGrace()`),
    setNavCone: (halfAngleDeg, distKm) => sendJs(
      `window.SM && SM.setNavCone(${halfAngleDeg == null ? "null" : halfAngleDeg},${distKm == null ? "null" : distKm})`,
    ),
    setRadarPing: (radiusM) => sendJs(
      `window.SM && SM.setRadarPing(${radiusM == null ? 0 : radiusM})`,
    ),
    setConeState: (state) => sendJs(
      `window.SM && SM.setConeState(${JSON.stringify(state)})`,
    ),
    refreshMap: () => sendJs(
      // invalidateSize + re-emit du prefetch + rulers pour couvrir tous
      // les cas de « carte figée / noire » après ouverture d'une modale.
      `try {`
      + `if (window.__map__) window.__map__.invalidateSize({animate:false});`
      + `if (window.__updateRulers) window.__updateRulers();`
      + `} catch(_){}`,
    ),
    // 31/07/2026 — Capture d'écran de la WebView (map + route + balises).
    //  - Natif : react-native-view-shot capture la View native englobant la
    //    WebView Android/iOS → pixels effectivement rendus (tuiles OSM +
    //    seamark overlay + polylines Leaflet + markers).
    //  - Web (iframe) : indisponible (fallback null → l'app affiche « capture
    //    indisponible sur web »).
    captureMap: async () => {
      if (Platform.OS === "web") return null;
      const view = containerRef.current;
      if (!view) return null;
      try {
        // 03/08/2026 — capture RÉDUITE : 1080 px de large et qualité 0,55
        // (≈ 120-220 Ko au lieu de 300-400 Ko). Moins de morceaux à envoyer =
        // moins de risque de throttling, et la carte marine reste lisible.
        const uri = await captureRef(view, {
          format: "jpg", quality: 0.55, result: "data-uri", width: 1080,
        });
        return typeof uri === "string" ? uri : null;
      } catch (err) {
        console.warn("captureMap failed", err);
        return null;
      }
    },
  }));

  // Push reports + user location whenever they change.
  useEffect(() => {
    const payload = reports.map((r) => ({
      id: r.id,
      lat: r.lat,
      lng: r.lng,
      color: TYPE_COLOR[r.type] || "#48CAE4",
      label: r.type,
      focus: focusId === r.id,
      is_test: !!r.is_test,
      heading: r.activity === "navigation" ? r.heading ?? null : null,
      speed_knots: r.activity === "navigation" ? r.speed_knots ?? null : null,
      rank_id: r.author?.rank_id ?? null,
      reliability_score: r.author?.reliability_score ?? null,
      drift_cone: r.drift_cone
        ? {
            polygon: r.drift_cone.polygon,
            distance_km: r.drift_cone.distance_km,
            bearing_deg: r.drift_cone.bearing_deg,
            wind_source: r.drift_cone.wind_source,
            // Bande côtière < 20 km → avertissement « vent seul » (13/07).
            wind_only: r.drift_cone.wind_only ?? false,
          }
        : null,
    }));
    sendJs(`window.SM && SM.setReports(${JSON.stringify(payload)})`);
  }, [reports, focusId]);

  // Push the user marker (boat arrow + projection line when nav mode is ON,
  // else legacy blue dot) whenever location, heading or showBoat changes.
  useEffect(() => {
    if (!userLocation) return;
    const hd = userHeading != null ? userHeading : "null";
    const sp = userSpeed != null ? userSpeed : "null";
    const asBoat = showBoat ? "true" : "false";
    sendJs(`window.SM && SM.setUser(${userLocation.lat},${userLocation.lng},${hd},${sp},${asBoat})`);
  }, [userLocation, userHeading, userSpeed, showBoat]);

  // Phase I (v3) — Course-up rotation: rotate the whole map so the boat's
  // heading is at the top. Fully automatic based on speed:
  //   • speed < 3 km/h (0.833 m/s) → freeze the map north-up (setBearing(null))
  //   • speed ≥ 3 km/h AND heading known → rotate to heading
  // No `courseUp` gating anymore — the user asked for this to be a pure
  // speed-driven behaviour so a moving boat always gets a natural forward-up
  // view and a stationary one gets a stable north-up chart. The boat icon's
  // inner triangle (rot = heading - bearing) points UP when rotating and
  // shows the true compass heading when frozen north-up.
  useEffect(() => {
    const AUTO_COURSE_UP_MS = 0.833; // 3 km/h
    const qualifies = userHeading != null && (userSpeed ?? 0) >= AUTO_COURSE_UP_MS;
    if (qualifies) {
      // Anti « rotations fantômes au lancement » : les premiers fixes GPS
      // (démarrage à froid) rapportent parfois des pics de vitesse + caps
      // aléatoires → la carte pivotait brutalement. On exige une vitesse
      // soutenue (3 mises à jour consécutives qualifiantes) avant de
      // basculer en course-up ; le retour nord-haut reste immédiat.
      courseUpStreakRef.current += 1;
      if (courseUpStreakRef.current >= 3) {
        sendJs(`window.SM && SM.setBearing(${userHeading})`);
      }
    } else {
      courseUpStreakRef.current = 0;
      sendJs(`window.SM && SM.setBearing(null)`);
    }
  }, [userHeading, userSpeed]);

  useEffect(() => {
    sendJs(`window.SM && SM.setCrosshair(${crosshair})`);
  }, [crosshair]);

  // Phase K — Push the yellow cone params whenever they change. When either
  // param is null (Vigie mode, or missing GPS heading), the cone is cleared.
  useEffect(() => {
    const half = coneHalfAngleDeg != null && coneHalfAngleDeg > 0 ? coneHalfAngleDeg : "null";
    const dist = coneDistanceKm != null && coneDistanceKm > 0 ? coneDistanceKm : "null";
    sendJs(`window.SM && SM.setNavCone(${half},${dist})`);
  }, [coneHalfAngleDeg, coneDistanceKm]);

  // Phase K.5 — Push the radar-ping radius whenever it changes (or is cleared).
  // In Vigie mode the parent passes voiceSettings.zoneVigieM; in Nav mode it
  // passes null so the ping is removed (yellow cone takes over visually).
  useEffect(() => {
    const r = radarPingRadiusM != null && radarPingRadiusM > 0 ? radarPingRadiusM : 0;
    sendJs(`window.SM && SM.setRadarPing(${r})`);
  }, [radarPingRadiusM]);

  // 16/07/2026 — Unité d'échelle (km / NM). Poussée à chaque changement.
  useEffect(() => {
    sendJs(`window.__setMapUnit && window.__setMapUnit(${JSON.stringify(mapUnit)})`);
  }, [mapUnit]);

  // 19/07/2026 — PROTOTYPE bathymétrie SHOM : pousser le toggle.
  // N1 (20/07) — le MÊME bouton active aussi les ISOBATHES (lignes de
  // profondeur générées par notre backend, niveaux selon le zoom).
  useEffect(() => {
    sendJs(`window.__setBathy && window.__setBathy(${bathymetry ? "true" : "false"})`);
    sendJs(`window.__setIsobaths && window.__setIsobaths(${bathymetry ? "true" : "false"}, ${JSON.stringify(API_BASE)})`);
  }, [bathymetry]);
  useEffect(() => {
    sendJs(`window.__setBathyOpacity && window.__setBathyOpacity(${bathymetryOpacity})`);
  }, [bathymetryOpacity]);
  // N1 (20/07/2026) — pousser/effacer la route sûre.
  useEffect(() => {
    sendJs(`window.__setRoute && window.__setRoute(${JSON.stringify(route ?? null)})`);
  }, [route]);
  // 23/07/2026 — SUIVI DE ROUTE : progression (tronçon parcouru grisé).
  useEffect(() => {
    sendJs(`window.__setRouteProgress && window.__setRouteProgress(${JSON.stringify(routeProgress ?? null)})`);
  }, [routeProgress]);
  // 02/08/2026 — COMPARAISON A/B de moteurs (variante + écarts surlignés).
  useEffect(() => {
    sendJs(`window.__setRouteCompare && window.__setRouteCompare(${JSON.stringify(routeCompare ?? null)})`);
  }, [routeCompare]);
  // 02/08/2026 — silence réseau pendant un calcul de route (anti-429).
  useEffect(() => {
    sendJs(`window.__setNetQuiet && window.__setNetQuiet(${netQuiet ? "true" : "false"})`);
  }, [netQuiet]);
  // 28/07/2026 — CAP À SUIVRE : projection verte le long du cap à suivre.
  useEffect(() => {
    sendJs(`window.__setTargetBearing && window.__setTargetBearing(${JSON.stringify(targetBearingDeg ?? null)})`);
  }, [targetBearingDeg]);
  // 28/07/2026 — projection de cap RÉEL (rouge) forcée en Navigation/suivi.
  useEffect(() => {
    sendJs(`window.__setHeadingLine && window.__setHeadingLine(${showHeadingLine ? "true" : "false"})`);
  }, [showHeadingLine]);
  // 23/07/2026 — ALARME DE MOUILLAGE : cercle de garde autour de l'ancre.
  useEffect(() => {
    sendJs(`window.__setAnchor && window.__setAnchor(${JSON.stringify(anchor ?? null)})`);
  }, [anchor]);
  // 24/07/2026 — COMPAS DE MESURE : toggle du segment A→B.
  useEffect(() => {
    sendJs(`window.__setMeasure && window.__setMeasure(${measure ? "true" : "false"})`);
  }, [measure]);
  // 26/07/2026 — pastille hauteur d'eau au point cliqué.
  useEffect(() => {
    sendJs(`window.__setWaterPoint && window.__setWaterPoint(${JSON.stringify(waterPoint ?? null)})`);
  }, [waterPoint]);
  // 31/07/2026 — POPUP CLIC CARTE (mode goutte d'eau désactivé).
  useEffect(() => {
    sendJs(`window.__setMapTapInfo && window.__setMapTapInfo(${JSON.stringify(mapTapInfo ?? null)})`);
  }, [mapTapInfo]);
  // 22/07/2026 — route MANUELLE en création (tracé provisoire numéroté).
  useEffect(() => {
    sendJs(`window.__setDraftRoute && window.__setDraftRoute(${JSON.stringify(manualPoints ?? null)}, ${JSON.stringify(draftEditIndex ?? null)})`);
  }, [manualPoints, draftEditIndex]);
  // 22/07/2026 — point de blocage (route impossible) + tronçon atteignable.
  useEffect(() => {
    sendJs(`window.__setBlocked && window.__setBlocked(${JSON.stringify(blocked ?? null)})`);
  }, [blocked]);

  // 16/07/2026 — Prefetch actif de tuiles autour du bateau (2 km, Z-1/Z/Z+1).
  // Déclenché quand la position user CHANGE de manière significative
  // (~200 m ou plus) pour ne pas spammer le serveur de tuiles à chaque tick.
  const lastPrefetchRef = useRef<{ lat: number; lng: number } | null>(null);
  useEffect(() => {
    if (!userLocation) return;
    const prev = lastPrefetchRef.current;
    const moved =
      !prev ||
      Math.abs(prev.lat - userLocation.lat) > 0.002 ||
      Math.abs(prev.lng - userLocation.lng) > 0.002;
    if (!moved) return;
    lastPrefetchRef.current = { lat: userLocation.lat, lng: userLocation.lng };
    sendJs(`window.__prefetchAroundUser && window.__prefetchAroundUser(${userLocation.lat},${userLocation.lng})`);
  }, [userLocation]);

  const handleMessage = (raw: string) => {
    try {
      const d = JSON.parse(raw) as { event?: string; id?: string; lat?: number; lng?: number; zoom?: number; index?: number; mark?: Seamark; depth_zh_m?: number };
      if (d.event === "marker" && d.id) onMarkerPress?.(d.id);
      else if (d.event === "move" && typeof d.lat === "number" && typeof d.lng === "number") {
        // 23/07/2026 (vidéos armateur, « sauts dans le Golfe ») — mémorise la
        // DERNIÈRE vue : quand Android recharge la WebView (mémoire) ou que
        // l'iframe se réinitialise, la carte repartait sur le centre PAR
        // DÉFAUT (large Golfe). Au prochain 'ready', on restaure cette vue.
        lastViewRef.current = { lat: d.lat, lng: d.lng, zoom: typeof d.zoom === "number" ? d.zoom : 11 };
        lastKnownView = lastViewRef.current;
        onMapMoved?.(d.lat, d.lng);
      } else if (d.event === "longpress" && typeof d.lat === "number" && typeof d.lng === "number") {
        onMapLongPress?.(d.lat, d.lng);
      } else if (d.event === "ruler_tap") {
        onRulerTap?.();
      } else if (d.event === "route_tap") {
        onRouteTap?.();
      } else if (d.event === "seamark_tap" && d.mark) {
        onSeamarkTap?.(d.mark);
      } else if (d.event === "measure_snap") {
        onMeasureSnap?.();
      } else if (d.event === "map_tap" && typeof d.lat === "number") {
        onMapTap?.(d.lat, d.lng);
      } else if (d.event === "water_close") {
        onWaterClose?.();
      } else if (d.event === "map_tap_close") {
        onMapTapClose?.();
      } else if (d.event === "map_tap_support") {
        const depth = typeof d.depth_zh_m === "number" ? d.depth_zh_m : null;
        onMapTapSupport?.(d.lat as number, d.lng as number, depth);
      } else if (d.event === "draft_move" && typeof d.index === "number" && typeof d.lat === "number" && typeof d.lng === "number") {
        onDraftMove?.(d.index, d.lat, d.lng);
      } else if (d.event === "ready") {
        // 23/07/2026 — WebView RECHARGÉE (mémoire Android / iframe) : on
        // restaure la dernière vue de l'utilisateur au lieu de laisser la
        // carte sur le centre par défaut (« saut dans le Golfe »). Le vol
        // vers la position GPS ne se fait qu'au TOUT PREMIER chargement.
        const lastView = lastViewRef.current;
        // Push initial data right after the map signals ready.
        if (userLocation) {
          const hd = userHeading != null ? userHeading : "null";
          const sp = userSpeed != null ? userSpeed : "null";
          const asBoat = showBoat ? "true" : "false";
          sendJs(`window.SM && SM.setUser(${userLocation.lat},${userLocation.lng},${hd},${sp},${asBoat})`);
          // 16/07/2026 (retour terrain) — au lancement, la carte restait sur
          // le centre PAR DÉFAUT (large Morbihan/Loire-Atlantique) au lieu de
          // se centrer sur l'UTILISATEUR : on vole vers sa position dès que
          // la carte est prête et qu'une position est connue.
          if (!lastView) {
            sendJs(`window.SM && SM.flyTo(${userLocation.lat},${userLocation.lng},12)`);
          }
        }
        if (lastView) {
          sendJs(`window.SM && SM.setView && SM.setView(${lastView.lat},${lastView.lng},${lastView.zoom})`);
        }
        // Phase K — also push the current cone params (usually null on load
        // in Vigie mode) so the SM state is in sync.
        {
          const half = coneHalfAngleDeg != null && coneHalfAngleDeg > 0 ? coneHalfAngleDeg : "null";
          const dist = coneDistanceKm != null && coneDistanceKm > 0 ? coneDistanceKm : "null";
          sendJs(`window.SM && SM.setNavCone(${half},${dist})`);
        }
        // Phase K.5 — Push the initial radar-ping radius (Vigie mode). The
        // useEffect above may have fired before the map was ready, so re-emit
        // here to guarantee the sonar rings show up on first paint.
        {
          const r = radarPingRadiusM != null && radarPingRadiusM > 0 ? radarPingRadiusM : 0;
          sendJs(`window.SM && SM.setRadarPing(${r})`);
        }
        // 16/07/2026 — pousser l'unité d'échelle initiale + amorcer le
        // prefetch de tuiles autour du bateau.
        sendJs(`window.__setMapUnit && window.__setMapUnit(${JSON.stringify(mapUnit)})`);
        // 19/07/2026 — ré-émettre le toggle bathymétrie (l'effet a pu partir
        // avant que la carte soit prête).
        sendJs(`window.__setBathyOpacity && window.__setBathyOpacity(${bathymetryOpacity})`);
        if (bathymetry) {
          sendJs(`window.__setBathy && window.__setBathy(true)`);
          sendJs(`window.__setIsobaths && window.__setIsobaths(true, ${JSON.stringify(API_BASE)})`);
        }
        if (route) sendJs(`window.__setRoute && window.__setRoute(${JSON.stringify(route)})`);
        if (routeCompare) sendJs(`window.__setRouteCompare && window.__setRouteCompare(${JSON.stringify(routeCompare)})`);
        if (netQuiet) sendJs(`window.__setNetQuiet && window.__setNetQuiet(true)`);
        // 23/07 — ré-émission progression de suivi + ancre de mouillage.
        if (routeProgress) sendJs(`window.__setRouteProgress && window.__setRouteProgress(${JSON.stringify(routeProgress)})`);
        if (targetBearingDeg != null) sendJs(`window.__setTargetBearing && window.__setTargetBearing(${JSON.stringify(targetBearingDeg)})`);
        if (showHeadingLine) sendJs(`window.__setHeadingLine && window.__setHeadingLine(true)`);
        if (anchor) sendJs(`window.__setAnchor && window.__setAnchor(${JSON.stringify(anchor)})`);
        // 24/07 — ré-émission du compas de mesure si actif.
        if (measure) sendJs(`window.__setMeasure && window.__setMeasure(true)`);
        // 26/07 — ré-émission de la pastille hauteur d'eau si active.
        if (waterPoint) sendJs(`window.__setWaterPoint && window.__setWaterPoint(${JSON.stringify(waterPoint)})`);
        // 31/07 — ré-émission du popup clic carte si actif.
        if (mapTapInfo) sendJs(`window.__setMapTapInfo && window.__setMapTapInfo(${JSON.stringify(mapTapInfo)})`);
        // 22/07/2026 — balises cliquables (fetch par bbox depuis la WebView)
        // + ré-émission du tracé manuel / point de blocage éventuels.
        sendJs(`window.__setSeamarkTaps && window.__setSeamarkTaps(${JSON.stringify(API_BASE)})`);
        if (manualPoints?.length) sendJs(`window.__setDraftRoute && window.__setDraftRoute(${JSON.stringify(manualPoints)}, ${JSON.stringify(draftEditIndex ?? null)})`);
        if (blocked) sendJs(`window.__setBlocked && window.__setBlocked(${JSON.stringify(blocked)})`);
        if (userLocation) {
          sendJs(`window.__prefetchAroundUser && window.__prefetchAroundUser(${userLocation.lat},${userLocation.lng})`);
        }
        const payload = reports.map((r) => ({
          id: r.id,
          lat: r.lat,
          lng: r.lng,
          color: TYPE_COLOR[r.type] || "#48CAE4",
          label: r.type,
          focus: focusId === r.id,
          is_test: !!r.is_test,
          heading: r.activity === "navigation" ? r.heading ?? null : null,
          speed_knots: r.activity === "navigation" ? r.speed_knots ?? null : null,
          rank_id: r.author?.rank_id ?? null,
          reliability_score: r.author?.reliability_score ?? null,
          drift_cone: r.drift_cone
            ? {
                polygon: r.drift_cone.polygon,
                distance_km: r.drift_cone.distance_km,
                bearing_deg: r.drift_cone.bearing_deg,
                wind_source: r.drift_cone.wind_source,
                wind_only: r.drift_cone.wind_only ?? false,
              }
            : null,
        }));
        sendJs(`window.SM && SM.setReports(${JSON.stringify(payload)})`);
      }
    } catch {
      /* ignore */
    }
  };

  // Web-only: handle iframe postMessage events. Hook always runs; effect is a no-op on native.
  useEffect(() => {
    if (Platform.OS !== "web") return;
    function onMsg(e: MessageEvent) {
      if (typeof e.data === "string") handleMessage(e.data);
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reports, userLocation, onMarkerPress, onMapMoved]);

  if (Platform.OS === "web") {
    return (
      <View style={styles.flex} testID="marine-map-web">
        {/* eslint-disable-next-line react/no-unknown-property */}
        <iframe
          ref={iframeRef}
          srcDoc={html}
          style={{ border: "none", width: "100%", height: "100%", background: "#0B132B" }}
          title="map"
        />
      </View>
    );
  }

  return (
    <View ref={containerRef} style={styles.flex} collapsable={false} testID="marine-map-native">
      <WebView
        ref={webRef}
        originWhitelist={["*"]}
        source={{ html }}
        style={styles.flex}
        onMessage={(e: WebViewMessageEvent) => handleMessage(e.nativeEvent.data)}
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        androidLayerType="hardware"
      />
    </View>
  );
});

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: "#0B132B" },
});
