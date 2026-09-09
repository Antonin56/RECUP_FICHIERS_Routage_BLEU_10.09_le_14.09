// SignalMar — Leaflet WebView HTML builder.
// 20/07/2026 refactor N0 : extrait de MarineMap.tsx (déplacement pur).
// 06/06/2026 refactor N1 : le JS embarqué (2400 lignes) est découpé en modules
// dans ./js/* et la feuille de style dans ./styles.ts. buildHtml ne fait plus
// que ASSEMBLER ces fragments dans le même ordre qu'avant — la chaîne HTML
// produite est identique octet pour octet (aucun changement fonctionnel).
import { REPORT_TYPES } from "@/src/lib/report-types";

import { MAP_CSS } from "./styles";
import { JS_BATHY } from "./js/bathy";
import { jsBootstrap } from "./js/bootstrap";
import { JS_EVENTS } from "./js/events";
import { JS_GEO } from "./js/geo";
import { JS_MARKERS } from "./js/markers";
import { JS_MEASURE } from "./js/measure";
import { JS_PREFETCH } from "./js/prefetch";
import { JS_ROUTE } from "./js/route";
import { JS_SEAMARKS } from "./js/seamarks";
import { jsSmApi } from "./js/sm-api";
import { JS_TILES } from "./js/tiles";
import { JS_WATER_TAP } from "./js/water-tap";
import { JS_ZONE_PICKER } from "./js/zone-picker";

export const TYPE_COLOR: Record<string, string> = REPORT_TYPES.reduce((acc, t) => {
  acc[t.id] = t.color;
  return acc;
}, {} as Record<string, string>);

export function buildHtml(center: { lat: number; lng: number }, zoom: number, crosshair: boolean, apiBase = "") {
  const head = `<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
`;
  const bodyOpen = `</style>
</head><body>
<div id="map"></div>
<div class="crosshair" id="ch" style="display:${crosshair ? "block" : "none"}"><div class="crosshair-dot"></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
`;
  // Ordre STRICT (dépendances de portée entre fragments) : bootstrap (map,
  // postMsg) → tuiles → bathy/iso → route → balises → compas → hauteur d'eau →
  // prefetch → marqueurs/cônes → helpers géo → window.SM → évènements.
  const js = [
    jsBootstrap(center, zoom, apiBase),
    JS_TILES,
    JS_BATHY,
    JS_ROUTE,
    JS_SEAMARKS,
    JS_MEASURE,
    JS_WATER_TAP,
    JS_ZONE_PICKER,
    JS_PREFETCH,
    JS_MARKERS,
    JS_GEO,
    jsSmApi(crosshair),
    JS_EVENTS,
  ].join("");

  return head + MAP_CSS + bodyOpen + js + `</script>
</body></html>`;
}
