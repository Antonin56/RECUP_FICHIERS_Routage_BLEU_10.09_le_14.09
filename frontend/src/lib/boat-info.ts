// SignalMar — FICHE « Mon bateau » (28/07/2026, demande armateur).
// Identité du bateau (nom, photo, type, dimensions, motorisation) —
// persistée localement, distincte des RÉGLAGES DE SÉCURITÉ (boat-settings)
// qui pilotent le calcul de route.
import { useCallback, useEffect, useState } from "react";

import { storage } from "@/src/utils/storage";

export type BoatKind = "moteur" | "voilier";
export type EngineType = "outboard" | "inboard";

export type BoatInfo = {
  name: string;
  /** Photo (data URI base64, redimensionnée) — "" si absente. */
  photo: string;
  kind: BoatKind;
  lengthM: number | null;
  widthM: number | null;
  engineType: EngineType;
  engineCount: number;
  /** Marque commune à tous les moteurs (demande armateur). */
  engineBrand: string;
  /** Puissance par moteur (saisie libre, ex. "150 ch"). */
  enginePowers: string[];
};

const KEY = "sm.boat.info";

export const BOAT_INFO_DEFAULT: BoatInfo = {
  name: "",
  photo: "",
  kind: "moteur",
  lengthM: null,
  widthM: null,
  engineType: "outboard",
  engineCount: 1,
  engineBrand: "",
  enginePowers: [""],
};

function sanitize(v: unknown): BoatInfo {
  const o = (v && typeof v === "object" ? v : {}) as Partial<BoatInfo>;
  const count = Math.min(4, Math.max(1, Math.round(Number(o.engineCount) || 1)));
  const powers = Array.isArray(o.enginePowers) ? o.enginePowers.map((p) => String(p ?? "")) : [];
  while (powers.length < count) powers.push("");
  return {
    name: typeof o.name === "string" ? o.name : "",
    photo: typeof o.photo === "string" ? o.photo : "",
    kind: o.kind === "voilier" ? "voilier" : "moteur",
    lengthM: Number.isFinite(Number(o.lengthM)) && o.lengthM != null ? Number(o.lengthM) : null,
    widthM: Number.isFinite(Number(o.widthM)) && o.widthM != null ? Number(o.widthM) : null,
    engineType: o.engineType === "inboard" ? "inboard" : "outboard",
    engineCount: count,
    engineBrand: typeof o.engineBrand === "string" ? o.engineBrand : "",
    enginePowers: powers.slice(0, count),
  };
}

export async function getBoatInfo(): Promise<BoatInfo> {
  const raw = await storage.getItem<BoatInfo>(KEY, BOAT_INFO_DEFAULT);
  return sanitize(raw);
}

export function useBoatInfo() {
  const [loaded, setLoaded] = useState(false);
  const [info, setInfoState] = useState<BoatInfo>(BOAT_INFO_DEFAULT);

  useEffect(() => {
    getBoatInfo()
      .then((v) => setInfoState(v))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const setInfo = useCallback((patch: Partial<BoatInfo>) => {
    setInfoState((prev) => {
      const next = sanitize({ ...prev, ...patch });
      storage.setItem(KEY, next).catch(() => {});
      return next;
    });
  }, []);

  return { loaded, info, setInfo };
}
