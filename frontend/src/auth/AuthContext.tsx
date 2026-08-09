import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState, type AppStateStatus, Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";

import { api, TOKEN_KEY, type User } from "@/src/api/client";
import { storage } from "@/src/utils/storage";
import { registerForPush } from "@/src/lib/push";
import { showToast } from "@/src/components/Toast";

type AuthState = {
  user: User | null;
  loading: boolean;
  demoMode: boolean;
  /** Phase A — envoie l'OTP SMS. Retourne si un compte existe déjà. */
  requestOtp: (phone: string) => Promise<{ account_exists: boolean; mock: boolean; cooldown: number }>;
  /** Phase A — vérifie l'OTP : connexion, ou création si pseudo fourni. */
  verifyOtp: (phone: string, code: string, pseudo?: string, referralCode?: string) => Promise<void>;
  signInGoogle: () => Promise<void>;
  enterDemo: () => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (u: User | null) => void;
  /** Phase T — Fast-switch to another whitelisted test account (dev/QA). */
  switchToTestAccount: (targetUserId: string) => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

async function setToken(token: string) {
  await storage.secureSet(TOKEN_KEY, token);
}

async function clearToken() {
  await storage.secureRemove(TOKEN_KEY);
}

// 23/07/2026 (vidéos armateur, « déconnexions à répétition ») — le profil est
// mis en CACHE après chaque me()/login réussi : si /auth/me échoue pour une
// raison TRANSITOIRE (429 ingress, réseau, 5xx), on reste connecté avec le
// profil en cache au lieu de purger le token (= déconnexion brutale). Le
// token n'est purgé QUE sur un vrai 401 (session invalide/expirée).
const USER_CACHE_KEY = "signmar.user_cache";

async function saveUserCache(u: User) {
  try { await storage.setItem(USER_CACHE_KEY, JSON.stringify(u)); } catch { /* noop */ }
}

async function loadUserCache(): Promise<User | null> {
  try {
    const raw = await storage.getItem<string>(USER_CACHE_KEY, "");
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

function parseSessionId(url: string): string | null {
  try {
    const idx = url.indexOf("session_id=");
    if (idx === -1) return null;
    const sub = url.slice(idx + "session_id=".length);
    return decodeURIComponent(sub.split(/[&#]/)[0]);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [demoMode, setDemoMode] = useState(false);

  const hydrate = useCallback(async () => {
    try {
      const tok = await storage.secureGet<string>(TOKEN_KEY, "");
      if (!tok) {
        setUser(null);
        return;
      }
      const u = await api.me();
      setUser(u);
      void saveUserCache(u);
    } catch (e) {
      const status = (e as Error & { status?: number }).status;
      if (status === 401) {
        // Session réellement invalide/expirée → déconnexion propre.
        await clearToken();
        setUser(null);
        return;
      }
      // 23/07/2026 — erreur TRANSITOIRE (429 ingress, réseau coupé, 5xx…) :
      // on NE déconnecte PAS. Profil en cache → session conservée telle
      // quelle ; sans cache (tout premier lancement hors-ligne), on retente
      // une fois avant d'abandonner SANS purger le token.
      const cached = await loadUserCache();
      if (cached) {
        setUser(cached);
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const u = await api.me();
        setUser(u);
        void saveUserCache(u);
      } catch {
        setUser(null);
      }
    }
  }, []);

  useEffect(() => {
    (async () => {
      await hydrate();
      setLoading(false);
    })();
  }, [hydrate]);

  // Whenever we have a logged-in user, (re-)register for push.
  useEffect(() => {
    if (user) void registerForPush(user.user_id);
  }, [user]);

  // V1.2 — Phase 2 gamification: ping the backend once when a session opens
  // and again every time the app comes back to foreground. The backend is
  // idempotent (once/UTC day) so it's safe to call generously.
  const lastPingRef = useRef<number>(0);
  const runPingOpen = useCallback(async () => {
    // Client-side throttle: at most one call per 60s to avoid spamming Metro
    // during HMR / rapid focus toggles on the web preview.
    const now = Date.now();
    if (now - lastPingRef.current < 60_000) return;
    lastPingRef.current = now;
    try {
      const r = await api.pingOpen();
      if (r.awarded > 0) {
        showToast("success", `${r.reason} : +${r.awarded} pt${r.awarded > 1 ? "s" : ""}`);
        setUser(r.user);
      }
    } catch {
      /* silent: never block the app on gamification */
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void runPingOpen();
    const sub = AppState.addEventListener("change", (state: AppStateStatus) => {
      if (state === "active") void runPingOpen();
    });
    return () => sub.remove();
  }, [user, runPingOpen]);

  const requestOtp = useCallback(async (phone: string) => {
    const r = await api.otpRequest(phone);
    return { account_exists: r.account_exists, mock: r.mock, cooldown: r.cooldown };
  }, []);

  const verifyOtp = useCallback(
    async (phone: string, code: string, pseudo?: string, referralCode?: string) => {
      const r = await api.otpVerify(phone, code, pseudo, referralCode);
      await setToken(r.token);
      setDemoMode(false);
      setUser(r.user);
    },
    [],
  );

  const signInGoogle = useCallback(async () => {
    const redirect =
      Platform.OS === "web"
        ? window.location.origin + "/"
        : Linking.createURL("auth");
    const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(
      redirect,
    )}`;
    let sessionId: string | null = null;

    if (Platform.OS === "web") {
      // Web: full-page redirect; session_id arrives in URL on return.
      window.location.href = authUrl;
      return;
    }

    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirect);
    if (result.type === "success" && result.url) {
      sessionId = parseSessionId(result.url);
    }
    if (!sessionId) {
      const initial = await Linking.getInitialURL();
      if (initial) sessionId = parseSessionId(initial);
    }
    if (!sessionId) throw new Error("Connexion Google annulée");
    const r = await api.googleSession(sessionId);
    await setToken(r.token);
    setDemoMode(false);
    setUser(r.user);
    void saveUserCache(r.user);
  }, []);

  const enterDemo = useCallback(() => {
    setDemoMode(true);
  }, []);

  // Web cold-start: pick up #session_id=... after redirect from auth.emergentagent.
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const url = window.location.href;
    const sid = parseSessionId(url);
    if (!sid) return;
    (async () => {
      try {
        const r = await api.googleSession(sid);
        await setToken(r.token);
        setUser(r.user);
        window.history.replaceState(null, "", window.location.pathname);
      } catch (e) {
        console.warn("google session error", e);
      }
    })();
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    await clearToken();
    await storage.removeItem(USER_CACHE_KEY).catch(() => {});
    setUser(null);
    setDemoMode(false);
  }, []);

  /**
   * Phase T — Swap the current session for another whitelisted test
   * account. The backend gate ensures only whitelisted callers can hit
   * this endpoint AND only whitelisted targets can be reached, so we
   * treat the received JWT exactly like a fresh login — no client-side
   * checks needed. Any error bubbles up so the UI can surface it.
   */
  const switchToTestAccount = useCallback(async (targetUserId: string) => {
    const r = await api.devSwitchAccount(targetUserId);
    await setToken(r.token);
    setDemoMode(false);
    setUser(r.user);
    void saveUserCache(r.user);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      demoMode,
      requestOtp,
      verifyOtp,
      signInGoogle,
      enterDemo,
      signOut,
      refresh: hydrate,
      setUser,
      switchToTestAccount,
    }),
    [user, loading, demoMode, requestOtp, verifyOtp, signInGoogle, enterDemo, signOut, hydrate, switchToTestAccount],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
