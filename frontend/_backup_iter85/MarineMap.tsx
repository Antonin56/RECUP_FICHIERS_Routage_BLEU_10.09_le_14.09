import { useMemo, useRef, useEffect, forwardRef, useImperativeHandle } from "react";
import { Platform, StyleSheet, View } from "react-native";
import { WebView, type WebViewMessageEvent } from "react-native-webview";

import { REPORT_TYPES } from "@/src/lib/report-types";
import type { ReportItem } from "@/src/api/client";

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
  /** 13/07/2026 — repousse le recentrage automatique de 5 s (comme un geste
   *  utilisateur) sans bouger la carte. */
  grantRecenterGrace: () => void;
  /** Phase K — set/update the yellow projection cone (or clear with null). */
  setNavCone: (halfAngleDeg: number | null, distanceKm: number | null) => void;
  /** Phase K.5 — set/update the Vigie mode radar ping radius (m). Pass 0/null to clear. */
  setRadarPing: (radiusM: number | null) => void;
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
};

const TYPE_COLOR: Record<string, string> = REPORT_TYPES.reduce((acc, t) => {
  acc[t.id] = t.color;
  return acc;
}, {} as Record<string, string>);

function buildHtml(center: { lat: number; lng: number }, zoom: number, crosshair: boolean) {
  return `<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  html,body{margin:0;padding:0;height:100%;width:100%;background:#0B132B;overflow:hidden;}
  /* Phase I (v5) — Smoother course-up rotation:
     - longer transition (550ms ease-out) makes 1-Hz heading updates blend
     - cumulative angle math is done in setBearing so 359°→1° animates the
       short way (+2°) instead of -358°. */
  #map{position:absolute;top:50%;left:50%;width:140vmax;height:140vmax;
    transform-origin:50% 50%;transform:translate(-50%,-50%);
    transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .leaflet-container{background:#0B132B;}
  .leaflet-tile{filter:brightness(.78) contrast(1.05) saturate(.92);}
  .leaflet-control-attribution{font-size:9px;background:rgba(11,19,43,.7);color:#A3CEF1;}
  .leaflet-control-attribution a{color:#48CAE4;}
  .leaflet-control-zoom a{background:#1C2541;color:#fff;border:1px solid rgba(255,255,255,.15);}
  .leaflet-control-zoom a:hover{background:#22305B;}
  /* Lift bottom-left zoom controls above the tab bar / FAB area. */
  .leaflet-bottom.leaflet-left{bottom:88px !important;left:8px !important;}
  .leaflet-control-zoom{box-shadow:0 6px 18px rgba(0,0,0,.45);border-radius:8px;overflow:hidden;}
  .leaflet-control-zoom a{width:38px;height:38px;line-height:38px;font-size:18px;}
  .sm-hit{width:54px;height:54px;display:flex;align-items:center;justify-content:center;cursor:pointer;position:relative;}
  /* --- Phase D: sexy zoom-adaptive markers ------------------------------- */
  .sm-pin{position:relative;width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    box-shadow:0 6px 16px rgba(0,0,0,.55),0 0 0 2px #0B132B;color:#fff;font-weight:900;font-size:16px;line-height:1;
    transition:transform .15s ease, width .15s ease, height .15s ease;}
  .sm-pin .sm-emoji{font-size:18px;line-height:1;filter:drop-shadow(0 1px 2px rgba(0,0,0,.5));}
  .sm-pin.sm-compact{width:24px;height:24px;}
  .sm-pin.sm-compact .sm-emoji{font-size:11px;}
  .sm-pin.sm-compact .sm-galon,.sm-pin.sm-compact .sm-rel{display:none;}
  .sm-pin.sm-marker-focus{transform:scale(1.18);box-shadow:0 0 0 4px rgba(72,202,228,.65),0 0 26px #48CAE4;}
  .sm-galon{position:absolute;top:-5px;right:-5px;width:18px;height:18px;border-radius:9px;display:flex;align-items:center;justify-content:center;
    border:2px solid #0B132B;font-size:9px;font-weight:900;color:#0B132B;line-height:1;box-shadow:0 2px 6px rgba(0,0,0,.5);}
  .sm-rel{position:absolute;bottom:-4px;right:-4px;min-width:18px;height:14px;padding:0 4px;border-radius:7px;
    background:#0B132B;color:#fff;font-size:9px;font-weight:900;display:flex;align-items:center;justify-content:center;line-height:1;
    border:1px solid rgba(255,255,255,.4);box-shadow:0 2px 4px rgba(0,0,0,.4);}
  .sm-marker{display:flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:50%;color:#fff;font-weight:900;font-size:14px;box-shadow:0 4px 14px rgba(0,0,0,.4);border:2px solid #0B132B;}
  .sm-marker.sm-marker-focus{box-shadow:0 0 0 4px rgba(72,202,228,.6),0 0 24px #48CAE4;transform:scale(1.18);}
  .sm-user{width:18px;height:18px;border-radius:50%;background:#48CAE4;border:3px solid rgba(72,202,228,.35);box-shadow:0 0 14px #48CAE4;}
  /* Phase I — Boat marker (red arrow) + projection line ahead. */
  .sm-boat-wrap{width:40px;height:40px;display:flex;align-items:center;justify-content:center;position:relative;}
  .sm-boat{width:0;height:0;border-left:11px solid transparent;border-right:11px solid transparent;border-bottom:24px solid #E63946;
    filter:drop-shadow(0 2px 4px rgba(0,0,0,.55));transform-origin:50% 70%;}
  .sm-boat-halo{position:absolute;width:30px;height:30px;border-radius:50%;background:rgba(230,57,70,.18);border:1px solid rgba(230,57,70,.45);
    top:50%;left:50%;transform:translate(-50%,-50%);}
  /* Phase K — Navigation projection cone (yellow). Sits ABOVE tiles but
     BELOW markers (see zIndex on the polygon layer via bringToBack after
     drift-cone rendering). The stroke is dashed to distinguish it from the
     drift cone (which is orange dashed 8,5). */
  .sm-nav-cone{filter:drop-shadow(0 0 8px rgba(244,162,97,.45));}
  /* Phase K.5 — Radar-ping animation (Vigie mode). Two concentric SVG
     circles centred on the boat; radius + opacity are driven by JS in
     requestAnimationFrame (see drawRadarPing) so we can control the exact
     expansion timing and the 1.5–2 s pause between two consecutive waves.
     No CSS keyframes on purpose — CSS cannot animate the SVG radius
     attribute reliably across browsers, and JS lets us keep the two waves
     in lockstep with any live change of the alert radius. */
  .sm-radar-ping{fill:none;pointer-events:none;}
  /* Phase K — Sober info popup shown on cone tap. Compact 3-row table with
     flare / corridor / angle. */
  .sm-cone-popup .leaflet-popup-content-wrapper{background:rgba(11,19,43,.96);color:#E8ECFB;border:1px solid #F4A261;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.45);padding:2px 4px;}
  .sm-cone-popup .leaflet-popup-content{margin:8px 12px 10px 12px;min-width:170px;}
  .sm-cone-popup .leaflet-popup-tip{background:#F4A261;}
  .sm-cone-popup .leaflet-popup-close-button{display:none;}
  .sm-cone-info .ttl{color:#F4A261;font-weight:900;font-size:10px;letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px;text-align:center;}
  .sm-cone-info .row{display:flex;justify-content:space-between;align-items:baseline;gap:14px;padding:4px 0;border-top:1px solid rgba(232,236,251,.09);}
  .sm-cone-info .row:first-of-type{border-top:none;padding-top:2px;}
  .sm-cone-info .lbl{color:rgba(232,236,251,.72);font-size:11px;font-weight:500;}
  .sm-cone-info .val{color:#FFFFFF;font-weight:800;font-size:12px;font-variant-numeric:tabular-nums;letter-spacing:.2px;}
  /* Bande côtière < 20 km — avertissement « vent seul » dans la popup cône. */
  .sm-cone-warn{display:block;margin-top:6px;padding-top:6px;border-top:1px solid rgba(244,162,97,.4);color:#F4A261;font-size:11px;font-weight:600;line-height:1.35;max-width:230px;white-space:normal;}
  /* Phase K — Markers outside the navigation cone are dimmed to 30% opacity
     so the pilot's eye is naturally drawn to reports inside their travel
     corridor. 0.6 s ease-in-out smooths out jitter when a marker is right
     on the cone boundary (avoids visible flickering at GPS tick rate). */
  .sm-hit.sm-outside-cone{opacity:.3;transition:opacity .6s ease-in-out;}
  .sm-hit{transition:opacity .6s ease-in-out;}
  /* Phase I (v4) — course-up rotation. The map div is rotated via setBearing
     (composed with the centering translate); child icons (.sm-hit, .sm-user,
     .sm-boat-wrap) are counter-rotated via --sm-counter to stay upright. */
  .leaflet-control-container{transform:rotate(var(--sm-counter,0deg));transform-origin:50% 50%;transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-hit,.sm-user,.sm-boat-wrap{transform:rotate(var(--sm-counter,0deg));transform-origin:50% 50%;transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-arrow-tip{display:flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;color:#0B132B;font-weight:900;font-size:10px;line-height:18px;text-align:center;border:2px solid #0B132B;box-shadow:0 2px 8px rgba(0,0,0,.4);}
  .crosshair{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none;z-index:500;}
  .crosshair::before,.crosshair::after{content:"";position:absolute;background:#E63946;}
  .crosshair::before{left:-22px;top:-1px;width:44px;height:2px;}
  .crosshair::after{left:-1px;top:-22px;width:2px;height:44px;}
  .crosshair-dot{width:14px;height:14px;border:2px solid #E63946;border-radius:50%;background:rgba(230,57,70,.18);}
  /* Phase E.6 — "Position dans +/- 1 h" label along the drift-cone arc. */
  .sm-cone-label-wrap{background:transparent !important;border:none !important;box-shadow:none !important;overflow:visible !important;
    transform:rotate(var(--sm-counter,0deg));transform-origin:50% 50%;transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-cone-label{display:inline-block;background:rgba(11,19,43,.88);color:#FFE0B3;font-weight:800;font-size:11px;
    padding:4px 10px;border-radius:12px;border:1.5px solid #FF6F1A;letter-spacing:.3px;line-height:1;
    box-shadow:0 3px 10px rgba(0,0,0,.55);white-space:nowrap;text-shadow:0 1px 2px rgba(0,0,0,.6);
    transform-origin:50% 50%;pointer-events:none;}
  .sm-cone-popup .leaflet-popup-content-wrapper{background:#0B132B;color:#E8F1FF;border:1.5px solid #FF6F1A;border-radius:12px;
    /* 16/07/2026 (retour user) — la carte est CSS-rotée en course-up ;
       le contenu du popup héritait de cette rotation et devenait illisible
       (renversé/oblique). On CONTRE-ROTE le contenu autour de l'ancre bas =
       pointe du popup : la bulle reste toujours à la verticale, la pointe
       reste bien fixée sur le cône. */
    transform:rotate(var(--sm-counter,0deg));
    transform-origin:50% 100%;
    transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-cone-popup .leaflet-popup-content{margin:10px 12px;font-size:12px;line-height:1.45;}
  .sm-cone-popup .leaflet-popup-tip{background:#0B132B;border:1.5px solid #FF6F1A;}
  .sm-cone-popup .leaflet-popup-close-button{color:#E8F1FF !important;}
  /* Échelle custom (10/07/2026) — règles discrètes : horizontale en bas
     (80 % de la largeur) et verticale à gauche (80 % de la hauteur), avec
     repères début / milieu / fin. Fixées au body (espace écran), donc
     toujours droites même en course-up. Métrique OU nautique selon le
     réglage user (16/07/2026). */
  .sm-ruler{position:fixed;pointer-events:auto;z-index:600;cursor:pointer;}
  #sm-ruler-h{left:10%;right:10%;bottom:8px;height:18px;border-bottom:1px solid rgba(255,255,255,.55);}
  #sm-ruler-h .tick{position:absolute;bottom:0;width:1px;height:6px;background:rgba(255,255,255,.55);}
  #sm-ruler-h .lbl{position:absolute;bottom:7px;transform:translateX(-50%);color:rgba(255,255,255,.85);
    font-size:9.5px;font-weight:700;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    text-shadow:0 1px 3px rgba(0,0,0,.9),0 0 4px rgba(0,0,0,.7);white-space:nowrap;letter-spacing:.2px;}
  #sm-ruler-v{left:8px;top:10%;bottom:10%;width:18px;border-left:1px solid rgba(255,255,255,.55);}
  #sm-ruler-v .tick{position:absolute;left:0;height:1px;width:6px;background:rgba(255,255,255,.55);}
  #sm-ruler-v .lbl{position:absolute;left:8px;transform:translateY(-50%);color:rgba(255,255,255,.85);
    font-size:9.5px;font-weight:700;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    text-shadow:0 1px 3px rgba(0,0,0,.9),0 0 4px rgba(0,0,0,.7);white-space:nowrap;letter-spacing:.2px;}
  /* Barre style Navionics (16/07/2026) — longueur physique EXACTE = 1 km ou
     1 NM à l'écran, positionnée au-dessus de l'échelle horizontale, à
     gauche. L'œil compare visuellement les distances instantanément. */
  #sm-ruler-nav{position:fixed;bottom:34px;left:14px;z-index:601;pointer-events:auto;cursor:pointer;
    background:rgba(11,19,43,.72);border:1px solid rgba(255,255,255,.55);border-radius:5px;
    padding:2px 4px 3px 4px;color:#FFFFFF;font-weight:800;font-size:10px;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    letter-spacing:.3px;text-align:center;
    box-shadow:0 2px 6px rgba(0,0,0,.55);}
  #sm-ruler-nav .bar{position:relative;height:8px;margin-top:2px;border-left:1px solid #FFFFFF;border-right:1px solid #FFFFFF;
    border-bottom:1px solid #FFFFFF;}
</style>
</head><body>
<div id="map"></div>
<div class="crosshair" id="ch" style="display:${crosshair ? "block" : "none"}"><div class="crosshair-dot"></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  function postMsg(payload){
    var data = JSON.stringify(payload);
    if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(data);
    else if (window.parent) window.parent.postMessage(data, "*");
  }
  var map = L.map('map', {zoomControl:false, attributionControl:false}).setView([${center.lat}, ${center.lng}], ${zoom});
  // Expose the map instance for diagnostic/testing purposes (pan direction
  // verification). Harmless in production.
  window.__map__ = map;
  // Phase K.9 — Rotation-aware pan. The #map div is CSS-rotated in course-up
  // mode via SM.setBearing, but Leaflet's built-in Draggable computes offsets
  // in raw screen pixels and applies them to _mapPane. Because _mapPane
  // inherits the parent rotation, the visual pan ends up rotated by -bearing
  // relative to the finger — swiping straight down produces a diagonal drift.
  // We fix this by rotating the drag offset by +bearing so the visual result
  // matches the finger exactly (grab-and-drag). At moveend, getCenter() reads
  // the same rotated position, so the map center updates consistently.
  try {
    var _drg = map.dragging && map.dragging._draggable;
    if (_drg && _drg._updatePosition) {
      var _origUpdate = _drg._updatePosition.bind(_drg);
      _drg._updatePosition = function(){
        try {
          var b = (window.SM && typeof window.SM.bearing === 'number') ? window.SM.bearing : 0;
          if (b && this._newPos && this._startPos) {
            var off = this._newPos.subtract(this._startPos);
            var rad = b * Math.PI / 180;
            var cs = Math.cos(rad), sn = Math.sin(rad);
            var rx = off.x * cs - off.y * sn;
            var ry = off.x * sn + off.y * cs;
            this._newPos = this._startPos.add(L.point(rx, ry));
          }
        } catch(_){}
        return _origUpdate();
      };
    }
  } catch(_){}
  // Contrôle de zoom Leaflet intégré RETIRÉ (12/07/2026) — remplacé par les
  // boutons natifs +/- côté gauche (map.tsx), plus gros et accessibles.
  // Échelle custom (10/07/2026) — remplace L.control.scale : deux règles
  // discrètes (bas = 80 % de largeur, gauche = 80 % de hauteur) avec repères
  // 0 / milieu / fin recalculés à chaque déplacement/zoom.
  (function(){
    function mkRuler(id, vertical){
      var el = document.createElement('div');
      el.id = id; el.className = 'sm-ruler';
      for (var i = 0; i < 3; i++) {
        var t = document.createElement('div'); t.className = 'tick';
        var pos = (i * 50) + '%';
        if (vertical) t.style.top = pos; else t.style.left = pos;
        el.appendChild(t);
        var l = document.createElement('div'); l.className = 'lbl';
        l.id = id + '-l' + i;
        if (vertical) l.style.top = pos; else l.style.left = pos;
        el.appendChild(l);
      }
      // 16/07/2026 (retour user) — clic sur l'échelle → menu unité km/NM.
      el.addEventListener('click', function(){
        postMsg({ event: 'ruler_tap' });
      });
      document.body.appendChild(el);
    }
    mkRuler('sm-ruler-h', false);
    mkRuler('sm-ruler-v', true);
    // Barre style Navionics (16/07/2026) — longueur physique = 1 unité.
    // Positionnée en bas-gauche, EN PLUS de l'échelle horizontale actuelle.
    var nav = document.createElement('div');
    nav.id = 'sm-ruler-nav';
    nav.innerHTML = '<div id="sm-ruler-nav-lbl">1 km</div><div class="bar" id="sm-ruler-nav-bar"></div>';
    nav.addEventListener('click', function(){ postMsg({ event: 'ruler_tap' }); });
    document.body.appendChild(nav);

    function setLbl(id, txt){ var e = document.getElementById(id); if (e) e.textContent = txt; }
    // ── FIX 11/07/2026 (retour user : « 31 km total, moitié à 15 ») ──
    // 1) Le conteneur #map est un CARRÉ SURDIMENSIONNÉ de 140vmax (pour la
    //    rotation course-up) : mesurer 80 % de map.getSize() donnait des
    //    distances fausses (et identiques H/V). On mesure désormais aux
    //    positions RÉELLES des règles dans le VIEWPORT, converties en
    //    coordonnées du conteneur (rotation course-up comprise).
    // 2) Le repère du milieu est EXACTEMENT la moitié de la valeur de fin
    //    (fin arrondie pour un affichage propre « à l'œil »).
    function vpToLatLng(vx, vy){
      var W = window.innerWidth, H = window.innerHeight;
      var s = map.getSize();
      var aDeg = (window.SM && typeof window.SM.bearingApplied === 'number') ? window.SM.bearingApplied : 0;
      var a = aDeg * Math.PI / 180;
      var dx = vx - W / 2, dy = vy - H / 2;
      var cs = Math.cos(a), sn = Math.sin(a);
      // Le div est tourné de -bearingApplied ⇒ vecteur écran → vecteur
      // conteneur = rotation de +bearingApplied.
      var ux = dx * cs - dy * sn;
      var uy = dx * sn + dy * cs;
      return map.containerPointToLatLng([s.x / 2 + ux, s.y / 2 + uy]);
    }
    // 16/07/2026 (retour user) — arrondi pour la lisibilité « à l'œil »
    // (fini les 6,2 km) : on prend le divisor le plus proche parmi une
    // liste de valeurs rondes, puis on affiche la valeur ronde.
    function roundNice(x, thresholds){
      // thresholds ex. [1, 2, 5, 10, 20, 50, ...]
      var best = thresholds[0];
      var bestDiff = Math.abs(x - best);
      for (var i = 1; i < thresholds.length; i++){
        var d = Math.abs(x - thresholds[i]);
        if (d < bestDiff){ bestDiff = d; best = thresholds[i]; }
      }
      return best;
    }
    function setRuler(prefix, meters, unit){
      var midTxt, endTxt;
      if (unit === 'nm') {
        var nm = meters / 1852;
        var nmR;
        if (nm < 0.5) nmR = roundNice(nm, [0.05, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5]);
        else if (nm < 5) nmR = roundNice(nm, [0.5, 1, 1.5, 2, 3, 4, 5]);
        else if (nm < 50) nmR = roundNice(nm, [5, 10, 15, 20, 25, 30, 40, 50]);
        else nmR = roundNice(nm, [50, 75, 100, 150, 200, 300, 500]);
        var nmH = nmR / 2;
        midTxt = (nmH < 0.1 ? nmH.toFixed(2) : nmH.toString()).replace('.', ',') + ' NM';
        endTxt = (nmR < 1 ? nmR.toString().replace('.', ',') : nmR.toString()) + ' NM';
      } else if (meters < 2000){
        var m = meters;
        var mR;
        if (m < 200) mR = roundNice(m, [20, 50, 100, 150, 200]);
        else if (m < 1000) mR = roundNice(m, [200, 300, 400, 500, 700, 1000]);
        else mR = roundNice(m, [1000, 1200, 1500, 2000]);
        midTxt = (mR / 2) + ' m'; endTxt = mR + ' m';
      } else {
        var kmX = meters / 1000;
        var kmR;
        if (kmX < 10) kmR = roundNice(kmX, [2, 3, 4, 5, 6, 8, 10]);
        else if (kmX < 100) kmR = roundNice(kmX, [10, 15, 20, 25, 30, 40, 50, 75, 100]);
        else kmR = roundNice(kmX, [100, 150, 200, 300, 500, 750, 1000]);
        midTxt = (kmR / 2) + ' km'; endTxt = kmR + ' km';
      }
      // ─── Inversion échelle verticale (16/07/2026 retour user) ────────
      // Verticale : 0 EN BAS (l2), fin EN HAUT (l0). Horizontale : inchangée
      // (0 à gauche, fin à droite).
      if (prefix === 'sm-ruler-v') {
        setLbl(prefix + '-l0', endTxt);
        setLbl(prefix + '-l1', midTxt);
        setLbl(prefix + '-l2', '0');
      } else {
        setLbl(prefix + '-l0', '0');
        setLbl(prefix + '-l1', midTxt);
        setLbl(prefix + '-l2', endTxt);
      }
    }
    // 16/07/2026 — barre Navionics : longueur PIXELS = distance latLng ↔ ?
    // On calcule la longueur pixel qui correspond à 1 unité (1 km ou 1 NM)
    // au centre de l'écran, à la latitude/rotation courante.
    function updateNavBar(unit){
      try {
        var W = window.innerWidth, H = window.innerHeight;
        var oneUnitM = unit === 'nm' ? 1852 : 1000;
        var yH = H - 12;
        var A = vpToLatLng(W * 0.5, yH);
        var B = vpToLatLng(W * 0.5 + 100, yH);
        var mPer100px = A.distanceTo(B);
        if (mPer100px <= 0) return;
        var px = 100 * (oneUnitM / mPer100px);
        // Bornes : jamais < 30 px (illisible), jamais > W*0.5 (dépasse l'écran).
        px = Math.min(W * 0.5, Math.max(30, px));
        var bar = document.getElementById('sm-ruler-nav-bar');
        var lbl = document.getElementById('sm-ruler-nav-lbl');
        if (bar) bar.style.width = px + 'px';
        if (lbl) lbl.textContent = unit === 'nm' ? '1 NM' : '1 km';
      } catch(_){}
    }
    window.__mapUnit = 'km';
    window.__updateRulers = function(){
      try {
        var W = window.innerWidth, H = window.innerHeight;
        var unit = window.__mapUnit || 'km';
        // Horizontal : la règle va de 10 % à 90 % de la LARGEUR du viewport,
        // posée à ~12 px du bas — on mesure exactement ce segment.
        var yH = H - 12;
        var dH = vpToLatLng(W * 0.1, yH).distanceTo(vpToLatLng(W * 0.9, yH));
        setRuler('sm-ruler-h', dH, unit);
        // Vertical : de 10 % à 90 % de la HAUTEUR du viewport, à ~10 px du
        // bord gauche.
        var xV = 10;
        var dV = vpToLatLng(xV, H * 0.1).distanceTo(vpToLatLng(xV, H * 0.9));
        setRuler('sm-ruler-v', dV, unit);
        updateNavBar(unit);
      } catch(_){}
    };
    window.__setMapUnit = function(u){
      window.__mapUnit = (u === 'nm') ? 'nm' : 'km';
      window.__updateRulers();
    };
    map.on('move zoom resize viewreset', window.__updateRulers);
    window.__updateRulers();
  })();
  // 16/07/2026 (retour terrain « zones noires en mer ») — augmentation du
  // buffer de tuiles conservées en mémoire (2 → 4) : Leaflet garde ainsi
  // les tuiles environnantes après un pan/zoom léger, évitant les carrés
  // noirs le temps du téléchargement. Combiné au prefetch actif ci-dessous
  // (SM.prefetchAroundUser), ça donne un « cache navigateur » ~2 km autour
  // du bateau sur 3 zooms (Z-1, Z, Z+1) — voir SM.prefetchAroundUser.
  var _osmTiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution:'© OpenStreetMap', keepBuffer: 4,
  }).addTo(map);
  var _seaTiles = L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution:'© OpenSeaMap', opacity:0.95, keepBuffer: 4,
  }).addTo(map);
  // Prefetch actif de tuiles autour du bateau (16/07/2026 retour user).
  // Idée : on TÉLÉCHARGE en arrière-plan un rayon de 2 km autour de la
  // position user aux niveaux Z-1 / Z / Z+1. Les tuiles téléchargées sont
  // mises en cache navigateur (HTTP cache + Leaflet _tiles) → si on zoome
  // ou dézoome d'un pas, elles sont IMMÉDIATEMENT disponibles, plus de
  // carré noir. Best-effort (ignore les erreurs réseau).
  window.__prefetched = window.__prefetched || {};
  function tileUrl(template, z, x, y){
    return template.replace('{z}', z).replace('{x}', x).replace('{y}', y);
  }
  function lat2tile(lat, z){
    return Math.floor((1 - Math.log(Math.tan(lat*Math.PI/180) + 1/Math.cos(lat*Math.PI/180)) / Math.PI) / 2 * Math.pow(2, z));
  }
  function lon2tile(lng, z){ return Math.floor((lng+180)/360 * Math.pow(2, z)); }
  function prefetchAtZoom(lat, lng, z, radiusM){
    if (z < 3 || z > 18) return;
    var mPerPx = 156543.03392 * Math.cos(lat*Math.PI/180) / Math.pow(2, z);
    var tileM = 256 * mPerPx;
    var span = Math.max(1, Math.ceil(radiusM / tileM));
    var cx = lon2tile(lng, z), cy = lat2tile(lat, z);
    for (var dx = -span; dx <= span; dx++){
      for (var dy = -span; dy <= span; dy++){
        var x = cx + dx, y = cy + dy;
        var key = z + '/' + x + '/' + y;
        if (window.__prefetched[key]) continue;
        window.__prefetched[key] = true;
        // OSM standard
        try {
          var i = new Image();
          i.decoding = 'async'; i.loading = 'eager';
          i.src = tileUrl('https://tile.openstreetmap.org/{z}/{x}/{y}.png', z, x, y);
        } catch(_){}
        // OpenSeaMap seamark overlay
        try {
          var j = new Image();
          j.decoding = 'async'; j.loading = 'eager';
          j.src = tileUrl('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', z, x, y);
        } catch(_){}
      }
    }
  }
  window.__prefetchAroundUser = function(lat, lng){
    if (typeof lat !== 'number' || typeof lng !== 'number') return;
    var z = Math.round(map.getZoom());
    // Rayon = 2 km (choix user 16/07) sur Z-1 / Z / Z+1.
    prefetchAtZoom(lat, lng, z - 1, 2000);
    prefetchAtZoom(lat, lng, z,     2000);
    prefetchAtZoom(lat, lng, z + 1, 2000);
  };

  var markers = {};
  var arrows = {}; // polyline + tip per navigation authority
  // Phase E.6c — global click de-duplication across overlapping cones.
  // Leaflet fires the "click" handler on EVERY polygon whose path is hit,
  // even with bubblingMouseEvents:false. Instead of skipping siblings (which
  // arbitrarily picks whichever fired first), we collect *all* candidate
  // cones sharing the same native tap timeStamp and choose the winner in a
  // microtask: the cone whose apex (the report marker) is closest to the
  // tap point wins. That matches the user's intuition — the "most specific"
  // cone under the finger gets its popup.
  var pendingConeTap = null;
  var cones = {};  // drift-cone Leaflet.Polygon per report id
  var userMarker = null;

  // Phase D — emoji glyph per report type (used inside the bubble at zoom 12+).
  var TYPE_ICON = {
    autorites:    '\u{1F6E1}',  // shield
    secours:      '\u{1F6DF}',  // life buoy / SOS
    obstacle_nav: '\u26A0',     // warning sign
    animal_marin: '\u{1F42C}',  // dolphin
    pollution:    '\u{1F6E2}',  // oil drum
    autre:        '\u2049'      // interrobang
  };
  // Phase D — galon (rank chevron) colour tier mirrors the Marine ladder.
  function galonColor(rankId){
    if (!rankId) return '#90A4AE';
    if (rankId === 'amiral_de_france') return '#E63946';
    if (['amiral','vae','vice_amiral','contre_amiral'].indexOf(rankId) >= 0) return '#FFC300';
    if (['cv','cf','cc','lv','ev1','ev2','aspirant'].indexOf(rankId) >= 0) return '#FFD166';
    if (['major','maitre_principal','premier_maitre','maitre','second_maitre'].indexOf(rankId) >= 0) return '#CD7F32';
    return '#90A4AE'; // mousse, matelot, qm2, qm1
  }
  function galonGlyph(rankId){
    // Compact glyph showing the relative seniority. Single chevrons for
    // junior, double for senior, star for officer, crown for amiral tier.
    if (!rankId) return '\u25CF'; // dot
    if (['amiral_de_france','amiral','vae','vice_amiral','contre_amiral'].indexOf(rankId) >= 0) return '\u2605'; // ★
    if (['cv','cf','cc','lv','ev1','ev2','aspirant'].indexOf(rankId) >= 0) return '\u2666'; // ◆
    if (['major','maitre_principal','premier_maitre','maitre','second_maitre'].indexOf(rankId) >= 0) return '\u00AB'; // «
    return '\u25CF';
  }
  function shouldShowReliability(score){ return typeof score === 'number' && score >= 70; }

  function updateZoomState(){
    var z = map.getZoom();
    var compact = z < 12;
    var nodes = document.querySelectorAll('.sm-pin');
    for (var i=0;i<nodes.length;i++){
      if (compact) nodes[i].classList.add('sm-compact');
      else nodes[i].classList.remove('sm-compact');
    }
  }
  map.on('zoomend', updateZoomState);
  // Phase E.6b — toggle drift-cone labels based on zoom level AND on
  // whether the arc chord fits the label at the current pixel scale.
  function refreshConeLabels(){
    var minZoom = map.getZoom() >= 13;
    Object.keys(cones).forEach(function(id){
      var c = cones[id];
      if (!c || !c.label) return;
      var chord = c.arcChordPx || 0;
      // Recompute chord in pixels — projection changed on zoom/move.
      try {
        var pts = c.poly.getLatLngs()[0] || [];
        if (pts.length >= 3){
          var p1 = map.latLngToLayerPoint(pts[1]);
          var p2 = map.latLngToLayerPoint(pts[pts.length - 1]);
          chord = Math.hypot(p2.x - p1.x, p2.y - p1.y);
          c.arcChordPx = chord;
        }
      } catch(_){}
      var iconW = (c.label.options.icon && c.label.options.icon.options.iconSize)
        ? c.label.options.icon.options.iconSize[0] : 160;
      if (minZoom && chord >= iconW * 0.85){
        try { c.label.addTo(map); } catch(_){}
      } else {
        try { map.removeLayer(c.label); } catch(_){}
      }
    });
  }
  map.on('zoomend', refreshConeLabels);
  map.on('moveend', refreshConeLabels);

  // Phase E.6d — cone popup dispatcher.
  // Proper point-in-polygon hit-testing on ALL cones. Whatever is under the
  // finger is disambiguated geometrically (not by Leaflet's layer order or
  // any heuristic): the cone whose polygon actually contains the tap wins.
  // If multiple cones contain the tap (a rare overlap), the SMALLEST one
  // wins (most specific = the one visually on top after bringToBack calls).
  function pointInLatLngRing(lat, lng, ring){
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++){
      var xi = ring[i].lng, yi = ring[i].lat;
      var xj = ring[j].lng, yj = ring[j].lat;
      var intersect = ((yi > lat) !== (yj > lat)) &&
        (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }
  function boundsArea(bounds){
    var s = bounds.getSouth(), n = bounds.getNorth();
    var w = bounds.getWest(),  e = bounds.getEast();
    return Math.max(0, (n - s) * (e - w));
  }
  // 16/07/2026 (retour user « très difficile à cliquer sur le cône ») —
  // hit-test AVEC BUFFER PIXELS : point-in-polygon en coordonnées layer
  // pixels, ET distance minimale point→segment. Un clic à ≤ CLICK_BUFFER_PX
  // du bord du cône compte comme un hit (le doigt n'a plus besoin d'être
  // pile-poil dans le cône ; le halo invisible de 40 px suffit).
  var CLICK_BUFFER_PX = 40;
  function distPtSegSq(px, py, ax, ay, bx, by){
    var dx = bx - ax, dy = by - ay;
    var lenSq = dx * dx + dy * dy;
    var t = lenSq > 0 ? ((px - ax) * dx + (py - ay) * dy) / lenSq : 0;
    t = Math.max(0, Math.min(1, t));
    var qx = ax + t * dx, qy = ay + t * dy;
    var ddx = px - qx, ddy = py - qy;
    return ddx * ddx + ddy * ddy;
  }
  function ringDistancePx(clickLatLng, ring){
    // Convert ring + click to layer-point space (screen-like pixels at
    // current zoom). Returns { inside, distPx }.
    var pts = new Array(ring.length);
    for (var k = 0; k < ring.length; k++) pts[k] = map.latLngToLayerPoint(ring[k]);
    var p = map.latLngToLayerPoint(clickLatLng);
    // Point-in-polygon en pixel space.
    var inside = false;
    for (var i = 0, j = pts.length - 1; i < pts.length; j = i++){
      var xi = pts[i].x, yi = pts[i].y;
      var xj = pts[j].x, yj = pts[j].y;
      var intersect = ((yi > p.y) !== (yj > p.y)) &&
        (p.x < (xj - xi) * (p.y - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    if (inside) return { inside: true, distPx: 0 };
    // Distance minimale point ↔ bord.
    var minSq = Infinity;
    for (var m = 0; m < pts.length; m++){
      var a = pts[m], b = pts[(m + 1) % pts.length];
      var d = distPtSegSq(p.x, p.y, a.x, a.y, b.x, b.y);
      if (d < minSq) minSq = d;
    }
    return { inside: false, distPx: Math.sqrt(minSq) };
  }
  map.on('click', function(e){
    // Ignore clicks that originated on a marker (report pin, user pin, etc.).
    var tgt = e.originalEvent && e.originalEvent.target;
    if (tgt && tgt.closest && tgt.closest('.leaflet-marker-icon')) return;
    var matches = [];
    Object.keys(cones).forEach(function(id){
      var c = cones[id];
      if (!c || !c.poly) return;
      var ring = c.poly.getLatLngs()[0];
      if (!ring || ring.length < 3) return;
      var hit = ringDistancePx(e.latlng, ring);
      if (hit.inside || hit.distPx <= CLICK_BUFFER_PX){
        matches.push({
          id: id, entry: c,
          area: boundsArea(c.poly.getBounds()),
          insidePenalty: hit.inside ? 0 : hit.distPx,
        });
      }
    });
    if (!matches.length) return;
    // Priorité : d'abord ceux DANS le cône (insidePenalty=0), puis les plus
    // petits en surface (le plus « spécifique » visible sur écran).
    matches.sort(function(a, b){
      if (a.insidePenalty !== b.insidePenalty) return a.insidePenalty - b.insidePenalty;
      return a.area - b.area;
    });
    var winner = matches[0].entry;
    map.closePopup();
    L.popup({
      closeButton: true, maxWidth: 220,
      className: 'sm-cone-popup', autoPan: true,
    })
      .setLatLng(winner.popupLatLng)
      .setContent(winner.popupContent)
      .openOn(map);
  });

  // V1.1 — long-press on the map surface triggers a fresh signalement at
  // the tapped coordinate. Leaflet's "contextmenu" event fires on both desktop
  // right-click AND mobile long-press, which is exactly what we want.
  map.on('contextmenu', function(e){
    if (e && e.originalEvent){
      try { L.DomEvent.stop(e.originalEvent); } catch(_){}
    }
    var tgt = e.originalEvent && e.originalEvent.target;
    if (tgt && tgt.closest && tgt.closest('.leaflet-marker-icon')) return;
    postMsg({ event: 'longpress', lat: e.latlng.lat, lng: e.latlng.lng });
  });

  function destPoint(lat, lng, bearingDeg, distKm){
    var R = 6371.0;
    var br = bearingDeg * Math.PI / 180;
    var lat1 = lat * Math.PI / 180;
    var lng1 = lng * Math.PI / 180;
    var dr = distKm / R;
    var lat2 = Math.asin(Math.sin(lat1)*Math.cos(dr) + Math.cos(lat1)*Math.sin(dr)*Math.cos(br));
    var lng2 = lng1 + Math.atan2(
      Math.sin(br)*Math.sin(dr)*Math.cos(lat1),
      Math.cos(dr)-Math.sin(lat1)*Math.sin(lat2)
    );
    return [lat2 * 180 / Math.PI, lng2 * 180 / Math.PI];
  }
  /* Phase K — Great-circle bearing from (lat1,lng1) to (lat2,lng2), degrees. */
  function bearingTo(lat1, lng1, lat2, lng2){
    var p1 = lat1 * Math.PI / 180;
    var p2 = lat2 * Math.PI / 180;
    var dl = (lng2 - lng1) * Math.PI / 180;
    var y = Math.sin(dl) * Math.cos(p2);
    var x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    var brg = Math.atan2(y, x) * 180 / Math.PI;
    return (brg + 360) % 360;
  }
  /* Phase K — Haversine distance in km. */
  function distanceKm(lat1, lng1, lat2, lng2){
    var R = 6371.0;
    var dl = (lat2 - lat1) * Math.PI / 180;
    var dg = (lng2 - lng1) * Math.PI / 180;
    var a = Math.sin(dl/2)*Math.sin(dl/2)
          + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
          * Math.sin(dg/2) * Math.sin(dg/2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
  }
  /* Phase K — Is a report inside the navigation cone ?
   * heading: user's course (deg 0-360)
   * halfAngle: cone half-spread (deg)
   * totalDistKm: forward reach of the corridor (km)
   * Geometry: near-field is a triangle flare (2 km deep, ± halfAngle wide);
   * far-field is a parallel corridor of width 2 * flareKm * sin(halfAngle).
   * Returns true when the report lies inside this pill-like footprint. */
  function isInsideCone(rLat, rLng, bLat, bLng, heading, halfAngle, totalDistKm){
    if (heading == null || halfAngle == null || totalDistKm == null || totalDistKm <= 0) return true;
    var d = distanceKm(bLat, bLng, rLat, rLng);
    if (d > totalDistKm) return false;
    var brg = bearingTo(bLat, bLng, rLat, rLng);
    var diff = ((brg - heading + 540) % 360) - 180; // signed [-180,180]
    var absDiff = Math.abs(diff);
    if (absDiff >= 90) return false; // behind or beam-abeam
    var halfRad = halfAngle * Math.PI / 180;
    var diffRad = diff * Math.PI / 180;
    var flareKm = 1.0;
    var halfWidthKm = flareKm * Math.sin(halfRad);
    var alongKm = d * Math.cos(diffRad);
    var perpKm = Math.abs(d * Math.sin(diffRad));
    if (alongKm < 0) return false;
    if (alongKm > totalDistKm) return false;
    var alongFlareEnd = flareKm * Math.cos(halfRad);
    if (alongKm <= alongFlareEnd) {
      // Flare (triangle) zone: pure angular check.
      return absDiff <= halfAngle;
    }
    // Corridor (parallel) zone: perpendicular distance check.
    return perpKm <= halfWidthKm;
  }

  window.SM = {
    flyTo: function(lat,lng,z){
      // Un flyTo programmatique (nouveau signalement, bannière, focus…)
      // accorde le même délai de grâce de 5 s que un geste utilisateur
      // avant que le recentrage automatique ne reprenne la main.
      this.lastUserPan = Date.now();
      map.flyTo([lat,lng], z || map.getZoom(), {duration:0.8});
    },
    // 13/07/2026 — accorde 5 s de grâce au recentrage auto SANS bouger la
    // carte (retour depuis un écran détail, tap sur la carte, etc.).
    grantGrace: function(){ this.lastUserPan = Date.now(); },
    // Zoom INSTANTANÉ (non animé) — indispensable en follow-mode : le
    // recentrage périodique (setUser → recenterOnUser) réutilise
    // map.getZoom() et annulerait toute animation de zoom en cours.
    setZoom: function(z){
      this.programmaticMove = true;
      try { map.setView(map.getCenter(), z, { animate: false }); }
      finally { var self=this; setTimeout(function(){ self.programmaticMove = false; }, 50); }
    },
    // Boutons +/- natifs côté gauche (12/07/2026) — zoom pas-à-pas instantané.
    zoomIn: function(){ this.setZoom(Math.min(map.getMaxZoom ? map.getMaxZoom() : 19, map.getZoom() + 1)); },
    zoomOut: function(){ this.setZoom(Math.max(map.getMinZoom ? map.getMinZoom() : 2, map.getZoom() - 1)); },
    setCrosshair: function(on){
      this.crosshairOn = !!on;
      document.getElementById('ch').style.display = on ? 'block':'none';
    },
    // Phase I — Navigation projection helpers.
    userHeading: null,
    userSpeed: null,
    userTrail: null,          // L.polyline showing the projected route ahead
    userIsBoat: false,        // whether the current marker is the boat arrow
    bearing: null,            // course-up rotation applied to the map (deg)
    /** Phase J — follow-mode state. */
    navMode: false,
    lastUserPan: 0,
    userDragging: false,
    crosshairOn: ${crosshair},
    programmaticMove: false,
    lastHeadingApplied: null,
    /** Phase K — Navigation cone (yellow). Redrawn each time setUser is
     *  called with a valid heading + speed. Params are set by setNavCone(). */
    coneLayer: null,
    coneHalfAngle: null,
    coneDistanceKm: null,
    // Phase K.5 — Radar ping (Vigie mode). 3 stacked circles at 0.33/0.66/1.0
    // of the alert radius, each with CSS animation staggered so it looks like
    // a soft sonar pulse. Recreated when radiusM changes; position tracks the
    // boat marker every setUser tick.
    // Phase K.5 — Radar ping (Vigie mode). 2 rings expanding from the boat
    // to the alert radius, driven by requestAnimationFrame so we can insert
    // a 1.5–1.75 s pause between two consecutive waves. Each ring runs a
    // 1.5 s ease-out expansion then goes idle for the pause; the second ring
    // is offset by half a cycle so waves alternate smoothly.
    pingLayers: null,
    pingRadiusM: 0,
    pingRaf: null,      // requestAnimationFrame id
    setRadarPing: function(radiusM){
      var target = (typeof radiusM === 'number' && radiusM > 0) ? radiusM : 0;
      // Redraw needed when the radius changed OR the layers/animation died
      // (e.g. after a Vigie↔Nav round-trip or a WebView init race) — the
      // pingRaf check makes this call safely idempotent AND self-healing.
      if (target === this.pingRadiusM && this.pingLayers && this.pingRaf) { return; }
      this.pingRadiusM = target;
      this.drawRadarPing();
    },
    drawRadarPing: function(){
      // Cancel any running animation.
      if (this.pingRaf){ try { cancelAnimationFrame(this.pingRaf); } catch(_){} this.pingRaf = null; }
      // Remove previous layers.
      if (this.pingLayers){
        for (var i=0;i<this.pingLayers.length;i++){ try { map.removeLayer(this.pingLayers[i]); } catch(_){} }
        this.pingLayers = null;
      }
      if (!userMarker || !this.pingRadiusM) return;
      var ll = userMarker.getLatLng();
      // Phase K.10 — Radar drawn at the exact user-configured alert radius
      // (Zone de veille Vigie — voiceSettings.zoneVigieM, valeur fixe).
      // Ratio 1:1 with the map scale so 25 km configured = 25 km ring on screen.
      var maxR = this.pingRadiusM;
      var layers = [];
      // Create 2 identical rings — they'll alternate expansions.
      for (var i = 0; i < 2; i++){
        var c = L.circle(ll, {
          radius: 1,
          color: '#E63946',
          weight: 2.5,
          opacity: 0,
          fill: false,
          interactive: false,
          className: 'sm-radar-ping',
          bubblingMouseEvents: false,
        }).addTo(map);
        try { c.bringToBack(); } catch(_){}
        layers.push(c);
      }
      this.pingLayers = layers;
      // Timing (ms). WAVE = smooth expansion ; PAUSE = idle between waves.
      // CYCLE per ring = WAVE + PAUSE. Ring #1 is offset by CYCLE/2 so that
      // the visible wave rate on screen is one every (CYCLE/2) ≈ 1.6 s.
      var WAVE = 1500;
      var PAUSE = 1700;
      var CYCLE = WAVE + PAUSE;
      var offsets = [0, CYCLE / 2];
      var start = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
      var self = this;
      function tick(now){
        if (!self.pingLayers || !self.pingRadiusM){ self.pingRaf = null; return; }
        var t0 = now || ((typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now());
        for (var k = 0; k < self.pingLayers.length; k++){
          var el = ((t0 - start) - offsets[k]);
          // Keep positive within CYCLE.
          el = ((el % CYCLE) + CYCLE) % CYCLE;
          var layer = self.pingLayers[k];
          if (el < WAVE){
            var t = el / WAVE;                // 0..1
            var e = 1 - Math.pow(1 - t, 3);   // ease-out cubic
            var r = Math.max(1, e * maxR);
            var op = 0.9 * (1 - t);           // fade out as ring grows
            try {
              layer.setRadius(r);
              layer.setStyle({ opacity: op, weight: 2.5 });
            } catch(_){}
          } else {
            // Pause phase — invisible.
            try { layer.setStyle({ opacity: 0 }); } catch(_){}
          }
        }
        self.pingRaf = requestAnimationFrame(tick);
      }
      self.pingRaf = requestAnimationFrame(tick);
    },
    updateRadarPingPos: function(){
      if (!this.pingLayers || !userMarker) return;
      var ll = userMarker.getLatLng();
      for (var i=0;i<this.pingLayers.length;i++){ this.pingLayers[i].setLatLng(ll); }
    },
    /** Store current markers-latlng dict so updateReportsOpacity can be a
     *  fast in-place iteration without re-fetching from markers[]. */
    currentReports: [],
    // ── Anti-clignotement (14/07/2026) ─────────────────────────────
    // État courant d'opacité par marqueur (true=grisé) et changements en
    // attente (anti-rebond 1,5 s sur le GRISAGE uniquement).
    dimState: {},
    dimPending: {},
    DIM_DEBOUNCE_MS: 1500,
    setNavCone: function(halfAngleDeg, distKm){
      this.coneHalfAngle = (typeof halfAngleDeg === 'number' && halfAngleDeg > 0) ? halfAngleDeg : null;
      this.coneDistanceKm = (typeof distKm === 'number' && distKm > 0) ? distKm : null;
      this.drawCone();
      this.refreshTrail();
      this.updateReportsOpacity();
    },
    refreshTrail: function(){
      // Redraw / remove the long red projection line based on the current
      // cone-active state. Called from setUser (each GPS tick) and from
      // setNavCone (mode toggle) so the trail vanishes as soon as user
      // switches to Vigie mode without waiting for the next GPS update.
      if (this.userTrail){ map.removeLayer(this.userTrail); this.userTrail = null; }
      if (!userMarker || !this.userIsBoat) return;
      if (this.userHeading == null) return;
      if (this.coneHalfAngle == null || this.coneDistanceKm == null) return;
      var ll = userMarker.getLatLng();
      // 15/07/2026 (bug terrain, capture user) : la ligne était tracée comme
      // UNE corde droite de 500 km — or une géodésique de 500 km COURBE sur
      // la projection Mercator, la corde s'écartait donc de l'axe du couloir
      // (lui, calculé par points géodésiques successifs). On échantillonne
      // désormais la géodésique tous les 25 km : la ligne rouge passe
      // exactement par l'axe du cône, à tous les caps.
      var pts = [[ll.lat, ll.lng]];
      for (var dk = 25; dk <= 500; dk += 25){
        pts.push(destPoint(ll.lat, ll.lng, this.userHeading, dk));
      }
      this.userTrail = L.polyline(pts, {
        color:'#E63946', weight:3, opacity:0.95, interactive:false,
      }).addTo(map);
      try { this.userTrail.bringToFront(); } catch(_){}
    },
    drawCone: function(){
      if (this.coneLayer){ map.removeLayer(this.coneLayer); this.coneLayer = null; }
      if (!userMarker || !this.userIsBoat) return;
      if (this.coneHalfAngle == null || this.coneDistanceKm == null) return;
      if (this.userHeading == null) return;
      var ll = userMarker.getLatLng();
      var hd = this.userHeading;
      var half = this.coneHalfAngle;
      var totalDist = this.coneDistanceKm;
      var flareKm = 1.0;
      var halfRad = half * Math.PI / 180;
      var halfWidthKm = flareKm * Math.sin(halfRad);
      var alongFlareKm = flareKm * Math.cos(halfRad);
      // If the total forward reach is smaller than the flare projection
      // itself, we just draw a triangle (no corridor section).
      var effectiveEndKm = Math.max(totalDist, alongFlareKm + 0.05);
      // Convert local (perp, along) km → lat/lng. Perp is positive to the right
      // of heading. Along is along heading.
      function toLL(perpKm, alongKm){
        if (perpKm === 0 && alongKm === 0) return [ll.lat, ll.lng];
        var d = Math.sqrt(perpKm*perpKm + alongKm*alongKm);
        var b = hd + Math.atan2(perpKm, alongKm) * 180 / Math.PI;
        return destPoint(ll.lat, ll.lng, b, d);
      }
      var verts = [
        toLL(0, 0),
        toLL(-halfWidthKm, alongFlareKm),
      ];
      // 15/07/2026 — les longs bords du couloir sont échantillonnés (pas de
      // simple corde droite) : sur de grandes distances, une corde s'écarte
      // de la géodésique en Mercator et le couloir n'était plus centré sur
      // la ligne de cap (capture user). Pas d'échantillon ≈ 1/24 de longueur.
      var stepKm = Math.max(2, (effectiveEndKm - alongFlareKm) / 24);
      var a;
      for (a = alongFlareKm + stepKm; a < effectiveEndKm; a += stepKm){
        verts.push(toLL(-halfWidthKm, a));
      }
      verts.push(toLL(-halfWidthKm, effectiveEndKm));
      verts.push(toLL( halfWidthKm, effectiveEndKm));
      for (a = effectiveEndKm - stepKm; a > alongFlareKm; a -= stepKm){
        verts.push(toLL( halfWidthKm, a));
      }
      verts.push(toLL( halfWidthKm, alongFlareKm));
      this.coneLayer = L.polygon(verts, {
        color: '#F4A261', weight: 2.2, opacity: 0.92,
        fillColor: '#F4A261', fillOpacity: 0.14,
        interactive: true,
        className: 'sm-nav-cone',
        bubblingMouseEvents: false,
      }).addTo(map);
      try { this.coneLayer.bringToBack(); } catch(_){}
      // Tap on cone → sober info popup with flare + corridor dimensions.
      this.coneLayer.off('click');
      this.coneLayer.on('click', function(e){
        var wKm = 2 * halfWidthKm;
        var content = '<div class="sm-cone-info">'
          + '<div class="ttl">Cône Navigation</div>'
          + '<div class="row"><span class="lbl">Évasement</span><span class="val">' + flareKm.toFixed(1) + ' km</span></div>'
          + '<div class="row"><span class="lbl">Corridor</span><span class="val">' + wKm.toFixed(2) + ' × ' + totalDist.toFixed(1) + ' km</span></div>'
          + '<div class="row"><span class="lbl">Angle</span><span class="val">' + Math.round(half * 2) + '°</span></div>'
          + '</div>';
        L.popup({ className: 'sm-cone-popup', closeButton: false, autoPan: false, offset: [0, -6] })
          .setLatLng(e.latlng)
          .setContent(content)
          .openOn(map);
        try { L.DomEvent.stopPropagation(e); } catch(_){}
      });
    },
    updateReportsOpacity: function(){
      if (!markers) return;
      var boatLat = null, boatLng = null;
      if (userMarker && this.userIsBoat){
        var ll = userMarker.getLatLng();
        boatLat = ll.lat; boatLng = ll.lng;
      }
      var half = this.coneHalfAngle;
      var dist = this.coneDistanceKm;
      var hd = this.userHeading;
      var coneActive = (boatLat != null && half != null && dist != null && hd != null);
      var arr = this.currentReports || [];
      var now = Date.now();
      for (var i = 0; i < arr.length; i++){
        var r = arr[i];
        var m = markers[r.id];
        if (!m) continue;
        var el = m.getElement && m.getElement();
        if (!el) continue;
        var hit = el.querySelector && el.querySelector('.sm-hit');
        if (!hit) continue;

        // ── ANTI-CLIGNOTEMENT (14/07/2026, retour terrain) ──────────────
        // Le jitter GPS (cap ±2-5°/s + position) fait balayer la frontière
        // du couloir sur les marqueurs proches → bascule gris↔couleur à
        // 1 Hz (« clignotement »). Deux gardes VISUELLES (le déclenchement
        // des alertes, lui, vit dans sound-alert.ts et n'est PAS touché) :
        //  1. HYSTÉRÉSIS géométrique : pour passer de allumé→grisé, il faut
        //     être hors d'un couloir ÉLARGI (+5° d'angle, +12 % de longueur) ;
        //     pour repasser grisé→allumé, il faut être dans le couloir exact.
        //  2. ANTI-REBOND temporel : le changement d'état doit persister
        //     ≥ 1,5 s avant d'être appliqué au marqueur.
        var target;
        if (!coneActive){
          target = false; // Vigie / pas de cap → tout allumé, immédiatement.
        } else {
          var cur = Object.prototype.hasOwnProperty.call(this.dimState, r.id)
            ? !!this.dimState[r.id]
            : null; // premier passage : pas d'état connu
          if (cur === true){
            // Grisé → se rallume dès qu'il entre dans le couloir EXACT.
            target = !isInsideCone(r.lat, r.lng, boatLat, boatLng, hd, half, dist);
          } else {
            // Allumé (ou inconnu) → ne se grise que s'il est clairement hors
            // du couloir ÉLARGI (marge anti-jitter).
            target = !isInsideCone(r.lat, r.lng, boatLat, boatLng, hd, half + 5, dist * 1.12);
          }
          if (cur === null){
            // Premier passage (nouveau marqueur / entrée en mode Nav) :
            // application immédiate, sans anti-rebond.
            this.dimState[r.id] = target;
            delete this.dimPending[r.id];
            if (target){ hit.classList.add('sm-outside-cone'); }
            else { hit.classList.remove('sm-outside-cone'); }
            continue;
          }
          if (target !== cur){
            if (!target){
              // Rallumage (entrée dans le couloir exact) : IMMÉDIAT — pour
              // re-griser ensuite il faudra sortir du couloir ÉLARGI pendant
              // ≥ 1,5 s, donc pas d'aller-retour possible (anti-jitter).
              delete this.dimPending[r.id];
            } else {
              var p = this.dimPending[r.id];
              if (!p || p.state !== target){
                this.dimPending[r.id] = { state: target, since: now };
                target = cur; // pas encore stabilisé → on garde l'état courant
              } else if (now - p.since < this.DIM_DEBOUNCE_MS){
                target = cur; // en cours de stabilisation
              } else {
                delete this.dimPending[r.id]; // stabilisé → on grise
              }
            }
          } else {
            delete this.dimPending[r.id];
          }
        }
        this.dimState[r.id] = target;
        if (target){ hit.classList.add('sm-outside-cone'); }
        else { hit.classList.remove('sm-outside-cone'); }
      }
    },
    /** Dernière position GPS jugée fiable (i.e. obtenue alors que la vitesse
     *  dépassait le seuil). Quand on retombe sous le seuil, on RÉUTILISE
     *  cette position au lieu d'accepter le bruit du GPS (qui fait dériver
     *  le marqueur de 5-15 m même bateau parfaitement à l'arrêt). */
    lastReliablePos: null,
    /** 3 km/h in m/s (0.833) — below this speed, the GPS heading is jitter,
     *  so we hold the last reliable position + heading instead of letting
     *  the map vibrate. Same threshold used for the auto course-up switch
     *  in the useEffect below: < 3 km/h → freeze north-up, ≥ 3 km/h → rotate
     *  to heading. */
    MIN_NAV_SPEED_MS: 0.833,
    setNavMode: function(on, skipRecenter){
      this.navMode = !!on;
      if (this.navMode && userMarker && !skipRecenter) this.recenterOnUser(true);
      if (!this.navMode) {
        this.lastHeadingApplied = null;
        this.lastReliablePos = null;
        // Phase K — Kill the yellow cone & restore full opacity to markers
        // as soon as the pilot leaves Navigation mode.
        if (this.coneLayer){ map.removeLayer(this.coneLayer); this.coneLayer = null; }
        this.coneHalfAngle = null;
        this.coneDistanceKm = null;
        this.dimState = {};
        this.dimPending = {};
        this.updateReportsOpacity();
      }
    },
    /** Recentre la carte sur le bateau en plaçant l'icône :
     *  • horizontalement au milieu de l'écran,
     *  • verticalement à 60 % depuis le haut (= 3/5).
     *  Le décalage tient compte de la rotation course-up active. */
    recenterOnUser: function(animate){
      if (!userMarker) return;
      var ll = userMarker.getLatLng();
      var z = map.getZoom();
      var center;
      if (this.navMode){
        var vh = window.innerHeight;
        var bearing = this.bearing || 0;
        var rad = bearing * Math.PI / 180;
        // Décalage en pixels (dans le repère du div carte, non-tourné) :
        // on veut placer le marqueur 10 % vh sous le centre du viewport.
        var V = vh * 0.10;
        var dx = -V * Math.sin(rad);
        var dy =  V * Math.cos(rad);
        var p = map.project(ll, z).subtract(L.point(dx, dy));
        center = map.unproject(p, z);
      } else {
        center = ll;
      }
      this.programmaticMove = true;
      try {
        map.setView(center, z, { animate: animate !== false, duration: 0.45 });
      } finally {
        var self = this;
        setTimeout(function(){ self.programmaticMove = false; }, 600);
      }
    },
    /** Phase I (v5) — Rotate the map smoothly so the heading points UP.
     *  We accumulate the rotation continuously (no mod-360 reset) so the
     *  CSS transition always animates the SHORTEST arc — fixes the 359°→1°
     *  glitch that previously made the map spin 358° backwards. */
    bearingApplied: 0,
    setBearing: function(deg){
      var el = document.getElementById('map');
      if (!el) return;
      if (typeof deg !== 'number'){
        this.bearing = null;
        this.bearingApplied = 0;
        el.style.transform = 'translate(-50%, -50%)';
        el.style.setProperty('--sm-counter', '0deg');
      } else {
        // Shortest delta between the current applied angle (mod 360) and the
        // new target. Result lies in (-180, 180].
        var cur = ((this.bearingApplied % 360) + 360) % 360;
        var delta = ((deg - cur + 540) % 360) - 180;
        this.bearingApplied += delta;
        this.bearing = deg;
        el.style.transform = 'translate(-50%, -50%) rotate(' + (-this.bearingApplied) + 'deg)';
        el.style.setProperty('--sm-counter', this.bearingApplied + 'deg');
      }
      // Re-render the boat so its inline rotation (= heading - bearing)
      // converges to 0 in course-up mode and the triangle stays straight up.
      if (userMarker && this.userIsBoat){
        var ll = userMarker.getLatLng();
        this.setUser(ll.lat, ll.lng, this.userHeading, this.userSpeed, true);
      }
      // La rotation change la portion de carte sous les règles → recalcul.
      if (window.__updateRulers) window.__updateRulers();
    },
    setUser: function(lat,lng,heading,speed,asBoat){
      var hd = (typeof heading === 'number' && heading >= 0) ? heading : this.userHeading;
      var sp = (typeof speed === 'number' && speed >= 0) ? speed : this.userSpeed;
      // Phase J — jitter gate. En mode bateau (navigation), si la vitesse
      // est sous 1 nœud :
      //   • on FIGE le cap au dernier cap fiable,
      //   • on FIGE LA POSITION sur la dernière position fiable enregistrée
      //     (sinon le marker dérive de 5-15 m à cause du bruit GPS et fait
      //     vibrer toute la carte via le follow-mode).
      if (asBoat) {
        var fastEnough = (typeof sp === 'number' && sp >= this.MIN_NAV_SPEED_MS);
        if (fastEnough) {
          this.lastReliablePos = { lat: lat, lng: lng };
          if (typeof hd === 'number' && hd >= 0) this.lastHeadingApplied = hd;
        } else {
          if (this.lastReliablePos) {
            lat = this.lastReliablePos.lat;
            lng = this.lastReliablePos.lng;
          } else {
            // Premier fix reçu en nav mode mais sans vitesse — on l'accepte
            // comme position de référence pour bloquer les suivants.
            this.lastReliablePos = { lat: lat, lng: lng };
          }
          if (this.lastHeadingApplied != null) hd = this.lastHeadingApplied;
        }
      }
      this.userHeading = hd;
      this.userSpeed = sp;
      // In course-up mode the container is already rotated by -bearing, so
      // the boat's inner triangle just needs to undo that to point straight
      // up. Math: screen-rot = -bearing + counter + inline-rot = inline-rot.
      // We want screen-rot = 0 → inline-rot = bearing. Wait — let me redo:
      //   container: rotate(-bearing)
      //   .sm-boat-wrap: rotate(+bearing) (via --sm-counter, cancels container)
      //   .sm-boat: rotate(inline)  → net screen rot = inline
      // To point along heading (screen-up when bearing=heading) we want
      // inline = heading - bearing. ✅
      var rot = (hd != null) ? (hd - (this.bearing || 0)) : 0;
      var iconSize = asBoat ? [40,40] : [18,18];
      var anchor   = asBoat ? [20,20] : [9,9];
      var html;
      if (asBoat) {
        html = '<div class="sm-boat-wrap">'
             + '<div class="sm-boat-halo"></div>'
             + '<div class="sm-boat" style="transform:rotate('+rot+'deg)"></div>'
             + '</div>';
      } else {
        html = '<div class="sm-user"></div>';
      }
      var icon = L.divIcon({className:'',html:html,iconSize:iconSize,iconAnchor:anchor});
      if (userMarker && this.userIsBoat !== asBoat) {
        map.removeLayer(userMarker);
        userMarker = null;
      }
      if (userMarker) {
        userMarker.setLatLng([lat,lng]);
        userMarker.setIcon(icon);
      } else {
        userMarker = L.marker([lat,lng], {icon:icon, zIndexOffset:1000, interactive:false}).addTo(map);
      }
      this.userIsBoat = !!asBoat;
      // Projection line — only visible in Navigation mode (yellow cone active).
      // Delegated to refreshTrail() so setNavCone can also update it when the
      // user toggles the mode without waiting for the next GPS tick.
      this.refreshTrail();
      // Recentrage automatique (10/07/2026) — Vigie ET Navigation :
      // l'utilisateur peut consulter librement la carte ; 5 s après la FIN
      // de son geste (dragend/zoomend — plus le début comme avant), la
      // carte se recentre sur le bateau à chaque tick GPS. Jamais pendant
      // un drag en cours ni en mode placement de signalement (croix rouge).
      // recenterOnUser gère la différence : Vigie = centré, Nav = ancrage 3/5.
      if (asBoat && !this.userDragging && !this.crosshairOn &&
          (Date.now() - this.lastUserPan) >= 5000) {
        this.recenterOnUser(true);
      }
      // Phase K — Redraw the yellow navigation cone at the new position/
      // heading, and refresh the outside-cone opacity on every report.
      this.drawCone();
      this.updateReportsOpacity();
      // Phase K.5 — Keep the radar ping centred on the boat. If the marker
      // was just (re)created (e.g. after a Vigie/Nav toggle or first fix),
      // ensure the rings are (re)drawn — updateRadarPingPos is a no-op when
      // no layers exist yet.
      if (!this.pingLayers) this.drawRadarPing();
      else this.updateRadarPingPos();
    },
    /** Phase I — clear the projection line and reset to the legacy blue dot. */
    clearBoat: function(){
      if (this.userTrail){ map.removeLayer(this.userTrail); this.userTrail = null; }
      if (this.coneLayer){ map.removeLayer(this.coneLayer); this.coneLayer = null; }
      // We DON'T remove userMarker — the dot variant takes its place via the
      // next setUser() call. If the marker exists as a boat, swap it.
    },
    setReports: function(list){
      // Phase K — Remember the reports so updateReportsOpacity() can iterate
      // in place after each GPS tick without needing to rebuild anything.
      this.currentReports = list || [];
      var keep = {};
      var keepArrows = {};
      var keepCones = {};
      for (var i=0;i<list.length;i++){
        var r = list[i];
        keep[r.id] = true;
        // ---- Drift cone (Phase B) -------------------------------------
        // Drawn first so the marker icon visually sits on top of it.
        if (r.drift_cone && r.drift_cone.polygon && r.drift_cone.polygon.length >= 3
            && r.drift_cone.distance_km > 0.005){
          keepCones[r.id] = true;
          var pts = r.drift_cone.polygon.map(function(p){ return [p.lat, p.lng]; });
          // Arc middle & apex from the polygon vertices (robust for legacy
          // reports missing r.drift_cone.bearing_deg).
          var arcMidIdx = Math.floor((pts.length - 1) / 2) + 1;
          if (arcMidIdx >= pts.length) arcMidIdx = pts.length - 1;
          var apex = pts[0];
          var arcMid = pts[arcMidIdx];
          // Label right at the arc extremity (92% along the axis) — user
          // requested the text to hug the outer edge, not the middle.
          var lblLat = apex[0] + (arcMid[0] - apex[0]) * 0.92;
          var lblLng = apex[1] + (arcMid[1] - apex[1]) * 0.92;
          var popupLat = arcMid[0], popupLng = arcMid[1];
          // Compute the *screen*-space rotation so the text runs PARALLEL
          // to the arc (perpendicular to the drift bearing). We use a
          // Mercator-flat approximation which is more than accurate enough
          // over a ~10 km cone.
          var latAvg = (apex[0] + arcMid[0]) / 2;
          var dxScr = (arcMid[1] - apex[1]) * Math.cos(latAvg * Math.PI / 180);
          var dyScr = -(arcMid[0] - apex[0]); // screen Y grows downward
          // Bearing measured clockwise from screen-up (north).
          var bearingScr = Math.atan2(dxScr, -dyScr) * 180 / Math.PI;
          // Text parallel to arc = same angle. Normalize so it stays upright
          // (never printed upside-down).
          var textRot = bearingScr;
          while (textRot >  90) textRot -= 180;
          while (textRot < -90) textRot += 180;
          textRot = Math.round(textRot);
          // Only show the label when the arc is wide enough on screen to
          // fit the text — otherwise it overflows the cone which looks bad.
          // We measure the arc's outer chord in *pixels* via the current
          // map projection, then compare it against the label width.
          var LBL_TEXT = 'Position dans +/- 1 h';
          var LBL_FONT_PX = 11;        // matches CSS .sm-cone-label font-size
          var labelPxW = Math.max(120, LBL_TEXT.length * (LBL_FONT_PX * 0.55) + 20);
          var arcChordPx = 0;
          try {
            var arcStart = pts[1] || arcMid;
            var arcEnd = pts[pts.length - 1] || arcMid;
            var p1 = map.latLngToLayerPoint(arcStart);
            var p2 = map.latLngToLayerPoint(arcEnd);
            arcChordPx = Math.hypot(p2.x - p1.x, p2.y - p1.y);
          } catch(_){ arcChordPx = 0; }
          var showLabel = map.getZoom() >= 13 && arcChordPx >= labelPxW * 0.85;
          var lblHtml = '<span class="sm-cone-label" style="transform:rotate(' + textRot + 'deg)">' + LBL_TEXT + '</span>';

          // Popup content — always built from THIS cone's data.
          var popupParts = ['<b>Cône de dérive</b>'];
          if (typeof r.drift_cone.distance_km === 'number'){
            var km = r.drift_cone.distance_km < 1
              ? Math.round(r.drift_cone.distance_km * 1000) + ' m'
              : r.drift_cone.distance_km.toFixed(2) + ' km';
            popupParts.push('Position estimée à ~ 1 h : <b>' + km + '</b>');
          }
          if (typeof r.drift_cone.bearing_deg === 'number'){
            popupParts.push('Cap : <b>' + Math.round(r.drift_cone.bearing_deg) + '°</b>');
          }
          if (r.drift_cone.wind_source){
            popupParts.push('Vent : ' + r.drift_cone.wind_source);
          }
          // Bande côtière < 20 km (13/07/2026) : courant modèle non fiable →
          // dérive au vent seul + avertissement clair au clic sur le cône.
          if (r.drift_cone.wind_only){
            popupParts.push('<span class="sm-cone-warn">\u26A0\uFE0F Dérive estimée uniquement avec les valeurs des vents sur le secteur, utilisez vos connaissances des courants locaux pour affiner l\u2019estimation de la direction de dérive de l\u2019objet.</span>');
          }
          var popupContent = popupParts.join('<br/>');

          if (cones[r.id]){
            // Legacy migration: old polygons were created before the E.6c fix
            // (bubblingMouseEvents:false + arc-mid manual popup). They still
            // exhibit the "popup on wrong cone" bug because their options are
            // frozen at creation time. Detect that case and force a full
            // rebuild — new polygons flow through the else-branch below.
            if (cones[r.id].poly && cones[r.id].poly.options
                && cones[r.id].poly.options.bubblingMouseEvents !== false){
              try { map.removeLayer(cones[r.id].poly); } catch(_){}
              if (cones[r.id].label){
                try { map.removeLayer(cones[r.id].label); } catch(_){}
              }
              delete cones[r.id];
            }
          }
          if (cones[r.id]){
            cones[r.id].poly.setLatLngs(pts);
            cones[r.id].popupLatLng = [popupLat, popupLng];
            cones[r.id].popupContent = popupContent;
            cones[r.id].arcChordPx = arcChordPx;
            if (cones[r.id].label){
              cones[r.id].label.setLatLng([lblLat, lblLng]);
              cones[r.id].label.setIcon(L.divIcon({
                className: 'sm-cone-label-wrap', html: lblHtml,
                iconSize: [labelPxW, 22], iconAnchor: [labelPxW / 2, 11],
              }));
              if (showLabel) cones[r.id].label.addTo(map);
              else map.removeLayer(cones[r.id].label);
            } else if (showLabel) {
              cones[r.id].label = L.marker([lblLat, lblLng], {
                icon: L.divIcon({
                  className: 'sm-cone-label-wrap', html: lblHtml,
                  iconSize: [labelPxW, 22], iconAnchor: [labelPxW / 2, 11],
                }),
                interactive: false, keyboard: false, zIndexOffset: 800,
              }).addTo(map);
            }
          } else {
            var poly = L.polygon(pts, {
              color: '#FF6F1A', weight: 3, opacity: 1, dashArray: '8,5',
              fillColor: '#FFA94D', fillOpacity: 0.4,
              // Polygon does NOT intercept clicks — the map-level handler
              // below does the geometric hit-testing itself. This is the
              // only way to guarantee that a tap physically inside cone A's
              // polygon opens A's popup (and not a sibling B's, no matter
              // how they are stacked in Leaflet's render order).
              interactive: false,
              className: 'sm-drift-cone',
              bubblingMouseEvents: false,
            }).addTo(map);
            // Bind the report id on the polygon so the map-level click
            // handler can look up the correct popup content by id.
            poly._smReportId = r.id;
            var coneEntry = {
              poly: poly, label: null,
              reportId: r.id,
              popupLatLng: [popupLat, popupLng],
              popupContent: popupContent,
            };
            // Click handling is done at the map level via geometric
            // hit-testing (see map.on('click', ...) below). No per-polygon
            // handler here — that avoids the whole class of overlap bugs.
            if (showLabel) {
              coneEntry.label = L.marker([lblLat, lblLng], {
                icon: L.divIcon({
                  className: 'sm-cone-label-wrap', html: lblHtml,
                  iconSize: [labelPxW, 22], iconAnchor: [labelPxW / 2, 11],
                }),
                interactive: false, keyboard: false, zIndexOffset: 800,
              }).addTo(map);
            }
            cones[r.id] = coneEntry;
            try { poly.bringToBack(); } catch(_){}
          }
        }
        var color = r.color || '#48CAE4';
        var focusClass = r.focus ? ' sm-marker-focus' : '';
        var compactClass = (map.getZoom() < 12) ? ' sm-compact' : '';
        var emoji = TYPE_ICON[r.label] || (r.label || '?').charAt(0).toUpperCase();
        // Phase E.6 — removed the sm-galon (rank glyph) + sm-rel (reliability
        // score) overlays from the map pins. They cluttered the pin, forced
        // odd icon offsets, and often produced a stray "●" or "100" bubble
        // even when the underlying rank was unknown. The full grade and
        // reliability are still visible on the report detail screen.
        var galon = '';
        var rel = '';
        var pinHtml = '<div class="sm-hit"><div class="sm-pin'+focusClass+compactClass+'" style="background:'+color+'">'
                    + '<span class="sm-emoji">'+emoji+'</span>'+galon+rel+'</div></div>';
        if (markers[r.id]){
          markers[r.id].setLatLng([r.lat, r.lng]);
          // Anti-flash (14/07/2026) : ne remplacer l'élément DOM de l'icône
          // que si son HTML a réellement changé (focus, zoom compact…) —
          // recréer le nœud à chaque poll provoquait un bref clignotement
          // (l'état grisé était perdu puis ré-appliqué).
          if (markers[r.id]._smPinHtml !== pinHtml){
            markers[r.id].setIcon(L.divIcon({className:'',html:pinHtml,iconSize:[54,54],iconAnchor:[27,27]}));
            markers[r.id]._smPinHtml = pinHtml;
          }
        } else {
          var icon = L.divIcon({className:'',html:pinHtml,iconSize:[54,54],iconAnchor:[27,27]});
          var m = L.marker([r.lat, r.lng], {icon:icon, riseOnHover:true}).addTo(map);
          m._smPinHtml = pinHtml;
          m.on('click', function(id){ return function(e){
            if (e && L.DomEvent) L.DomEvent.stopPropagation(e);
            postMsg({event:'marker', id:id});
          }; }(r.id));
          markers[r.id] = m;
        }
        // Heading / speed vector for authority + navigation reports.
        if (r.heading != null && r.speed_knots != null && r.speed_knots > 0){
          keepArrows[r.id] = true;
          // 5-minute projection in km: speed_kn * 1.852 / 12.
          var distKm = Math.max(0.3, Math.min(8, r.speed_knots * 1.852 / 12));
          var end = destPoint(r.lat, r.lng, r.heading, distKm);
          if (arrows[r.id]){
            arrows[r.id].line.setLatLngs([[r.lat, r.lng], end]);
            arrows[r.id].tip.setLatLng(end);
            arrows[r.id].tip.setIcon(L.divIcon({className:'',
              html:'<div class="sm-arrow-tip" style="background:'+color+';transform:rotate('+r.heading+'deg)">▲</div>',
              iconSize:[18,18], iconAnchor:[9,9]}));
          } else {
            var line = L.polyline([[r.lat, r.lng], end], {color: color, weight: 3, opacity: 0.85, dashArray: '6,4'}).addTo(map);
            var tip = L.marker(end, {icon: L.divIcon({className:'',
              html:'<div class="sm-arrow-tip" style="background:'+color+';transform:rotate('+r.heading+'deg)">▲</div>',
              iconSize:[18,18], iconAnchor:[9,9]})}).addTo(map);
            arrows[r.id] = { line: line, tip: tip };
          }
        }
      }
      var self2 = this;
      Object.keys(markers).forEach(function(id){
        if (!keep[id]){
          map.removeLayer(markers[id]); delete markers[id];
          delete self2.dimState[id]; delete self2.dimPending[id];
        }
      });
      Object.keys(arrows).forEach(function(id){
        if (!keepArrows[id]){
          map.removeLayer(arrows[id].line);
          map.removeLayer(arrows[id].tip);
          delete arrows[id];
        }
      });
      Object.keys(cones).forEach(function(id){
        if (!keepCones[id]){
          try { map.removeLayer(cones[id].poly); } catch(_){}
          if (cones[id].label){ try { map.removeLayer(cones[id].label); } catch(_){} }
          delete cones[id];
        }
      });
      // Phase K — Refresh per-marker opacity so newly-added reports get their
      // cone-inclusion state applied instantly (no waiting for next GPS tick).
      this.updateReportsOpacity();
    }
  };

  map.on('moveend', function(){
    var c = map.getCenter();
    postMsg({event:'move', lat:c.lat, lng:c.lng, zoom: map.getZoom()});
  });
  // Phase J — détection d'INTERACTION utilisateur (pan / zoom à la main).
  // Ces évènements ne sont déclenchés QUE par les gestes humains, jamais par
  // map.setView() programmatique → c'est un détecteur fiable de "main
  // levée". Le chrono de 5 s du recentrage automatique repart à la FIN du
  // geste (dragend/zoomend) — pas au début — pour laisser consulter la carte.
  map.on('dragstart', function(){
    window.SM.userDragging = true;
    window.SM.lastUserPan = Date.now();
  });
  map.on('dragend', function(){
    window.SM.userDragging = false;
    window.SM.lastUserPan = Date.now();
  });
  map.on('zoomstart', function(){
    // Le zoom déclenché par les boutons +/- en bas-gauche est aussi un acte
    // volontaire → on le compte comme une interaction.
    if (!window.SM.programmaticMove) window.SM.lastUserPan = Date.now();
  });
  map.on('zoomend', function(){
    if (!window.SM.programmaticMove) window.SM.lastUserPan = Date.now();
  });
  // 13/07/2026 — TOUT contact tactile sur la carte (tap sur un marqueur
  // inclus) repousse le recentrage automatique de 5 s. Sans ça, le chrono
  // pouvait expirer PENDANT que le doigt visait un marqueur : la carte se
  // recentrait sous le doigt → mauvais signalement ouvert / « éjection ».
  (function(){
    var mc = document.getElementById('map');
    ['touchstart','mousedown','wheel'].forEach(function(evt){
      mc.addEventListener(evt, function(){
        window.SM.lastUserPan = Date.now();
      }, {passive:true, capture:true});
    });
  })();
  // Web bridge: listen to parent postMessage so SM.* calls execute on the iframe.
  window.addEventListener('message', function(e){
    var raw = e.data;
    if (typeof raw !== 'string') return;
    try {
      var d = JSON.parse(raw);
      if (d && d.__sm_eval) { (0,eval)(d.__sm_eval); }
    } catch(_){}
  });
  // ready
  setTimeout(function(){ postMsg({event:'ready'}); }, 200);
</script>
</body></html>`;
}

export const MarineMap = forwardRef<MarineMapHandle, Props>(function MarineMap(
  { center, zoom = 11, userLocation, userHeading, userSpeed, showBoat = true, coneHalfAngleDeg = null, coneDistanceKm = null, radarPingRadiusM = null, courseUp = false, reports, crosshair = false, focusId = null, onMarkerPress, onMapMoved, onMapLongPress, mapUnit = "km", onRulerTap },
  ref,
) {
  const webRef = useRef<WebView | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  // Compteur de mises à jour consécutives « en mouvement » avant d'autoriser
  // la rotation course-up (filtre les pics GPS du démarrage à froid).
  const courseUpStreakRef = useRef(0);
  const html = useMemo(() => buildHtml(center, zoom, crosshair), []); // eslint-disable-line react-hooks/exhaustive-deps

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
    grantRecenterGrace: () => sendJs(`window.SM && SM.grantGrace()`),
    setNavCone: (halfAngleDeg, distKm) => sendJs(
      `window.SM && SM.setNavCone(${halfAngleDeg == null ? "null" : halfAngleDeg},${distKm == null ? "null" : distKm})`,
    ),
    setRadarPing: (radiusM) => sendJs(
      `window.SM && SM.setRadarPing(${radiusM == null ? 0 : radiusM})`,
    ),
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
      const d = JSON.parse(raw) as { event?: string; id?: string; lat?: number; lng?: number };
      if (d.event === "marker" && d.id) onMarkerPress?.(d.id);
      else if (d.event === "move" && typeof d.lat === "number" && typeof d.lng === "number") {
        onMapMoved?.(d.lat, d.lng);
      } else if (d.event === "longpress" && typeof d.lat === "number" && typeof d.lng === "number") {
        onMapLongPress?.(d.lat, d.lng);
      } else if (d.event === "ruler_tap") {
        onRulerTap?.();
      } else if (d.event === "ready") {
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
          sendJs(`window.SM && SM.flyTo(${userLocation.lat},${userLocation.lng},12)`);
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
    <View style={styles.flex} testID="marine-map-native">
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
