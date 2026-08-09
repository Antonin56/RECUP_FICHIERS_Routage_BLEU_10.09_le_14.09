// SignalMar — Logger persistant 24h pour diagnostic en production.
//
// Capture :
//   • console.log / warn / error  (proxy global, transparent pour le code)
//   • Erreurs JS non-attrapées     (ErrorUtils.setGlobalHandler)
//   • Rejets de promesses non gérés
//   • Évènements applicatifs ciblés via logger.event(category, ...)
//
// Stockage :
//   • Buffer circulaire en mémoire (MAX_ENTRIES) — accès O(1)
//   • Persistance sur disque (AsyncStorage) avec rotation 24h automatique
//   • Sérialisation sûre : pas de structures circulaires, troncature long
//
// Utilisation :
//   import { logger } from "@/src/lib/logger";
//   logger.init();                          // au démarrage de l'app
//   logger.event("nav", "stop", { speed });
//   const entries = await logger.getAll();
//
// L'API est volontairement minimale — voir Diagnostic.tsx pour l'UI.

import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

const STORAGE_KEY = "signalmar.logs.v1";
const MAX_ENTRIES = 500;          // ~120 ko en JSON
const RETENTION_MS = 24 * 60 * 60 * 1000; // 24h
const FLUSH_DEBOUNCE_MS = 750;
const MAX_FIELD_CHARS = 1200;     // évite les blobs base64 dans les logs

export type LogLevel = "debug" | "info" | "warn" | "error";
export type LogCategory =
  | "app"
  | "nav"
  | "gps"
  | "api"
  | "net"
  | "auth"
  | "report"
  | "push"
  | "other";

export interface LogEntry {
  ts: number;                        // epoch ms
  level: LogLevel;
  category: LogCategory;
  message: string;
  data?: string;                     // JSON stringifié (déjà tronqué)
}

// ────────────────────────────────────────────────────────────────────────
// Utils
// ────────────────────────────────────────────────────────────────────────

function safeStringify(value: unknown): string {
  if (value === undefined) return "";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const seen = new WeakSet<object>();
    const json = JSON.stringify(
      value,
      (_k, v) => {
        if (typeof v === "string" && v.length > 400 && v.startsWith("data:")) {
          return `<base64 ${v.length} chars>`;
        }
        if (typeof v === "object" && v !== null) {
          if (seen.has(v as object)) return "<circular>";
          seen.add(v as object);
        }
        return v;
      },
    );
    return json && json.length > MAX_FIELD_CHARS
      ? `${json.slice(0, MAX_FIELD_CHARS)}… <truncated ${json.length}>`
      : json;
  } catch {
    return String(value);
  }
}

function inferCategory(args: unknown[]): LogCategory {
  const head = typeof args[0] === "string" ? (args[0] as string).toLowerCase() : "";
  if (head.includes("[nav") || head.includes("nav:")) return "nav";
  if (head.includes("[gps") || head.includes("gps:")) return "gps";
  if (head.includes("[api") || head.includes("api:")) return "api";
  if (head.includes("[net") || head.includes("net:")) return "net";
  if (head.includes("[auth") || head.includes("auth:")) return "auth";
  if (head.includes("[push") || head.includes("push:")) return "push";
  if (head.includes("[report") || head.includes("report:")) return "report";
  return "other";
}

// ────────────────────────────────────────────────────────────────────────
// Logger
// ────────────────────────────────────────────────────────────────────────

class Logger {
  private buf: LogEntry[] = [];
  private inited = false;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private origConsole = {
    log: console.log.bind(console),
    info: console.info ? console.info.bind(console) : console.log.bind(console),
    warn: console.warn.bind(console),
    error: console.error.bind(console),
  };

  async init(): Promise<void> {
    if (this.inited) return;
    this.inited = true;

    // 1. Restaure les logs persistés (en respectant la rétention 24h).
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      if (raw) {
        const arr = JSON.parse(raw) as LogEntry[];
        const cutoff = Date.now() - RETENTION_MS;
        this.buf = arr.filter((e) => e.ts >= cutoff).slice(-MAX_ENTRIES);
      }
    } catch {
      // ignore : on démarre buffer vide
    }

    // 2. Patch console.* pour capturer tous les logs existants du code.
    console.log = (...args: unknown[]) => {
      this.push("info", inferCategory(args), this.fmt(args));
      this.origConsole.log(...args);
    };
    console.info = (...args: unknown[]) => {
      this.push("info", inferCategory(args), this.fmt(args));
      this.origConsole.info(...args);
    };
    console.warn = (...args: unknown[]) => {
      this.push("warn", inferCategory(args), this.fmt(args));
      this.origConsole.warn(...args);
    };
    console.error = (...args: unknown[]) => {
      this.push("error", inferCategory(args), this.fmt(args));
      this.origConsole.error(...args);
    };

    // 3. Capture les erreurs JS non-attrapées (RN seulement).
    type GlobalWithErrorUtils = typeof globalThis & {
      ErrorUtils?: {
        getGlobalHandler: () => (e: unknown, isFatal?: boolean) => void;
        setGlobalHandler: (h: (e: unknown, isFatal?: boolean) => void) => void;
      };
    };
    const g = globalThis as GlobalWithErrorUtils;
    if (g.ErrorUtils && typeof g.ErrorUtils.setGlobalHandler === "function") {
      const prev = g.ErrorUtils.getGlobalHandler();
      g.ErrorUtils.setGlobalHandler((err, isFatal) => {
        const e = err as Error | undefined;
        this.push("error", "app", `Uncaught${isFatal ? " FATAL" : ""}: ${e?.message ?? String(err)}`, {
          stack: e?.stack,
          isFatal,
        });
        try { prev?.(err, isFatal); } catch { /* ignore */ }
      });
    }

    // 4. Rejets de promesses (web) — équivalent natif via HermesInternal indispo.
    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.addEventListener("unhandledrejection", (ev) => {
        const reason = (ev as PromiseRejectionEvent).reason;
        const msg = reason instanceof Error ? reason.message : String(reason);
        this.push("error", "app", `UnhandledRejection: ${msg}`, {
          stack: reason instanceof Error ? reason.stack : undefined,
        });
      });
    }

    this.event("app", "logger_started", { platform: Platform.OS });
  }

  /** API publique pour les events applicatifs structurés. */
  event(category: LogCategory, message: string, data?: unknown): void {
    this.push("info", category, message, data);
  }

  /** Balise persistée IMMÉDIATEMENT sur disque (survit à un crash natif —
   *  utilisé pour tracer pas-à-pas les parcours qui tuent l'app, ex. photo). */
  async breadcrumb(category: LogCategory, message: string, data?: unknown): Promise<void> {
    this.push("info", category, message, data);
    if (this.flushTimer) { clearTimeout(this.flushTimer); this.flushTimer = null; }
    await this.flush().catch(() => { /* ignore */ });
  }

  warn(category: LogCategory, message: string, data?: unknown): void {
    this.push("warn", category, message, data);
  }

  error(category: LogCategory, message: string, data?: unknown): void {
    this.push("error", category, message, data);
  }

  // ────────────────────────────────────────────────────────────────────
  // Lecture
  // ────────────────────────────────────────────────────────────────────

  /** Retourne une copie du buffer actuel + reconstruit depuis le disque. */
  async getAll(): Promise<LogEntry[]> {
    // On se contente du buffer mémoire (déjà restauré au init).
    const cutoff = Date.now() - RETENTION_MS;
    return this.buf.filter((e) => e.ts >= cutoff).slice();
  }

  /** Sérialise les logs en .txt human-readable pour partage / mail. */
  async exportText(meta?: Record<string, unknown>): Promise<string> {
    const entries = await this.getAll();
    const lines: string[] = [];
    lines.push("=== SignalMar — Diagnostic Logs ===");
    lines.push(`Généré le : ${new Date().toISOString()}`);
    lines.push(`Plateforme : ${Platform.OS} ${Platform.Version ?? ""}`);
    if (meta) {
      for (const [k, v] of Object.entries(meta)) {
        lines.push(`${k} : ${safeStringify(v)}`);
      }
    }
    lines.push(`Nombre d'entrées : ${entries.length} (rétention 24h)`);
    lines.push("");
    lines.push("─".repeat(60));
    for (const e of entries) {
      const date = new Date(e.ts).toISOString().replace("T", " ").replace("Z", "");
      const lvl = e.level.toUpperCase().padEnd(5);
      const cat = e.category.padEnd(7);
      lines.push(`${date} [${lvl}] [${cat}] ${e.message}`);
      if (e.data) lines.push(`    ↳ ${e.data}`);
    }
    lines.push("─".repeat(60));
    return lines.join("\n");
  }

  async clear(): Promise<void> {
    this.buf = [];
    try { await AsyncStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
  }

  // ────────────────────────────────────────────────────────────────────
  // Internals
  // ────────────────────────────────────────────────────────────────────

  private fmt(args: unknown[]): string {
    return args.map((a) => (typeof a === "string" ? a : safeStringify(a))).join(" ");
  }

  private push(level: LogLevel, category: LogCategory, message: string, data?: unknown): void {
    const entry: LogEntry = {
      ts: Date.now(),
      level,
      category,
      message: message.length > MAX_FIELD_CHARS ? message.slice(0, MAX_FIELD_CHARS) + "…" : message,
    };
    if (data !== undefined) entry.data = safeStringify(data);
    this.buf.push(entry);
    if (this.buf.length > MAX_ENTRIES) this.buf.splice(0, this.buf.length - MAX_ENTRIES);
    this.scheduleFlush();
  }

  private scheduleFlush(): void {
    if (this.flushTimer) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      this.flush().catch(() => { /* ignore */ });
    }, FLUSH_DEBOUNCE_MS);
  }

  private async flush(): Promise<void> {
    try {
      const cutoff = Date.now() - RETENTION_MS;
      const fresh = this.buf.filter((e) => e.ts >= cutoff).slice(-MAX_ENTRIES);
      this.buf = fresh;
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(fresh));
    } catch {
      // disque plein, quota dépassé… on continue silencieusement
    }
  }
}

export const logger = new Logger();
