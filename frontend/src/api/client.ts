import { storage } from "@/src/utils/storage";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
export const TOKEN_KEY = "signmar.token";

async function authHeader(): Promise<Record<string, string>> {
  const tok = await storage.secureGet<string>(TOKEN_KEY, "");
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

type Json = unknown;

// ── 02/08/2026 (armateur : « erreur 429 quasi à chaque calcul de route près
// des côtes ») — PORTIER DE REQUÊTES.
// Diagnostic : l'ingress de la plateforme limite les requêtes SIMULTANÉES par
// IP. Un calcul côtier occupe une connexion plusieurs secondes ; pendant ce
// temps la WebView charge ses tuiles et l'app interroge signalements /
// cloche / marées → la limite est franchie → 429 sur le calcul lui-même
// (départ de route perdu) et bascule « hors-ligne » à tort.
// Deux garde-fous, sans rien changer aux API :
//   1. au plus MAX_INFLIGHT requêtes app en vol ;
//   2. pendant un calcul de route (priorité 2), les requêtes de FOND
//      (priorité 0 : signalements, cloche, marées, version…) patientent.
const MAX_INFLIGHT = 3;
/** Un fond ne patiente jamais plus longtemps que ça (anti-blocage). */
const BG_MAX_WAIT_MS = 12_000;

let inflight = 0;
let priorityMode = 0;
type Waiter = { prio: number; taken: boolean; resume: () => void };
const waiters: Waiter[] = [];

function pump(): void {
  while (inflight < MAX_INFLIGHT && waiters.length) {
    waiters.sort((a, b) => b.prio - a.prio);
    const next = waiters[0];
    // Un calcul de route est en cours : le trafic de fond attend son tour.
    if (priorityMode > 0 && next.prio === 0) break;
    waiters.shift();
    if (next.taken) continue;
    next.taken = true;
    inflight++;
    next.resume();
  }
}

function priorityOf(path: string, method: string): number {
  if (
    path.startsWith("/routes/compute") ||
    path.startsWith("/routes/manual") ||
    path.includes("/recompute") ||
    // 02/08/2026 (armateur : « support screenshot failed 429 » dans ses logs)
    // — les ENVOIS AU SUPPORT (capture carte, logs, vidéo) sont la seule
    // façon de diagnostiquer un problème en mer : ils passent AVANT le
    // trafic de fond, comme un calcul de route.
    path.startsWith("/support/") ||
    path.startsWith("/diagnostics")
  ) return 2;
  if (
    method === "GET" &&
    (path.startsWith("/reports") ||
      path.startsWith("/notifications") ||
      path.startsWith("/tides") ||
      path.startsWith("/app/version") ||
      path.startsWith("/friends") ||
      path.startsWith("/groups"))
  ) return 0;
  return 1;
}

async function acquire(prio: number): Promise<boolean> {
  if (inflight < MAX_INFLIGHT && !(priorityMode > 0 && prio === 0)) {
    inflight++;
    return true;
  }
  return new Promise<boolean>((resolve) => {
    const w: Waiter = { prio, taken: false, resume: () => resolve(true) };
    waiters.push(w);
    if (prio === 0) {
      setTimeout(() => {
        if (w.taken) return;
        w.taken = true;
        const i = waiters.indexOf(w);
        if (i >= 0) waiters.splice(i, 1);
        // Départ « hors quota » : on ne bloque jamais indéfiniment le fond.
        resolve(false);
      }, BG_MAX_WAIT_MS);
    }
  });
}

function release(counted: boolean): void {
  if (counted) inflight = Math.max(0, inflight - 1);
  pump();
}

async function request<T = Json>(
  path: string,
  options: { method?: string; body?: unknown; auth?: boolean } = {},
): Promise<T> {
  const { method = "GET" } = options;
  const prio = priorityOf(path, method);
  const counted = await acquire(prio);
  if (prio === 2) priorityMode++;
  try {
    return await requestRaw<T>(path, options);
  } finally {
    if (prio === 2) priorityMode = Math.max(0, priorityMode - 1);
    release(counted);
  }
}

async function requestRaw<T = Json>(
  path: string,
  options: { method?: string; body?: unknown; auth?: boolean } = {},
): Promise<T> {
  const { method = "GET", body, auth = true } = options;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) Object.assign(headers, await authHeader());
  // 23/07/2026 (vidéos armateur, « Erreur 429 » fréquentes) — l'ingress de la
  // plateforme limite les RAFALES par IP (tuiles + polling simultanés) : les
  // GET (idempotents) sont réessayés avec backoff sur 429/502/503/504 au
  // lieu d'échouer immédiatement (ce qui basculait l'app « hors-ligne » et
  // cassait l'ouverture des signalements).
  // 27/07 — les calculs de route (POST idempotents, aucune écriture) sont
  // aussi réessayés : un 429 d'ingress pendant une rafale de tuiles faisait
  // échouer le calcul avec une simple « Erreur 429 ».
  // 02/08/2026 — 4 tentatives (0,6 / 1,6 / 3,2 / 6 s) + respect de l'en-tête
  // « Retry-After » : le sas de l'ingress dure quelques secondes, il faut
  // simplement l'attendre au lieu de perdre le calcul (et le point de départ).
  // 02/08/2026 (logs armateur : 3 captures perdues sur 6 avec « status 429 »)
  // — les envois au support sont AUSSI réessayés : un 429 de l'ingress
  // pendant une rafale de tuiles faisait perdre la capture d'écran (et donc
  // la preuve du bug). Au pire une capture arrive en double, ce qui est sans
  // conséquence ; la perdre, si.
  const retriable =
    method === "GET" ||
    path.startsWith("/routes/compute") ||
    path.startsWith("/routes/manual") ||
    path.includes("/recompute") ||
    path.startsWith("/support/") ||
    path.startsWith("/diagnostics");
  const BACKOFF_MS = [600, 1600, 3200, 6000];
  let res: Response;
  for (let attempt = 0; ; attempt++) {
    res = await fetch(`${BASE}/api${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (
      retriable &&
      attempt < BACKOFF_MS.length &&
      (res.status === 429 || res.status === 502 || res.status === 503 || res.status === 504)
    ) {
      const ra = Number(res.headers.get("Retry-After") ?? "");
      const wait = Number.isFinite(ra) && ra > 0
        ? Math.min(ra * 1000, 8000)
        : BACKOFF_MS[attempt];
      await new Promise((r) => setTimeout(r, wait));
      continue;
    }
    break;
  }
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* keep raw text */
  }
  if (!res.ok) {
    const d = (data as { detail?: unknown } | null)?.detail;
    const msg =
      typeof d === "string"
        ? d
        : (d as { message?: string } | null)?.message || `Erreur ${res.status}`;
    // 23/07/2026 (bug armateur « je ne vois pas la zone sur la carte ») — le
    // détail STRUCTURÉ du 422 (code, blocked_at, partial_waypoints…) était
    // PERDU ici : la carte ne pouvait jamais afficher le point de blocage.
    const err = new Error(msg) as Error & { detail?: unknown; status?: number };
    if (d && typeof d === "object") err.detail = d;
    err.status = res.status;
    throw err;
  }
  return data as T;
}

// ── 02/08/2026 (armateur : 429 pendant les calculs de route côtiers) ───────
// CALCUL EN TÂCHE DE FOND : le serveur rend un `job_id` immédiatement, on
// interroge ensuite un GET très court. Aucune connexion n'est retenue 10-20 s,
// donc plus de 429 sur le calcul ; et si une interrogation échoue quand même,
// le calcul CONTINUE côté serveur : on le récupère au coup suivant (le point
// de départ n'est jamais perdu).
type JobReply<T> =
  | { status: "pending" }
  | { status: "done"; result: T }
  | { status: "error"; status_code?: number; detail?: unknown };

const JOB_MAX_MS = 240_000;

/** 08/09/2026 (remise à plat armateur) — ARRÊT DU CALCUL : jeton passé au
 *  polling ; `cancelled = true` → on cesse d'interroger et on rend la main
 *  immédiatement (le serveur termine son job dans son coin, sans effet). */
export type CancelToken = { cancelled: boolean };

/** Cadence d'interrogation : rapide au début (routes du Golfe = ~1 s), plus
 *  espacée ensuite (route côtière longue distance = 10-20 s). */
function jobPollDelay(i: number): number {
  if (i === 0) return 350;
  if (i < 4) return 700;
  return 1000;
}

async function runAsJob<T>(startPath: string, body: unknown, cancel?: CancelToken): Promise<T> {
  const started = await request<{ job_id: string }>(startPath, { method: "POST", body });
  const t0 = Date.now();
  let misses = 0;
  for (let i = 0; Date.now() - t0 < JOB_MAX_MS; i++) {
    if (cancel?.cancelled) {
      const err = new Error("Calcul arrêté.") as Error & { cancelled?: boolean };
      err.cancelled = true;
      throw err;
    }
    await new Promise((r) => setTimeout(r, jobPollDelay(i)));
    if (cancel?.cancelled) {
      const err = new Error("Calcul arrêté.") as Error & { cancelled?: boolean };
      err.cancelled = true;
      throw err;
    }
    let rep: JobReply<T>;
    try {
      rep = await request<JobReply<T>>(`/routes/job/${started.job_id}`);
    } catch (e) {
      // 404 = job purgé (redémarrage serveur) → inutile d'insister.
      if ((e as { status?: number }).status === 404) throw e;
      // Réseau/429 : le calcul continue côté serveur, on retentera.
      if (++misses > 25) throw e;
      continue;
    }
    misses = 0;
    if (rep.status === "done") return rep.result;
    if (rep.status === "error") {
      const d = rep.detail;
      const msg =
        typeof d === "string"
          ? d
          : (d as { message?: string } | null)?.message || `Erreur ${rep.status_code ?? 422}`;
      const err = new Error(msg) as Error & { detail?: unknown; status?: number };
      if (d && typeof d === "object") err.detail = d;
      err.status = rep.status_code ?? 422;
      throw err;
    }
  }
  const err = new Error("Calcul trop long — réessayez.") as Error & { status?: number };
  err.status = 504;
  throw err;
}


// ── V2 N1 (20/07/2026) — Routage marin sûr ────────────────────────────────
export interface RouteWaypoint {
  lat: number;
  lng: number;
}
export interface RouteProfilePoint {
  d_m: number;
  lat: number;
  lng: number;
  depth_m: number | null;
}
export interface ComputedRoute {
  /** 08/09/2026 — temps de calcul EFFECTIF côté serveur (secondes). */
  compute_s?: number;
  /** 31/07/2026 — ID public de la route (support armateur). Format
   *  `R-YYYYMMDD-HHMMSS-XX`. Communiqué au support pour consultation. */
  route_id?: string;
  /** 01/08/2026 — Moteur qui a produit ce tracé (multi-engine A/B/…). */
  engine?: {
    id: string;
    name: string;
    algo: string;
    algo_version?: string | null;
  };
  waypoints: RouteWaypoint[];
  distance_m: number;
  min_depth_m: number | null;
  threshold_m: number;
  depth_profile: RouteProfilePoint[];
  warnings: string[];
  disclaimer: string;
  /** 22/07/2026 — destination non navigable : arrivée DÉPLACÉE vers l'eau
   *  saine atteignable la plus proche (pointillé + repère sur la carte). */
  end_snapped?: { requested: { lat: number; lng: number }; offset_m: number };
  /** 23/07 — marge latérale réellement utilisée si réduite (passages étroits). */
  lateral_margin_used_m?: number;
  /** 22/07/2026 — "auto" (A*) ou "manual" (waypoints utilisateur). */
  mode?: "auto" | "manual";
  /** 22/07 (GO armateur) — hauteur de marée intégrée au calcul (m ≈ / ZH). */
  tide_m?: number;
  tide?: {
    port: string;
    height_start_m: number;
    height_min_m: number;
    window_h: number;
    departure_ts: number;
  };
  /** 26/07 (GO armateur) — route passable UNIQUEMENT grâce à la marée :
   *  fenêtre de validité (hauteur requise + fin de la fenêtre courante). */
  tide_window?: { required_m: number; ok_until_ts: number | null; port: string };
  /** 26/07 — arrivée déplacée : la route ira PLUS LOIN à partir de ts. */
  tide_better?: { ts: number; required_m: number; offset_m: number; port: string };
  /** 22/07 — demi-largeur (m) du corridor dynamique par SEGMENT de route. */
  corridor_m?: number[];
  /** 24/07 — tronçons compromis (index de segment) : rouge + risque à accepter. */
  compromised_legs?: number[];
  /** 03/08/2026 (Moteur C — signalmar.v3) — MOTIF de chaque tronçon rouge :
   *  `{"12": "shallow" | "low_margin"}` (clé = index de segment, en texte). */
  leg_reasons?: Record<string, "shallow" | "low_margin">;
  /** 03/08 (Moteur C) — marge latérale MESURÉE (m) par tronçon. */
  leg_margin_m?: number[];
  /** 03/08 (Moteur C) — tronçons dont la marge mesurée est ≤ 20 m. */
  low_margin_legs?: number[];
  /** 03/08 (Moteur C) — balises dont le côté de passage a été CORRIGÉ. */
  side_fixed?: string[];
  /** 03/08 (Moteur C) — balises restées du MAUVAIS côté (aucun passage
   *  conforme trouvé) : à franchir à vue. */
  wrong_side_marks?: {
    name: string;
    kind?: "lateral" | "cardinal";
    category?: string;
    dist_m: number;
    side_required: string;
  }[];
  /** 03/08 (Moteur C) — cardinales dont le départ ou l'arrivée est DANS le
   *  secteur dangereux : il faut en sortir à vue. */
  endpoint_cardinals?: { name: string; dist_m: number; side_required: string }[];
  /** 03/08 (Moteur C) — sens conventionnel retenu pour le calcul. */
  engine_rules?: {
    conventional_direction: string;
    computed_reversed: boolean;
    sea_end: RouteWaypoint;
    land_end: RouteWaypoint;
  };
  /** 03/08 (Moteur C) — départ déplacé (l'arrivée du calcul conventionnel). */
  start_snapped?: { requested: RouteWaypoint; offset_m: number };
  /** 24/07 — route « douteuse » (fallback auto ou manuelle avec rouge). */
  risk?: boolean;
  /** 25/07 — marge de sécurité FAIBLE (<150 % du besoin) sur le trajet. */
  low_margin?: {
    min_height_m: number;
    required_m: number;
    alert_at_m: number;
    safe_extra_m: number;
  };
}
/** 22/07/2026 — détail d'une erreur de routage (HTTP 422). */
export interface RouteErrorDetail {
  code?: string;
  message?: string;
  blocked_at?: RouteWaypoint;
  partial_waypoints?: RouteWaypoint[];
  /** 24/07 — route de secours « douteuse » : tronçon sûr + segment direct
   *  (rouge) jusqu'à destination, à afficher après acceptation du risque. */
  fallback_route?: {
    waypoints: RouteWaypoint[];
    compromised_from: number;
    distance_m: number;
  };
}
/** 22/07/2026 — route enregistrée (max 20/utilisateur). */
export interface SavedRoute {
  id: string;
  name: string;
  mode: "auto" | "manual";
  waypoints: RouteWaypoint[];
  distance_m: number;
  created_at: string;
  /** 01/08/2026 — Traçabilité multi-moteurs. */
  engine_id?: string | null;
  engine_name?: string | null;
  algo_id?: string | null;
  draft_m?: number | null;
  depth_margin_m?: number | null;
  lateral_margin_m?: number | null;
  source_route_id?: string | null;
  /** 27/08/2026 (demande armateur) — coordonnées EXACTES du départ et de
   *  l'arrivée, conservées à l'enregistrement. */
  start?: RouteWaypoint | null;
  end?: RouteWaypoint | null;
}

/** 01/08/2026 — Moteur de routage (profil nommé). Cf. backend
 *  `core.routing_engines.manager`. */
export interface RoutingEngine {
  id: string;
  name: string;
  description?: string | null;
  algo: string;
  params?: Record<string, unknown>;
  active: boolean;
  built_in: boolean;
  parent_id?: string | null;
  created_at?: string;
  updated_at?: string;
  usage_count?: number;
}
/** 22/07/2026 — objet cliquable : balise (seamark) ou danger (roche/épave/
 *  obstruction) OSM. */
export interface Seamark {
  id: number;
  lat: number;
  lng: number;
  kind: "lateral" | "cardinal" | "isolated_danger" | "special" | "safe_water" | "rock" | "wreck" | "obstruction";
  type: string;
  category: string;
  colour: string;
  name: string;
  light: string;
  /** Dangers uniquement : niveau d'eau OSM (covers/awash/submerged/dry…). */
  water_level?: string;
  /** Dangers uniquement : profondeur connue (m au zéro hydro) ou null. */
  depth_m?: number | null;
}

// ── Marées (20/07/2026, Open-Meteo approché) ──────────────────────────────
export interface TideEvent {
  type: "PM" | "BM";
  time: string;
  height_m: number;
  coef: number | null;
}
export interface TidesResponse {
  source: string;
  port: { id: string; name: string; lat: number; lng: number; distance_km: number };
  nearest_ports: { id: string; name: string; lat: number; lng: number; distance_km: number }[];
  days: { date: string; events: TideEvent[] }[];
}

export interface User {
  user_id: string;
  email: string;
  name: string;
  pseudo?: string;
  /** Honorary title (e.g. "Amiral Modérateur"). Distinct from the auto-rank. */
  title?: string | null;
  picture: string;
  provider: string;
  points: number;
  /** Legacy text label (kept for backward compat). */
  rank: string;
  /** Phase D — proper Marine Nationale rank ID + label from MARINE_RANKS. */
  rank_id?: string;
  rank_label?: string;
  /** Phase D — Indice de fiabilité, 1-12 (default 6). */
  reliability_score?: number;
  reliability_pos?: number;
  reliability_neg?: number;
  notify_radius_km?: number;
  muted_types?: string[];
  /** 13/07/2026 — position des boutons zoom déplaçables sur la carte. */
  zoom_btn_pos?: { x: number; y: number } | null;
  created_at?: string;
  is_dev?: boolean;
  // Phase 3a — referral system
  referral_code?: string | null;
  referred_by?: string | null;
  /** 31/07/2026 — compte SignalMar admin (armateur) : débloque la fonction
   *  « Capture & envoi au support » sur la carte + endpoints d'inspection. */
  is_signalmar_admin?: boolean;
  /** E.164 phone number (backend-only field, exposed for admin check). */
  phone?: string;
  /** 01/08/2026 — Moteur de routage préféré (choisi depuis le profil). */
  active_engine_id?: string;
}

export interface AuthPayload {
  token: string;
  user: User;
}

export interface ReportEdit {
  id: string;
  kind: "fake" | "ended" | "shift";
  new_lat?: number | null;
  new_lng?: number | null;
  comment: string;
  proposer: { user_id: string; name: string };
  created_at: string;
  up_count: number;
  down_count: number;
  net: number;
  my_vote: "up" | "down" | null;
  applied: boolean;
  applied_at?: string | null;
}

export interface DriftCone {
  bearing_deg: number;
  /** Phase E.3 — algorithmic bearing (wind+current vector sum), always present.
   * When bearing_source = "user", `bearing_deg` is the user-set heading and
   * `algo_bearing_deg` exposes the pure-physics estimate for transparency. */
  algo_bearing_deg?: number;
  /** "auto" = computed from wind+current. "user" = overridden by the report's
   * heading field (set by the author or a trusted user with reliability ≥ 60%). */
  bearing_source?: "auto" | "user";
  distance_km: number;
  polygon: { lat: number; lng: number }[];
  wind_to_deg?: number;
  wind_speed_ms?: number;
  wind_source?: string;  // Phase E.6 — e.g. "AROME 1.3km" | "ARPEGE 0.1° Europe" | "Open-Meteo"
  current_to_deg?: number;
  current_speed_ms?: number;
  /** true = signalement à < 20 km d'une terre (îles comprises) : dérive
   *  estimée au VENT SEUL, le courant modèle n'y est pas fiable (13/07/2026). */
  wind_only?: boolean;
  hours?: number;
  weights?: { V: number; C: number };
  computed_at?: string;
}

export interface ReportItem {
  id: string;
  /** ID COURT public (8 caractères MAJUSCULES) — posts viraux + loupe carte. */
  short_id?: string | null;
  type: string;
  lat: number;
  lng: number;
  description: string;
  photos: string[];
  heading?: number | null;
  heading_edited_at?: string | null;
  heading_edited_by?: string | null;
  heading_edited_by_name?: string | null;
  speed_knots?: number | null;
  subtype?: string | null;
  activity?: string | null;
  status?: "active" | "ended" | null;
  flagged_fake?: boolean;
  /** Mode test bêta (19/07/2026) — signalement de TEST (badge « TEST »). */
  is_test?: boolean;
  created_at: string;
  last_confirmed_at: string;
  confirm_count: number;
  confirmed_by_me: boolean;
  author: {
    user_id: string;
    name: string;
    pseudo?: string;
    /** Phase D — Marine Nationale rank id (mousse, matelot, …). */
    rank_id?: string;
    rank_label?: string;
    /** Phase D — Indice de fiabilité, 1-12. */
    reliability_score?: number;
  };
  edits: ReportEdit[];
  drift_cone?: DriftCone | null;
}

/** Aperçu public anonymisé d'un signalement (page /s/[CODE]). */
export interface PublicReportPreview {
  short_id: string;
  type: string;
  subtype?: string | null;
  approx_lat: number;
  approx_lng: number;
  description_excerpt: string;
  created_at: string;
  confirm_count: number;
  author_pseudo: string;
  status: "active" | "ended" | "expired";
  photo?: string | null;
}

export interface ChatMessage {
  id: string;
  report_id: string;
  user_id: string;
  name: string;
  text: string;
  created_at: string;
}

export interface WeatherAlert {
  severity: "danger" | "warning" | "info";
  title: string;
  description: string;
}

export interface WeatherResponse {
  alerts: WeatherAlert[];
  current: {
    wind_speed_kn?: number;
    wind_gust_kn?: number;
    wind_direction?: number;
    temperature?: number;
    wave_height_m?: number;
    wave_period_s?: number;
    swell_height_m?: number;
  };
  error?: string;
}

export const api = {
  /** V2 N1 — calcule une route sûre A→B selon les réglages bateau. */
  computeRoute: (body: {
    start: RouteWaypoint;
    end: RouteWaypoint;
    draft_m: number;
    depth_margin_m: number;
    /** 23/07 — ABSENT = mode AUTO (marge adaptée au chenal par le moteur). */
    lateral_margin_m?: number;
    /** 22/07 — intégrer la hauteur de marée à l'heure de départ. */
    use_tide?: boolean;
    /** Epoch s UTC du départ (absent = maintenant). */
    departure_ts?: number;
    /** 26/07 — route « plus sûre » (règle des 150 %) : marge d'eau
     *  SUPPLÉMENTAIRE ajoutée au besoin (typiquement +2 m). */
    safety_extra_m?: number;
    /** 01/08/2026 — Moteur de routage à utiliser. Absent = preference user. */
    engine_id?: string;
  }, cancel?: CancelToken) => runAsJob<ComputedRoute>("/routes/compute/async", body, cancel),

  /** 22/07/2026 — route MANUELLE : distance + profil sur les waypoints donnés. */
  manualRoute: (body: {
    waypoints: RouteWaypoint[];
    draft_m: number;
    depth_margin_m: number;
    // 27/07 — marée aussi sur les routes manuelles/modifiées.
    use_tide?: boolean;
    departure_ts?: number;
    /** 01/08/2026 — Moteur de routage à utiliser. Absent = preference user. */
    engine_id?: string;
    // 10/09/2026 (V1.6) — STOP possible sur TOUS les écrans de calcul.
  }, cancel?: CancelToken) => runAsJob<ComputedRoute>("/routes/manual/async", body, cancel),

  /** 24/07/2026 — hauteur d'eau au point cliqué (fond carte + marée). */
  depthAt: (lat: number, lng: number) =>
    request<{
      covered: boolean;
      water?: boolean;
      depth_zh_m?: number;
      tide_m?: number;
      height_now_m?: number;
      port?: string;
    }>(`/bathy/depth?lat=${lat.toFixed(6)}&lng=${lng.toFixed(6)}`),

  /** 22/07/2026 — routes enregistrées (max 20/utilisateur). */
  savedRoutes: () => request<{ routes: SavedRoute[]; max: number }>("/routes/saved"),
  saveRoute: (body: {
    name: string;
    mode: "auto" | "manual";
    waypoints: RouteWaypoint[];
    distance_m: number;
    // 01/08/2026 — traçabilité multi-moteurs.
    engine_id?: string | null;
    engine_name?: string | null;
    algo_id?: string | null;
    draft_m?: number;
    depth_margin_m?: number;
    lateral_margin_m?: number;
    source_route_id?: string | null;
    /** 02/08/2026 — points DEMANDÉS (avant accrochage grille) : permettent de
     *  recalculer la route à l'identique avec un autre moteur (test A/B). */
    start?: RouteWaypoint;
    end?: RouteWaypoint;
  }) => request<SavedRoute>("/routes/saved", { method: "POST", body }),
  deleteSavedRoute: (id: string) =>
    request<{ ok: boolean }>(`/routes/saved/${id}`, { method: "DELETE" }),
  /** 04/09/2026 (ordre armateur) — SOURCE des dalles bathy PC : serveur OVH
   *  ou repli archive locale (affiché dans la fiche de détails de route). */
  tilesSource: () =>
    request<{ source: string; label: string; version: string;
      tiles_indexed: number; tiles_cached: number }>("/bathy/tiles-source"),
  /** 14/08/2026 (demande armateur) — Signalement « balisage non respecté » :
   *  envoie automatiquement l'ID de route + la balise concernée au support. */
  reportMarkIssue: (body: { route_id: string; mark_name?: string; comment?: string }) =>
    request<{ ok: boolean; report_id: string; route_found: boolean }>(
      "/routes/mark-report", { method: "POST", body }),
  /** 01/08/2026 — Recalcule une route enregistrée avec 1..6 moteurs et
   *  retourne les tracés côte à côte pour analyse. */
  recomputeSavedRoute: (id: string, engine_ids: string[], cancel?: CancelToken) =>
    runAsJob<{
      saved_route_id: string;
      source_engine_id: string | null;
      results: Record<string, ComputedRoute | { engine: unknown; error: string }>;
    }>(`/routes/saved/${id}/recompute/async`, { engine_ids }, cancel),

  // ── 01/08/2026 — Multi-moteurs de routage ─────────────────────────────
  listRoutingEngines: () =>
    request<{
      engines: RoutingEngine[];
      default_id: string;
      active_id: string;
      is_admin: boolean;
    }>("/routing/engines"),
  duplicateRoutingEngine: (source_id: string, name: string, description?: string) =>
    request<{ ok: boolean; engine: RoutingEngine }>(
      "/routing/engines/duplicate",
      { method: "POST", body: { source_id, name, description } },
    ),
  renameRoutingEngine: (id: string, name: string, description?: string) =>
    request<{ ok: boolean; engine: RoutingEngine }>(
      `/routing/engines/${encodeURIComponent(id)}`,
      { method: "PATCH", body: { name, description } },
    ),
  deleteRoutingEngine: (id: string) =>
    request<{ ok: boolean }>(
      `/routing/engines/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),
  setActiveRoutingEngine: (id: string) =>
    request<{ ok: boolean; engine_id: string; engine_name: string }>(
      "/routing/user/active-engine",
      { method: "POST", body: { engine_id: id } },
    ),

  /** Marées — port le plus proche (Open-Meteo, coefficient approché). */
  tidesNearest: (lat: number, lng: number) =>
    request<TidesResponse>(`/tides/nearest?lat=${lat}&lng=${lng}`),
  /** 28/07 — mini-graphe RouteCard : courbe de marée 24 h (pas 30 min). */
  tideCurve: (lat: number, lng: number) =>
    request<{ port: string; points: { ts: number; h: number }[] }>(
      `/tides/curve?lat=${lat}&lng=${lng}`,
    ),

  // Upload support (13/07/2026) — vidéos/captures d'écran vers le support.
  supportUploadInit: (filename: string, mime: string, totalChunks: number) =>
    request<{ upload_id: string }>("/support/upload/init", {
      method: "POST", body: { filename, mime, total_chunks: totalChunks },
    }),
  supportUploadChunk: (uploadId: string, index: number, dataB64: string) =>
    request<{ ok: boolean; received: number; total: number }>("/support/upload/chunk", {
      method: "POST", body: { upload_id: uploadId, index, data_b64: dataB64 },
    }),
  supportUploadComplete: (uploadId: string, note?: string) =>
    request<{ ok: boolean; size: number; filename: string }>("/support/upload/complete", {
      method: "POST", body: { upload_id: uploadId, note },
    }),

  /** 03/08/2026 — finalise une capture carte envoyée PAR MORCEAUX (les envois
   *  en un seul POST étaient throttlés par l'ingress : « status 429 » et la
   *  capture n'arrivait jamais). Rattache les coordonnées et le contexte. */
  commitMapSupportScreenshot: (body: {
    upload_id: string;
    mime?: string;
    lat?: number | null;
    lng?: number | null;
    depth_zh_m?: number | null;
    comment?: string | null;
    route_id?: string | null;
    context?: Record<string, unknown> | null;
  }) =>
    request<{ ok: boolean; id: string; size: number; created_at: string }>(
      "/support/screenshot/commit", { method: "POST", body },
    ),

  /** 31/07/2026 — capture d'écran carte (admin uniquement, upload direct) :
   *  base64 JPEG/PNG + contexte GPS/route pour diagnostic support. */
  /** 03/08/2026 — « Vérifier la réception » : ce que le serveur a RÉELLEMENT
   *  enregistré (captures, fichiers assemblés, bundles de logs). */
  supportInbox: () =>
    request<{
      screenshots: {
        id: string; created_at: string | null; lat: number | null;
        lng: number | null; has_image: boolean; size_bytes?: number | null;
        transport: string; route_id?: string | null;
      }[];
      files: { filename: string; size_bytes: number; modified_at: string }[];
      logs: { created_at: string | null; user_agent: string }[];
      server_time: string;
    }>("/support/inbox"),

  sendMapSupportScreenshot: (body: {
    /** 03/08/2026 — `null` accepté : sur navigateur la photo de l'iframe
     *  Leaflet est impossible, on envoie le CONTEXTE seul. */
    image_b64: string | null;
    lat?: number | null;
    lng?: number | null;
    depth_zh_m?: number | null;
    comment?: string | null;
    route_id?: string | null;
    context?: Record<string, unknown> | null;
  }) =>
    request<{ ok: boolean; id: string; created_at: string }>(
      "/support/screenshot", { method: "POST", body },
    ),

  /** 02/08/2026 — envoi du bundle de diagnostic (logs 24 h + instantané
   *  système) au support. Passe par le portier : priorité haute + ré-essai
   *  sur 429/50x de l'ingress (un `fetch` brut perdait l'envoi). */
  sendDiagnostics: (body: {
    snapshot?: unknown;
    logs_text?: string;
    user_email?: string | null;
    user_id?: string | null;
    note?: string | null;
  }) =>
    request<{ id: string }>("/diagnostics", { method: "POST", body }),

  // Phase A — Auth par téléphone + OTP (SMS mocké : code 123456).
  otpRequest: (phone: string) =>
    request<{ sent: boolean; account_exists: boolean; mock: boolean; cooldown: number }>(
      "/auth/otp/request",
      { method: "POST", body: { phone }, auth: false },
    ),
  /** 14/08/2026 (audit QA FND-009) — connexion email + mot de passe. */
  loginEmail: (email: string, password: string) =>
    request<AuthPayload>("/auth/login", {
      method: "POST",
      body: { email, password },
    }),
  otpVerify: (phone: string, code: string, pseudo?: string, referralCode?: string) =>
    request<AuthPayload>("/auth/otp/verify", {
      method: "POST",
      body: {
        phone,
        code,
        ...(pseudo ? { pseudo } : {}),
        ...(referralCode ? { referral_code: referralCode } : {}),
      },
      auth: false,
    }),
  googleSession: (session_id: string) =>
    request<AuthPayload>("/auth/google/session", {
      method: "POST",
      body: { session_id },
      auth: false,
    }),
  me: () => request<User>("/auth/me"),
  updateMe: (body: { pseudo?: string; voice_settings?: Record<string, unknown> }) =>
    request<User>("/auth/me", { method: "PATCH", body }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  listReports: (params: {
    lat?: number;
    lng?: number;
    radius_km?: number;
    types?: string[];
    min_age_hours?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.lat != null) qs.set("lat", String(params.lat));
    if (params.lng != null) qs.set("lng", String(params.lng));
    if (params.radius_km != null) qs.set("radius_km", String(params.radius_km));
    if (params.types && params.types.length) qs.set("types", params.types.join(","));
    if (params.min_age_hours != null) qs.set("min_age_hours", String(params.min_age_hours));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<ReportItem[]>(`/reports${suffix}`);
  },
  getReport: (id: string) => request<ReportItem>(`/reports/${id}`),
  /** Recherche par ID COURT (loupe de la carte) → renvoie l'id long. */
  getReportByCode: (code: string) =>
    request<{ id: string; short_id: string; type: string }>(
      `/reports/by-code/${encodeURIComponent(code.trim().toUpperCase())}`,
    ),
  /** Aperçu PUBLIC (sans auth) — page web /s/[CODE] des posts viraux. */
  getPublicReportPreview: (code: string) =>
    request<PublicReportPreview>(
      `/public/report/${encodeURIComponent(code.trim().toUpperCase())}`,
      { auth: false },
    ),
  createReport: (data: {
    type: string;
    lat: number;
    lng: number;
    description: string;
    photos: string[];
    heading?: number | null;
    speed_knots?: number | null;
    subtype?: string | null;
    activity?: string | null;
    extras?: Record<string, string | number | boolean | null> | null;
  }) =>
    // V1.2 — the backend also returns `points_awarded` and `is_first_report`
    // on the freshly created report so the client can toast the reward.
    request<ReportItem & { points_awarded?: number; is_first_report?: boolean }>(
      "/reports", { method: "POST", body: data },
    ),
  // ── Mode test BÊTA (19/07/2026 — préparation distribution APK) ──
  betaStatus: () =>
    request<{ is_tester: boolean; is_admin: boolean; test_mode: boolean }>("/beta/status"),
  setTestMode: (enabled: boolean) =>
    request<{ ok: boolean; test_mode: boolean }>("/beta/test-mode", {
      method: "POST", body: { enabled },
    }),
  betaTesters: () =>
    request<{ testers: {
      phone: string; note: string; added_at?: string;
      pseudo?: string | null; has_account: boolean; test_mode: boolean;
    }[] }>("/beta/testers"),
  addBetaTester: (phone: string, note?: string) =>
    request<{ ok: boolean; phone: string }>("/beta/testers", {
      method: "POST", body: { phone, note },
    }),
  removeBetaTester: (phone: string) =>
    request<{ ok: boolean }>(`/beta/testers/${encodeURIComponent(phone)}`, {
      method: "DELETE",
    }),
  confirmReport: (id: string, source?: "proximity") =>
    // V1.2 — confirm response is enriched with the confirmer's grade delta,
    // the author's fiabilité delta, and the referral bonus flag. Used by the
    // report detail screen to render a proper toast on success.
    // 15/07/2026 — source "proximity" (popup de passage) = points réduits.
    request<ReportItem & {
      confirmer_points_awarded?: number;
      author_reliability_awarded?: number;
      author_pseudo?: string | null;
      referral_bonus_paid?: boolean;
    }>(`/reports/${id}/confirm`, {
      method: "POST",
      body: source ? { source } : undefined,
    }),
  /** 15/07/2026 — infirmation communautaire (« Non, pas vu » de la popup
   *  de passage à proximité). Effets côté backend : none / ttl_reduced /
   *  removed selon fraîcheur et nombre de « Non ». */
  denyReport: (id: string) =>
    request<{ effect: "none" | "ttl_reduced" | "removed"; denial_count?: number }>(
      `/reports/${id}/deny`, { method: "POST" },
    ),
  proposeEdit: (
    id: string,
    data: { kind: "fake" | "ended" | "shift"; new_lat?: number | null; new_lng?: number | null; comment?: string },
  ) => request<ReportItem>(`/reports/${id}/edits`, { method: "POST", body: data }),
  /** Author-only direct edit (no community vote). Used when the report's author
   *  shifts the point or marks it as ended on their own report.
   *
   *  Heading edits (cap) are also accepted by trusted users (reliability ≥ 60%)
   *  on autorites / drift-eligible reports — the backend authorises that case
   *  even when the caller is NOT the author. */
  authorEdit: (
    id: string,
    data: {
      new_lat?: number | null;
      new_lng?: number | null;
      status?: "active" | "ended";
      heading?: number;
      speed_knots?: number;
    },
  ) => request<ReportItem>(`/reports/${id}`, { method: "PATCH", body: data }),
  /** Author-only deletion. */
  deleteReport: (id: string) =>
    request<{ ok: boolean }>(`/reports/${id}`, { method: "DELETE" }),
  voteEdit: (rid: string, eid: string, vote: "up" | "down") =>
    request<ReportItem>(`/reports/${rid}/edits/${eid}/vote`, {
      method: "POST",
      body: { vote },
    }),
  listMessages: (id: string) =>
    request<ChatMessage[]>(`/reports/${id}/messages`),
  postMessage: (id: string, text: string) =>
    request<ChatMessage>(`/reports/${id}/messages`, {
      method: "POST",
      body: { text },
    }),

  profileMe: (opts?: { limit?: number; offset?: number }) => {
    const limit = opts?.limit ?? 5;
    const offset = opts?.offset ?? 0;
    return request<User & {
      reports_count: number;
      confirmations_count: number;
      history: ReportItem[];
      history_total: number;
      history_offset: number;
      history_limit: number;
    }>(`/profile/me?limit=${limit}&offset=${offset}`);
  },

  uploadAvatar: (imageBase64: string) =>
    request<User>("/profile/avatar", { method: "POST", body: { image: imageBase64 } }),

  updateLocation: (lat: number, lng: number) =>
    request<{ ok: boolean }>("/profile/location", {
      method: "POST",
      body: { lat, lng },
    }),

  updatePreferences: (prefs: { notify_radius_km?: number; muted_types?: string[]; zoom_btn_pos?: { x: number; y: number } }) =>
    request<User>("/profile/preferences", { method: "PUT", body: prefs }),

  // V1.2 — Phase 2 gamification: daily/streak reward on app open.
  pingOpen: () =>
    request<{
      awarded: number;
      reason: string;
      streak: number;
      user: User;
    }>("/profile/ping-open", { method: "POST" }),

  // V1.2 — journal of the last N gamification events (points + reliability).
  pointsHistory: (limit: number = 10) =>
    request<{
      items: Array<{
        ts: string;
        delta_points: number;
        delta_reliability: number;
        reason: string;
        report_id: string | null;
      }>;
      limit: number;
    }>(`/profile/points-history?limit=${limit}`),

  // Phase 3a — referral system (referral code + shareable join URL).
  getReferral: () =>
    request<{
      referral_code: string;
      join_url: string;
      friends_count: number;
      active_count: number;
      bonus_per_active_friend: number;
    }>("/profile/referral"),

  // ── Phase B — Subscription state + referral list ──────────────────
  getSubscription: () =>
    request<{
      subscription: SubscriptionState;
      referrals: ReferralItem[];
    }>("/profile/subscription"),

  // ── Invitations de parrainage par SMS (10/07/2026) ────────────────
  referralInvitationsCreate: (phone_hashes: string[]) =>
    request<{ created: number }>("/referral/invitations", {
      method: "POST",
      body: { phone_hashes },
    }),
  referralPending: (phone: string) =>
    request<{ invitations: SponsorInvitation[] }>("/referral/pending", {
      method: "POST",
      body: { phone },
      auth: false,
    }),
  referralResolveSponsor: (phone_hashes: string[]) =>
    request<{ sponsors: SponsorInvitation[] }>("/referral/resolve-sponsor", {
      method: "POST",
      body: { phone_hashes },
      auth: false,
    }),

  // Phase 3a — list of users I invited (referred_by == my referral_code).
  getFriends: () =>
    request<{
      items: Array<{
        user_id: string;
        pseudo: string;
        picture: string;
        rank_label: string;
        points: number;
        reliability_score: number;
        referral_bonus_paid: boolean;
        created_at: string | null;
        last_open_day: string | null;
      }>;
    }>("/profile/friends"),

  // Phase 3a — detailed sheet for one friend (3 last reports + 3 last confirms).
  getFriendDetail: (friendId: string) =>
    request<{
      friend: {
        user_id: string;
        pseudo: string;
        picture: string;
        rank_label: string;
        points: number;
        reliability_score: number;
        referral_bonus_paid: boolean;
        created_at: string | null;
        last_open_day: string | null;
      };
      last_reports: ReportItem[];
      last_confirmations: ReportItem[];
    }>(`/profile/friends/${friendId}`),

  // Phase 3b — bidirectional friends system (search / request / accept / list).
  friendsSearch: (query: string) =>
    request<{
      found: null | {
        user_id: string; pseudo: string; picture: string;
        rank_label: string; points: number; reliability_score: number;
      };
      relationship?: "friends" | "outgoing_pending" | "incoming_pending" | "none";
      request_id?: string | null;
    }>("/friends/search", { method: "POST", body: { query } }),
  friendsRequest: (toUserId: string) =>
    request<{ ok: boolean; already_friends?: boolean; request?: { id: string } }>(
      "/friends/request", { method: "POST", body: { to_user_id: toUserId } },
    ),
  friendsPending: () =>
    request<{
      incoming: Array<{
        id: string; from_user_id: string; to_user_id: string; created_at: string;
        user: { user_id: string; pseudo: string; picture: string; rank_label: string; points: number; reliability_score: number };
      }>;
      outgoing: Array<{
        id: string; from_user_id: string; to_user_id: string; created_at: string;
        user: { user_id: string; pseudo: string; picture: string; rank_label: string; points: number; reliability_score: number };
      }>;
    }>("/friends/pending"),
  friendsAccept: (reqId: string) =>
    request<{ ok: boolean }>(`/friends/request/${reqId}/accept`, { method: "POST" }),
  friendsReject: (reqId: string) =>
    request<{ ok: boolean }>(`/friends/request/${reqId}/reject`, { method: "POST" }),
  friendsList: () =>
    request<{
      items: Array<{
        user_id: string; pseudo: string; picture: string;
        rank_label: string; points: number; reliability_score: number;
        referral_bonus_paid: boolean; created_at: string | null; last_open_day: string | null;
      }>;
    }>("/friends/list"),

  // Phase 3c — In-app notifications (bell drawer / dedicated screen).
  notifications: (limit: number = 30, unreadOnly: boolean = false) =>
    request<{
      items: Array<{
        id: string; kind: string; title: string; message: string;
        action_url: string | null; created_at: string; read_at: string | null;
      }>;
      unread_count: number;
    }>(`/notifications?limit=${limit}&unread_only=${unreadOnly ? "true" : "false"}`),
  notificationsCount: () =>
    request<{ unread_count: number }>("/notifications/count"),
  notificationRead: (id: string) =>
    request<{ ok: boolean }>(`/notifications/${id}/read`, { method: "POST" }),
  notificationsReadAll: () =>
    request<{ ok: boolean; updated: number }>("/notifications/read-all", { method: "POST" }),
  notificationDelete: (id: string) =>
    request<{ ok: boolean }>(`/notifications/${id}`, { method: "DELETE" }),
  notificationsClearAll: () =>
    request<{ ok: boolean; deleted: number }>("/notifications/all", { method: "DELETE" }),

  registerPush: (user_id: string, platform: string, device_token: string) =>
    request<{ status: string }>("/register-push", {
      method: "POST",
      body: { user_id, platform, device_token },
      auth: false,
    }),

  weather: (lat: number, lng: number) =>
    request<WeatherResponse>(`/weather/marine?lat=${lat}&lng=${lng}`, {
      auth: false,
    }),

  // ── Phase 4.1 — Private groups ─────────────────────────────────────
  groupsList: () => request<{ groups: GroupSummary[] }>("/groups"),
  groupCreate: (body: { name: string; description?: string; avatar_url?: string }) =>
    request<GroupSummary>("/groups", { method: "POST", body }),
  groupDetail: (group_id: string) =>
    request<{ group: GroupSummary; members: GroupMember[] }>(`/groups/${group_id}`),
  groupUpdate: (
    group_id: string,
    body: { name?: string; description?: string; avatar_url?: string },
  ) => request<GroupSummary>(`/groups/${group_id}`, { method: "PATCH", body }),
  groupDelete: (group_id: string) =>
    request<{ ok: boolean }>(`/groups/${group_id}`, { method: "DELETE" }),
  groupRegenerateInvite: (group_id: string) =>
    request<GroupSummary>(`/groups/${group_id}/regenerate-invite`, { method: "POST" }),
  groupPreviewInvite: (invite_code: string) =>
    request<GroupInvitePreview>(`/groups/join/${encodeURIComponent(invite_code)}/preview`),
  groupJoinByCode: (invite_code: string) =>
    request<GroupSummary>(`/groups/join/${encodeURIComponent(invite_code)}`, {
      method: "POST",
    }),
  groupLeave: (group_id: string) =>
    request<{ ok: boolean }>(`/groups/${group_id}/leave`, { method: "POST" }),
  groupKick: (group_id: string, user_id: string) =>
    request<{ ok: boolean }>(`/groups/${group_id}/kick/${user_id}`, { method: "POST" }),

  // ── Phase 4.2 — Contact sync ───────────────────────────────────────
  contactsMatch: (hashes: string[]) =>
    request<{ matches: ContactMatch[] }>("/contacts/match", {
      method: "POST",
      body: { hashes },
    }),

  // ── Phase 4.2b — Direct targeted invitations ───────────────────────
  invitationsCreate: (group_id: string, user_ids: string[]) =>
    request<{
      created: number;
      already_member: number;
      remaining_seats: number;
      invitations: PendingInvitation[];
    }>(`/groups/${group_id}/invitations`, { method: "POST", body: { user_ids } }),
  invitationsMine: () =>
    request<{ invitations: PendingInvitation[] }>("/invitations/mine"),
  invitationAccept: (invite_id: string) =>
    request<GroupSummary>(`/invitations/${invite_id}/accept`, { method: "POST" }),
  invitationDecline: (invite_id: string) =>
    request<{ ok: boolean }>(`/invitations/${invite_id}/decline`, { method: "POST" }),

  // ── Phase T — Test-account fast switcher (dev / QA only) ───────────
  devListTestAccounts: () =>
    request<{ current_user_id: string; accounts: TestAccount[] }>(
      "/dev/test-accounts",
    ),
  devSwitchAccount: (target_user_id: string) =>
    request<{ token: string; user: User }>("/dev/switch-account", {
      method: "POST",
      body: { target_user_id },
    }),
  /** 13/07/2026 — lot de 5 signalements de TEST d'alarme (600 m → 20 km)
   *  autour de la position donnée ; efface le lot précédent. Whitelist. */
  devAlertTestBatch: (lat: number, lng: number) =>
    request<{
      ok: boolean;
      deleted: number;
      created: { id: string; distance_km: number; type: string; subtype: string }[];
    }>("/dev/alert-test-batch", { method: "POST", body: { lat, lng } }),
};

// ── Phase 4.1 — Group types ───────────────────────────────────────────
export interface GroupSummary {
  group_id: string;
  name: string;
  description: string;
  avatar_url: string;
  owner_id: string;
  invite_code: string;
  member_count: number;
  max_members: number;
  my_role: "owner" | "member" | null;
  created_at: number;
  updated_at: number;
}

export interface GroupMember {
  user_id: string;
  pseudo: string;
  picture: string;
  rank_label: string;
  role: "owner" | "member";
  joined_at: number;
  reliability_score?: number | null;
}

export interface GroupInvitePreview {
  group_id: string;
  name: string;
  description: string;
  avatar_url: string;
  member_count: number;
  max_members: number;
  owner_pseudo: string;
  owner_picture: string;
}

// ── Phase 4.2 — Contact match types ─────────────────────────────────
export interface ContactMatch {
  phone_hash: string;
  user_id: string;
  pseudo: string;
  picture: string;
  rank_label: string;
  reliability_score?: number | null;
}

// ── Phase T — Test-account fast switcher (dev/QA convenience) ───────
export interface TestAccount {
  user_id: string;
  email: string | null;
  phone: string | null;
  pseudo: string;
  picture: string;
  points: number;
  is_current: boolean;
}

// ── Phase 4.2b — Direct targeted invitations ─────────────────────────
export interface PendingInvitation {
  invite_id: string;
  group_id: string;
  group_name: string;
  group_description: string;
  group_avatar_url: string;
  group_member_count: number;
  group_max_members: number;
  inviter_user_id: string;
  inviter_pseudo: string;
  inviter_picture: string;
  created_at: number;
  expires_at: number;
}

// ── Phase B — Subscription bonus tracking ─────────────────────────────
export interface SubscriptionState {
  bonus_months_confirmed: number;
  bonus_months_pending: number;
  cap_pending: number;
  premium_valid_until: number | null;
  premium_valid_until_iso: string | null;
  is_premium: boolean;
  remaining_days: number;
  registered_at: string | null;
  // Premium offert 1ʳᵉ année + paliers de points (10/07/2026) :
  free_year_until: number | null;
  free_year_active: boolean;
  points_per_month: number;
  points_progress: number;
  points_to_next_month: number;
  points_months_awarded: number;
}

// Invitations de parrainage par SMS (10/07/2026).
export interface SponsorInvitation {
  pseudo: string;
  picture: string;
  referral_code: string;
  invited_at?: number;
}

export type ReferralStatus =
  | "pending_report"
  | "pending_confirmation"
  | "confirmed"
  | "rejected_farm"
  | "expired";

export interface ReferralItem {
  referral_id: string;
  status: ReferralStatus;
  months_awarded: number;
  linked_at: number;
  first_report_at: number | null;
  confirmed_at: number | null;
  referee: {
    user_id: string;
    pseudo: string;
    picture: string;
  };
}
