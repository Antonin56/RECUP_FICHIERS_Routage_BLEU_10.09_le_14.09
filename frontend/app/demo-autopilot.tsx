// SignalMar — Démo autopilote (~90 s), 100 % pilotée par la PROXIMITÉ.
//
// Aucune alerte scriptée au chronomètre : à chaque tick on mesure la distance
// bateau ↔ signalement et l'alerte (bannière + TTS voix femme + vibreur via
// playAlertVoice) part À L'INSTANT où l'objet entre dans le périmètre radar
// (Vigie, 360°) ou dans le cône d'alerte avant (Navigation).
//
// Séquence (vitesses réelles, AUCUN accéléré) :
//   1. 0-18 s  : bateau à l'arrêt en Vigie (radar 1 km, zoom 15).
//                t≈7 s : un OFNI est PUBLIÉ à 550 m → alerte immédiate.
//   2. 18-22 s : le bateau accélère → BASCULE AUTOMATIQUE en Navigation.
//   3. 22-52 s : croisière 20 nds cap 225. t≈30 s : une gendarmerie est
//                publiée dans le cône → alerte immédiate. t≈45 s : le bateau
//                ENTRE dans le rayon du mammifère mort (pré-existant, cône de
//                dérive) → alerte immédiate.
//   4. 52-56 s : le bateau ralentit → RETOUR AUTOMATIQUE en Vigie.
//   5. 56-78 s : mouillage. t≈63 s : pollution publiée à 600 m → alerte.
//   6. 78 s    : overlay CTA (Créer un compte / Rejouer / Retour).
//
// Chaque alerte affiche un bouton OK qui coupe immédiatement le son + le
// vibreur (stopAlertVoice) et rend la bannière de phase.

import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { MarineMap, type MarineMapHandle } from "@/src/components/MarineMap";
import { type ReportAlertInput } from "@/src/lib/voice-alerts";
import { vibrateAlert, stopAlertFeedback } from "@/src/lib/alert-vibration";
import { playAlertHorn, stopAlertHorn } from "@/src/lib/alert-sound";
import { theme } from "@/src/lib/theme";
import type { ReportItem } from "@/src/api/client";

// ─── Géo helpers ───────────────────────────────────────────────────────────
function bearingDeg(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const p1 = toRad(lat1);
  const p2 = toRad(lat2);
  const dl = toRad(lng2 - lng1);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}
function destPoint(lat: number, lng: number, brg: number, km: number): { lat: number; lng: number } {
  const R = 6371;
  const br = (brg * Math.PI) / 180;
  const la1 = (lat * Math.PI) / 180;
  const lo1 = (lng * Math.PI) / 180;
  const dr = km / R;
  const la2 = Math.asin(Math.sin(la1) * Math.cos(dr) + Math.cos(la1) * Math.sin(dr) * Math.cos(br));
  const lo2 = lo1 + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(la1), Math.cos(dr) - Math.sin(la1) * Math.sin(la2));
  return { lat: (la2 * 180) / Math.PI, lng: (lo2 * 180) / Math.PI };
}
function distanceM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const a =
    Math.sin(toRad(lat2 - lat1) / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(toRad(lng2 - lng1) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(a));
}

// ─── Cinématique (vitesses réelles, pas d'accéléré) ────────────────────────
const W0 = { lat: 47.545, lng: -2.921 };   // mouillage — sortie du Golfe
const HEADING = 225;                        // cap vers Belle-Île
const CRUISE_MS = 10.3;                     // ≈ 20 nds
const T_ACCEL = 18;   // début accélération (bascule auto → Navigation)
const T_CRUISE = 22;  // vitesse de croisière atteinte
const T_DECEL = 52;   // début ralentissement (bascule auto → Vigie)
const T_STOP = 56;    // à l'arrêt
const T_CTA = 78;
const T_TOTAL = 90;
const RADAR_M = 1000;      // périmètre Vigie (360°)
// Cône Navigation — MÊME géométrie que l'app réelle (MarineMap + watcher) :
// évasement triangulaire de 1 km (± demi-angle), puis corridor parallèle de
// largeur 2 × 1 km × sin(demi-angle), jusqu'à la distance totale.
const CONE_HALF_DEG = 15;  // évasement total 30°
const CONE_DIST_KM = 5;    // portée du corridor
const FLARE_KM = 1.0;      // profondeur de l'évasement (constante app réelle)
const ZOOM_VIGIE = 15;
const ZOOM_NAV = 13;       // dézoomé pour voir le corridor de 5 km entier

function distAt(t: number): number {
  if (t <= T_ACCEL) return 0;
  if (t <= T_CRUISE) {
    const dt = t - T_ACCEL;
    return (CRUISE_MS / (2 * (T_CRUISE - T_ACCEL))) * dt * dt; // rampe linéaire
  }
  const dAccel = (CRUISE_MS * (T_CRUISE - T_ACCEL)) / 2;
  if (t <= T_DECEL) return dAccel + CRUISE_MS * (t - T_CRUISE);
  const dCruise = dAccel + CRUISE_MS * (T_DECEL - T_CRUISE);
  if (t <= T_STOP) {
    const dt = t - T_DECEL;
    const dur = T_STOP - T_DECEL;
    return dCruise + CRUISE_MS * dt - (CRUISE_MS / (2 * dur)) * dt * dt;
  }
  return dCruise + (CRUISE_MS * (T_STOP - T_DECEL)) / 2;
}
function speedAt(t: number): number {
  if (t <= T_ACCEL) return 0;
  if (t <= T_CRUISE) return (CRUISE_MS * (t - T_ACCEL)) / (T_CRUISE - T_ACCEL);
  if (t <= T_DECEL) return CRUISE_MS;
  if (t <= T_STOP) return CRUISE_MS * (1 - (t - T_DECEL) / (T_STOP - T_DECEL));
  return 0;
}
const END_POS = destPoint(W0.lat, W0.lng, HEADING, distAt(T_STOP) / 1000);

// ─── Signalements de la scène ───────────────────────────────────────────────
const DEMO_AUTHOR = {
  user_id: "demo", pseudo: "SignalMar", name: "SignalMar",
  rank_id: "maitre", rank_label: "Maître", reliability_score: 82,
};

function buildDemoCone(lat: number, lng: number, brg: number, km: number, halfDeg: number) {
  const pts = [{ lat, lng }];
  for (let s = 0; s <= 7; s++) {
    pts.push(destPoint(lat, lng, brg - halfDeg + (2 * halfDeg * s) / 7, km));
  }
  return { polygon: pts, distance_km: km };
}

const P_OFNI = destPoint(W0.lat, W0.lng, 315, 0.55);         // publié t≈7 (Vigie)
const _pGend = destPoint(W0.lat, W0.lng, HEADING, 0.703);
const P_GEND = destPoint(_pGend.lat, _pGend.lng, 315, 0.08); // publié t≈30 (Nav, dans le corridor)
// Mammifère PRÉ-EXISTANT placé juste AU-DELÀ du bout du corridor (5,25 km
// pour un corridor de 5 km) : grisé à 30 % au début de la Navigation, il
// « s'allume » et déclenche l'alerte À L'INSTANT où le corridor l'atteint
// (boat a parcouru ~250 m → t≈45 s).
const _pDolp = destPoint(W0.lat, W0.lng, HEADING, 5.25);
const P_DOLP = destPoint(_pDolp.lat, _pDolp.lng, 135, 0.08);
const P_POLL = destPoint(END_POS.lat, END_POS.lng, 200, 0.6); // publié t≈63 (Vigie 2)

/** Test corridor — réplique EXACTE de la géométrie du watcher de l'app
 *  réelle (voice-alert-watcher.ts) : évasement 1 km puis bande parallèle. */
function isInCorridor(
  boatLat: number, boatLng: number, heading: number,
  lat: number, lng: number,
): boolean {
  const dKm = distanceM(boatLat, boatLng, lat, lng) / 1000;
  if (dKm > CONE_DIST_KM) return false;
  const brg = bearingDeg(boatLat, boatLng, lat, lng);
  const diff = ((brg - heading + 540) % 360) - 180;
  const absDiff = Math.abs(diff);
  if (absDiff >= 90) return false;
  const halfRad = (CONE_HALF_DEG * Math.PI) / 180;
  const diffRad = (diff * Math.PI) / 180;
  const alongKm = dKm * Math.cos(diffRad);
  const perpKm = Math.abs(dKm * Math.sin(diffRad));
  if (alongKm < 0 || alongKm > CONE_DIST_KM) return false;
  const alongFlareEnd = FLARE_KM * Math.cos(halfRad);
  if (alongKm <= alongFlareEnd) return absDiff <= CONE_HALF_DEG;
  return perpKm <= FLARE_KM * Math.sin(halfRad);
}

type SceneReport = {
  report: ReportItem;
  /** Instant de PUBLICATION (apparition sur la carte). 0 = présent dès le début. */
  spawnT: number;
  /** Contenu vocal / bannière quand la proximité déclenche l'alerte. */
  input?: ReportAlertInput;
  customTts?: string;
  banner: string;
  color: string;
  icon: keyof typeof Ionicons.glyphMap;
};

const SCENE: SceneReport[] = [
  {
    spawnT: 7,
    report: { id: "demo_ofni", type: "obstacle_nav", subtype: "ofni", lat: P_OFNI.lat, lng: P_OFNI.lng, description: "OFNI semi-immergé", author: DEMO_AUTHOR } as unknown as ReportItem,
    input: { type: "obstacle_nav", subtype: "ofni" },
    banner: "⚠️ OFNI publié dans votre périmètre — 550 m", color: "#F4A261", icon: "warning",
  },
  {
    spawnT: 30,
    report: {
      id: "demo_gendarmerie", type: "autorites", subtype: "gendarmerie_maritime",
      lat: P_GEND.lat, lng: P_GEND.lng, description: "Vedette Gendarmerie maritime",
      activity: "navigation", heading: 120, speed_knots: 9, author: DEMO_AUTHOR,
    } as unknown as ReportItem,
    input: { type: "autorites", subtype: "gendarmerie_maritime" },
    banner: "🛡️ Gendarmerie maritime droit devant", color: "#48CAE4", icon: "shield-checkmark",
  },
  {
    spawnT: 0,
    report: {
      id: "demo_dauphin", type: "animal_marin", subtype: "mammifere",
      lat: P_DOLP.lat, lng: P_DOLP.lng, description: "Dauphin commun mort",
      extras: { health: "dead_unmarked" }, author: DEMO_AUTHOR,
      drift_cone: buildDemoCone(P_DOLP.lat, P_DOLP.lng, 240, 0.35, 22),
    } as unknown as ReportItem,
    input: { type: "animal_marin", subtype: "mammifere", health: "dead_unmarked" },
    banner: "🐬 Mammifère marin mort — il entre dans votre corridor", color: "#2A9D8F", icon: "navigate",
  },
  {
    spawnT: 63,
    report: { id: "demo_pollution", type: "pollution", subtype: "pollution_locale", lat: P_POLL.lat, lng: P_POLL.lng, description: "Irisation localisée", author: DEMO_AUTHOR } as unknown as ReportItem,
    customTts: "Attention, pollution signalée dans votre périmètre d'alerte.",
    banner: "🛢️ Pollution publiée dans votre périmètre — 600 m", color: "#9D4CDD", icon: "alert-circle",
  },
];

// ─── Bannières de phase (bascules AUTO mises en avant) ─────────────────────
function phaseBanner(t: number): { text: string; color: string; icon: keyof typeof Ionicons.glyphMap } {
  if (t < T_ACCEL) return { text: "Mode Vigie — veille 360° · bateau à l'arrêt", color: "#E63946", icon: "radio" };
  if (t < T_CRUISE) return { text: "Le bateau accélère → bascule auto en Navigation", color: "#F4A261", icon: "swap-horizontal" };
  if (t < T_DECEL) return { text: "Navigation — cap 225 · 20 nds · corridor 5 km / 30°", color: "#F4A261", icon: "boat" };
  if (t < T_STOP) return { text: "Le bateau ralentit → retour auto en Vigie", color: "#E63946", icon: "swap-horizontal" };
  return { text: "Mode Vigie — veille 360° au mouillage", color: "#E63946", icon: "radio" };
}

const ALERT_HOLD_S = 9;

type ActiveAlert = { sr: SceneReport; at: number; stopped: boolean };

export default function DemoAutopilot() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const mapRef = useRef<MarineMapHandle | null>(null);

  const [elapsed, setElapsed] = useState(0);
  const [boat, setBoat] = useState({ lat: W0.lat, lng: W0.lng, heading: HEADING as number | null, speed: 0 });
  const [visibleReports, setVisibleReports] = useState<ReportItem[]>(
    SCENE.filter((s) => s.spawnT === 0).map((s) => s.report),
  );
  const [alert, setAlert] = useState<ActiveAlert | null>(null);
  const [muted, setMuted] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const mutedRef = useRef(muted);
  mutedRef.current = muted;
  const firedRef = useRef<Set<string>>(new Set());
  const spawnedRef = useRef<Set<string>>(new Set(SCENE.filter((s) => s.spawnT === 0).map((s) => s.report.id)));
  const navModeRef = useRef(false);
  const startRef = useRef(Date.now());
  const lastPingPushRef = useRef(0);

  const fireAlert = useCallback((sr: SceneReport, t: number, speed: number) => {
    firedRef.current.add(sr.report.id);
    setAlert({ sr, at: t, stopped: false });
    setFocusId(sr.report.id);
    // 14/07/2026 — corne de brume fournie par l'armateur + vibration.
    if (!mutedRef.current) { playAlertHorn(); vibrateAlert(); }
  }, []);

  // ─── Tick 200 ms : cinématique + spawns + PROXIMITÉ ──────────────────────
  useEffect(() => {
    const iv = setInterval(() => {
      const t = (Date.now() - startRef.current) / 1000;
      setElapsed(t);

      // Position / vitesse réelles.
      const d = distAt(t);
      const sp = speedAt(t);
      const pos = d > 0 ? destPoint(W0.lat, W0.lng, HEADING, d / 1000) : W0;
      setBoat({ lat: pos.lat, lng: pos.lng, heading: HEADING, speed: sp });

      // Bascule AUTO Vigie ↔ Navigation (pilotée par la vitesse, comme l'app).
      const nav = sp >= 0.833; // 3 km/h — même seuil que l'app réelle
      if (nav !== navModeRef.current) {
        navModeRef.current = nav;
        if (nav) {
          // Zoom instantané AVANT le follow-mode : dézoomé pour voir le
          // corridor de 5 km en entier (le recentrage périodique du
          // follow-mode annulerait un zoom animé).
          mapRef.current?.setZoom(ZOOM_NAV);
          mapRef.current?.setNavMode(true);
        } else {
          mapRef.current?.setNavMode(false);
          mapRef.current?.flyTo(pos.lat, pos.lng, ZOOM_VIGIE);
        }
      }

      // Radar Vigie — ré-émis chaque seconde (auto-réparation : garantit que
      // les cercles rouges sont TOUJOURS visibles à l'arrêt, y compris après
      // un replay ou une course d'initialisation de la WebView).
      if (!nav && t - lastPingPushRef.current >= 1) {
        lastPingPushRef.current = t;
        mapRef.current?.setRadarPing(RADAR_M);
      }

      // Publications de signalements (apparition sur la carte).
      for (const sr of SCENE) {
        if (sr.spawnT > 0 && t >= sr.spawnT && !spawnedRef.current.has(sr.report.id)) {
          spawnedRef.current.add(sr.report.id);
          setVisibleReports((prev) => [...prev, sr.report]);
        }
      }

      // ★ PROXIMITÉ — l'alerte part À L'INSTANT où l'objet est dans le
      // périmètre : rayon 360° en Vigie, corridor (évasement + bande) en
      // Navigation — même géométrie que l'app réelle, donc synchronisée
      // avec le grisé/dégrisé visuel des marqueurs.
      for (const sr of SCENE) {
        if (!spawnedRef.current.has(sr.report.id) || firedRef.current.has(sr.report.id)) continue;
        let inside = false;
        if (!nav) {
          inside = distanceM(pos.lat, pos.lng, sr.report.lat, sr.report.lng) <= RADAR_M;
        } else {
          inside = isInCorridor(pos.lat, pos.lng, HEADING, sr.report.lat, sr.report.lng);
        }
        if (inside) fireAlert(sr, t, sp);
      }

      if (t >= T_CTA) setDone(true);
    }, 200);
    return () => clearInterval(iv);
  }, [fireAlert]);

  // Expiration douce de la bannière d'alerte (sans interaction). Une alerte
  // STOPPÉE reste en pastille persistante (réactivable) jusqu'à la
  // prochaine alerte ou sa fermeture explicite.
  useEffect(() => {
    if (!alert || alert.stopped) return;
    if (elapsed - alert.at > ALERT_HOLD_S) {
      setAlert(null);
      setFocusId(null);
    }
  }, [elapsed, alert]);

  // Coupure du son + vibreur à la sortie de l'écran.
  useEffect(() => () => {
    try { stopAlertHorn(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
  }, []);

  // Stop = réduit l'alerte en pastille persistante (clic par mégarde → on
  // peut la réactiver). Son + vibreur coupés immédiatement.
  const stopAlert = useCallback(() => {
    try { stopAlertHorn(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
    setAlert((a) => (a ? { ...a, stopped: true } : null));
    setFocusId(null);
  }, []);

  const reactivateAlert = useCallback(() => {
    setAlert((a) => {
      if (!a) return null;
      if (!mutedRef.current) { playAlertHorn(); vibrateAlert(); }
      setFocusId(a.sr.report.id);
      return { ...a, stopped: false, at: (Date.now() - startRef.current) / 1000 };
    });
  }, []);

  const closeAlert = useCallback(() => {
    try { stopAlertHorn(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
    setAlert(null);
    setFocusId(null);
  }, []);

  const replay = useCallback(() => {
    try { stopAlertHorn(); } catch { /* noop */ }
    try { stopAlertFeedback(); } catch { /* noop */ }
    firedRef.current = new Set();
    spawnedRef.current = new Set(SCENE.filter((s) => s.spawnT === 0).map((s) => s.report.id));
    navModeRef.current = false;
    lastPingPushRef.current = 0;
    mapRef.current?.setNavMode(false);
    mapRef.current?.flyTo(W0.lat, W0.lng, ZOOM_VIGIE);
    mapRef.current?.setRadarPing(RADAR_M);
    startRef.current = Date.now();
    setVisibleReports(SCENE.filter((s) => s.spawnT === 0).map((s) => s.report));
    setAlert(null);
    setFocusId(null);
    setDone(false);
    setElapsed(0);
  }, []);

  const nav = boat.speed >= 0.833;
  const showAlertBanner = !!alert && !alert.stopped;
  const banner = showAlertBanner
    ? { text: alert!.sr.banner, color: alert!.sr.color, icon: alert!.sr.icon }
    : phaseBanner(elapsed);
  const progress = Math.min(1, elapsed / T_TOTAL);

  return (
    <View style={styles.root}>
      <MarineMap
        ref={mapRef}
        center={W0}
        zoom={ZOOM_VIGIE}
        userLocation={{ lat: boat.lat, lng: boat.lng }}
        userHeading={boat.heading}
        userSpeed={boat.speed}
        showBoat
        coneHalfAngleDeg={nav ? CONE_HALF_DEG : null}
        coneDistanceKm={nav ? CONE_DIST_KM : null}
        radarPingRadiusM={!nav ? RADAR_M : null}
        courseUp={nav}
        reports={visibleReports}
        focusId={focusId}
      />

      {/* ─── Barre du haut : fermer / titre / mute ─── */}
      <View style={[styles.topBar, { top: insets.top + 8 }]}>
        <TouchableOpacity style={styles.roundBtn} onPress={() => router.back()} testID="demo-close">
          <Ionicons name="close" size={22} color={theme.text} />
        </TouchableOpacity>
        <View style={styles.titlePill}>
          <Ionicons name="play" size={12} color={theme.primary} />
          <Text style={styles.titleText}>Démo SignalMar</Text>
        </View>
        <TouchableOpacity
          style={[styles.roundBtn, muted && styles.roundBtnMuted]}
          onPress={() => setMuted((m) => {
            if (!m) { try { stopAlertHorn(); stopAlertFeedback(); } catch { /* noop */ } }
            return !m;
          })}
          testID="demo-mute"
        >
          <Ionicons name={muted ? "volume-mute" : "volume-high"} size={20} color={muted ? "#E63946" : theme.text} />
        </TouchableOpacity>
      </View>

      {/* ─── Bannière phase / alerte (+ Stop qui réduit en pastille) ─── */}
      <View style={[styles.banner, { top: insets.top + 64, borderColor: banner.color }]}>
        <Ionicons name={banner.icon} size={18} color={banner.color} />
        <Text style={[styles.bannerText, showAlertBanner && { color: banner.color }]} numberOfLines={2}>
          {banner.text}
        </Text>
        {showAlertBanner && (
          <TouchableOpacity
            style={[styles.okBtn, { backgroundColor: banner.color }]}
            onPress={stopAlert}
            testID="demo-alert-ok"
          >
            <Ionicons name="stop-circle" size={15} color={theme.bg} />
            <Text style={styles.okText}>Stop</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* ─── Alerte stoppée → pastille persistante réactivable ─── */}
      {alert?.stopped && (
        <View style={[styles.stoppedPill, { top: insets.top + 122, borderColor: alert.sr.color }]}>
          <Ionicons name={alert.sr.icon} size={14} color={alert.sr.color} />
          <Text style={styles.stoppedPillText} numberOfLines={1}>Alerte stoppée</Text>
          <TouchableOpacity
            style={[styles.reactivateBtn, { backgroundColor: alert.sr.color }]}
            onPress={reactivateAlert}
            testID="demo-alert-reactivate"
          >
            <Ionicons name="notifications" size={13} color={theme.bg} />
            <Text style={styles.reactivateText}>Réactiver</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.pillClose} onPress={closeAlert} testID="demo-alert-close">
            <Ionicons name="close" size={16} color={theme.textMute} />
          </TouchableOpacity>
        </View>
      )}

      {/* ─── Barre de progression ─── */}
      <View style={[styles.progressWrap, { bottom: insets.bottom + 16 }]}>
        <View style={[styles.progressFill, { width: `${Math.round(progress * 100)}%` }]} />
      </View>

      {/* ─── Overlay final CTA ─── */}
      {done && (
        <View style={styles.ctaOverlay}>
          <View style={styles.ctaCard}>
            <Text style={styles.ctaTitle}>⚓ Prêt à embarquer ?</Text>
            <Text style={styles.ctaSub}>
              Rejoignez la communauté SignalMar : alertes en temps réel, signalements en 3 taps, veille collaborative.
            </Text>
            <TouchableOpacity
              style={styles.ctaPrimary}
              onPress={() => router.replace("/(auth)/login")}
              testID="demo-cta-register"
            >
              <Ionicons name="person-add" size={18} color={theme.bg} />
              <Text style={styles.ctaPrimaryText}>Créer un compte</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.ctaSecondary} onPress={replay} testID="demo-cta-replay">
              <Ionicons name="refresh" size={16} color={theme.primary} />
              <Text style={styles.ctaSecondaryText}>Revoir la démo</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.ctaGhost} onPress={() => router.back()} testID="demo-cta-back">
              <Text style={styles.ctaGhostText}>Retour</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  topBar: {
    position: "absolute", left: 12, right: 12,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    zIndex: 20,
  },
  roundBtn: {
    width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(11,19,43,0.9)", borderWidth: 1, borderColor: theme.border,
  },
  roundBtnMuted: { borderColor: "#E63946" },
  titlePill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(11,19,43,0.9)", borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20,
  },
  titleText: { color: theme.text, fontWeight: "800", fontSize: 13 },
  banner: {
    position: "absolute", left: 12, right: 12, zIndex: 15,
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "rgba(11,19,43,0.92)", borderWidth: 1.5,
    paddingHorizontal: 14, paddingVertical: 12, borderRadius: 14,
  },
  bannerText: { color: theme.text, fontWeight: "700", fontSize: 13, flex: 1, lineHeight: 18 },
  okBtn: {
    paddingHorizontal: 14, paddingVertical: 9, borderRadius: 10,
    minWidth: 48, minHeight: 36, alignItems: "center", justifyContent: "center",
    flexDirection: "row", gap: 5,
  },
  okText: { color: theme.bg, fontWeight: "900", fontSize: 14 },
  stoppedPill: {
    position: "absolute", left: 12, zIndex: 14,
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(11,19,43,0.92)", borderWidth: 1,
    paddingLeft: 12, paddingRight: 6, paddingVertical: 7, borderRadius: 20,
  },
  stoppedPillText: { color: theme.textMute, fontWeight: "700", fontSize: 12 },
  reactivateBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 7, borderRadius: 14, minHeight: 30,
  },
  reactivateText: { color: theme.bg, fontWeight: "900", fontSize: 12 },
  pillClose: { padding: 6 },
  progressWrap: {
    position: "absolute", left: 16, right: 16, height: 5, borderRadius: 3,
    backgroundColor: "rgba(255,255,255,0.18)", overflow: "hidden", zIndex: 15,
  },
  progressFill: { height: "100%", backgroundColor: theme.primary, borderRadius: 3 },
  ctaOverlay: {
    ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(11,19,43,0.82)",
    alignItems: "center", justifyContent: "center", zIndex: 30, padding: 24,
  },
  ctaCard: {
    width: "100%", maxWidth: 380, backgroundColor: theme.bg2, borderRadius: 20,
    borderWidth: 1, borderColor: theme.border, padding: 24, gap: 12,
  },
  ctaTitle: { color: theme.text, fontWeight: "900", fontSize: 22, textAlign: "center" },
  ctaSub: { color: theme.textMute, fontSize: 13, textAlign: "center", lineHeight: 19, marginBottom: 6 },
  ctaPrimary: {
    backgroundColor: theme.primary, paddingVertical: 15, borderRadius: 14,
    alignItems: "center", flexDirection: "row", justifyContent: "center", gap: 8, minHeight: 52,
  },
  ctaPrimaryText: { color: theme.bg, fontWeight: "900", fontSize: 16 },
  ctaSecondary: {
    paddingVertical: 13, borderRadius: 14, alignItems: "center", flexDirection: "row",
    justifyContent: "center", gap: 6, borderWidth: 1, borderColor: theme.primary, minHeight: 48,
  },
  ctaSecondaryText: { color: theme.primary, fontWeight: "800", fontSize: 14 },
  ctaGhost: { paddingVertical: 10, alignItems: "center" },
  ctaGhostText: { color: theme.textMute, fontWeight: "600", fontSize: 13 },
});
