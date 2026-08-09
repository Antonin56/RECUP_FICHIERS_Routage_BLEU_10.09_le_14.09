// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Marqueurs de signalement, cônes de dérive, hit-test, appui long.

export const JS_MARKERS = `  var markers = {};
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
    meteo:        '\u26C8',     // thunder cloud (24/07 — phénomènes météo)
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
    // 24/07 — clics déjà consommés par une balise / le tracé de route /
    // l'étiquette du compas de mesure.
    if (e.originalEvent && (e.originalEvent._smRouteTap || e.originalEvent._smHandled)) return;
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
    if (!matches.length){
      // 24/07/2026 (demande armateur) — CLIC COURT sur l'eau libre → hauteur
      // d'eau au point (fond carte + marée). RN décide d'afficher ou non
      // (ignoré pendant les modes visée/route manuelle).
      postMsg({ event: 'map_tap', lat: e.latlng.lat, lng: e.latlng.lng });
      return;
    }
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

`;
