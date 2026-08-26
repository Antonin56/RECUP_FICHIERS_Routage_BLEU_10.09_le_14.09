// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Route sûre, comparaison de moteurs, suivi, cap à suivre, mouillage, route manuelle, point de blocage.

export const JS_ROUTE = `  // ── N1 (20/07/2026) — ROUTE SÛRE calculée par le backend (A* sur MNT).
  // window.__setRoute(route|null) : trait rouge pointillé avec liseré blanc,
  // segments ORANGE là où la profondeur approche le seuil (< seuil + 0.5 m),
  // drapeaux départ/arrivée, fitBounds au premier affichage.
  var _routeLayer = L.layerGroup().addTo(map);
  var _routeKey = null;
  // 23/07/2026 — SUIVI DE ROUTE : tronçon parcouru grisé + waypoints grisés.
  var _progressLayer = L.layerGroup().addTo(map);
  var _routePts = [];
  var _routeWpMarkers = [];
  window.__setRoute = function(route){
    try {
      _routeLayer.clearLayers();
      _progressLayer.clearLayers();
      _routePts = [];
      _routeWpMarkers = [];
      if (!route || !route.waypoints || route.waypoints.length < 2){ _routeKey = null; return; }
      var pts = [];
      for (var i = 0; i < route.waypoints.length; i++){
        pts.push([route.waypoints[i].lat, route.waypoints[i].lng]);
      }
      _routePts = pts;
      L.polyline(pts, { color: '#FFFFFF', weight: 7, opacity: 0.85, interactive: false }).addTo(_routeLayer);
      // 29/07/2026 (décision armateur, façon Navionics) — trait PLEIN fushia
      // #e034de (plus de pointillés) : les zones à risques (rouge) ressortent
      // d'un coup d'œil.
      L.polyline(pts, { color: '#e034de', weight: 4, opacity: 0.95, interactive: false }).addTo(_routeLayer);
      // 21/07/2026 — tap sur le tracé → menu RN (Voir les détails /
      // Supprimer la route). Zone de tap invisible élargie (18 px).
      L.polyline(pts, { color: '#000', weight: 18, opacity: 0.01, interactive: true })
        .on('click', function(ev){
          if (ev.originalEvent){ ev.originalEvent._smRouteTap = true; }
          postMsg({ event: 'route_tap' });
        })
        .addTo(_routeLayer);
      // Zones limites (profondeur < seuil + 0.5 m) surlignées en orange.
      var prof = route.depth_profile || [];
      var warnAt = (typeof route.threshold_m === 'number' ? route.threshold_m : 2) + 0.5;
      var seg = [];
      function flush(){
        if (seg.length >= 2){
          L.polyline(seg, { color: '#F4A261', weight: 6, opacity: 0.9, interactive: false }).addTo(_routeLayer);
        }
        seg = [];
      }
      for (var j = 0; j < prof.length; j++){
        var p = prof[j];
        if (typeof p.lat === 'number' && p.depth_m != null && p.depth_m < warnAt){
          seg.push([p.lat, p.lng]);
        } else { flush(); }
      }
      flush();
      // 24/07/2026 (demande armateur) — zones dangereuses en ROUGE VIF.
      // 26/08/2026 (demande armateur) — ZONES ROUGES PRÉCISES : seuls les
      // échantillons du profil de profondeur SOUS le seuil sont peints en
      // rouge (plus le tronçon entier). Un tap sur une zone rouge envoie
      // route_tap AVEC l'info de hauteur d'eau → le menu RN affiche la
      // faible hauteur d'eau ET les options de la route.
      function _dangerTap(danger){
        return function(ev){
          if (ev.originalEvent){ ev.originalEvent._smRouteTap = true; }
          postMsg({ event: 'route_tap', danger: danger });
        };
      }
      function _dangerTri(latlng, danger){
        L.marker(latlng, {
          interactive: true, zIndexOffset: 1200,
          icon: L.divIcon({
            className: '', iconSize: [0, 0], iconAnchor: [0, 0],
            html: '<div class="sm-danger-tri">\u26A0</div>',
          }),
        }).on('click', _dangerTap(danger)).addTo(_routeLayer);
      }
      var thr = (typeof route.threshold_m === 'number') ? route.threshold_m : 2;
      var zones = [];
      var zpts = null, zmin = null;
      function _mid(a, b){ return [(a.lat + b.lat) / 2, (a.lng + b.lng) / 2]; }
      for (var q = 0; q < prof.length; q++){
        var pp = prof[q];
        var bad = (typeof pp.lat === 'number' && pp.depth_m != null && pp.depth_m < thr);
        if (bad){
          if (!zpts){
            zpts = [];
            if (q > 0) zpts.push(_mid(prof[q - 1], pp));
            zmin = pp.depth_m;
          }
          zpts.push([pp.lat, pp.lng]);
          if (pp.depth_m < zmin) zmin = pp.depth_m;
        } else if (zpts){
          if (typeof pp.lat === 'number') zpts.push(_mid(prof[q - 1], pp));
          if (zpts.length >= 2) zones.push({ pts: zpts, min: zmin });
          zpts = null; zmin = null;
        }
      }
      if (zpts && zpts.length >= 2) zones.push({ pts: zpts, min: zmin });
      for (var zi = 0; zi < zones.length; zi++){
        (function(z){
          var danger = { min_depth_m: z.min, threshold_m: thr, reason: 'shallow' };
          L.polyline(z.pts, {
            color: '#FF1744', weight: 6, opacity: 0.95,
            interactive: true, bubblingMouseEvents: false,
          }).on('click', _dangerTap(danger)).addTo(_routeLayer);
          _dangerTri(z.pts[Math.floor(z.pts.length / 2)], danger);
        })(zones[zi]);
      }
      // Tronçons compromis SANS zone précise correspondante (raison ≠ fond,
      // ex. marge latérale, ou profil muet) : tronçon entier conservé en
      // rouge — on ne perd JAMAIS un avertissement.
      var comp = route.compromised_legs || [];
      function _zoneNearLeg(a, b){
        for (var k2 = 0; k2 < zones.length; k2++){
          var zp = zones[k2].pts;
          for (var k3 = 0; k3 < zp.length; k3++){
            var okLat = Math.min(a[0], b[0]) - 0.001 <= zp[k3][0] && zp[k3][0] <= Math.max(a[0], b[0]) + 0.001;
            var okLng = Math.min(a[1], b[1]) - 0.0015 <= zp[k3][1] && zp[k3][1] <= Math.max(a[1], b[1]) + 0.0015;
            if (okLat && okLng) return true;
          }
        }
        return false;
      }
      for (var ci = 0; ci < comp.length; ci++){
        var li = comp[ci];
        if (li < 0 || li >= pts.length - 1) continue;
        var rs0 = (route.leg_reasons || {})[String(li)] || 'shallow';
        if (rs0 !== 'low_margin' && _zoneNearLeg(pts[li], pts[li + 1])) continue;
        (function(idx, rs){
          var danger = { min_depth_m: null, threshold_m: thr, reason: rs };
          L.polyline([pts[idx], pts[idx + 1]], {
            color: '#FF1744', weight: 6, opacity: 0.95,
            interactive: true, bubblingMouseEvents: false,
          }).on('click', _dangerTap(danger)).addTo(_routeLayer);
          _dangerTri([
            (pts[idx][0] + pts[idx + 1][0]) / 2,
            (pts[idx][1] + pts[idx + 1][1]) / 2,
          ], danger);
        })(li, rs0);
      }
      // Départ (rond vert) / arrivée (drapeau).
      L.circleMarker(pts[0], { radius: 7, color: '#fff', weight: 2, fillColor: '#2EC4B6', fillOpacity: 1, interactive: false }).addTo(_routeLayer);
      L.marker(pts[pts.length - 1], {
        interactive: false,
        icon: L.divIcon({ className: '', html: '<div style="font-size:22px;line-height:22px;text-shadow:0 1px 3px rgba(0,0,0,.5)">🏁</div>', iconSize: [24, 24], iconAnchor: [4, 22] }),
      }).addTo(_routeLayer);
      // 22/07/2026 — ARRIVÉE DÉPLACÉE (end_snapped) : la destination demandée
      // n'était pas navigable, la route s'arrête à l'eau saine la plus proche.
      // Pointillé discret + repère creux sur le point DEMANDÉ + distance.
      var es = route.end_snapped;
      if (es && es.requested && typeof es.requested.lat === 'number'){
        var req = [es.requested.lat, es.requested.lng];
        L.polyline([pts[pts.length - 1], req], {
          color: '#F4A261', weight: 2.5, opacity: 0.9, dashArray: '3 8',
          interactive: false,
        }).addTo(_routeLayer);
        L.circleMarker(req, {
          radius: 7, color: '#F4A261', weight: 2.5, fillColor: '#F4A261',
          fillOpacity: 0.15, interactive: false,
        }).addTo(_routeLayer);
        var offTxt = es.offset_m >= 1000
          ? (es.offset_m / 1000).toFixed(1).replace('.', ',') + ' km'
          : Math.round(es.offset_m) + ' m';
        L.marker(req, {
          interactive: false,
          icon: L.divIcon({
            className: '',
            html: '<div class="sm-tag-anchor"><div class="sm-tag sm-tag--warn" style="transform:translate(-50%,12px);">reste ' + offTxt + ' \u00e0 vue</div></div>',
            iconSize: [0, 0], iconAnchor: [0, 0],
          }),
        }).addTo(_routeLayer);
      }
      // 23/07 — WAYPOINTS intermédiaires : 29/07 (décision armateur) —
      // visibles UNIQUEMENT sur les routes MANUELLES (points créés par
      // l'utilisateur) ; la route AUTO est un trait pur, sans points de
      // changement de cap. Grisés au passage (__setRouteProgress).
      if (route.mode === 'manual' && pts.length <= 200){
        for (var w = 1; w < pts.length - 1; w++){
          _routeWpMarkers[w] = L.circleMarker(pts[w], {
            radius: 4.5, color: '#fff', weight: 1.5,
            fillColor: '#e034de', fillOpacity: 1, interactive: false,
          }).addTo(_routeLayer);
        }
      }
      // fitBounds seulement quand la route CHANGE (pas au ré-émis 'ready').
      var key = pts[0].join(',') + '|' + pts[pts.length - 1].join(',') + '|' + pts.length;
      if (key !== _routeKey){
        _routeKey = key;
        map.fitBounds(L.latLngBounds(pts), { padding: [46, 46], maxZoom: 15 });
      }
    } catch(_){}
  };
  // ── 02/08/2026 (demande armateur) — COMPARAISON A/B DE MOTEURS.
  // window.__setRouteCompare(c|null) où
  //   c = { key, base: {waypoints, label, color, anchor},
  //         variant: {waypoints, label, color, anchor},
  //         diff_base: [[{lat,lng}…]…], diff_variant: [[…]…] }
  // La route de RÉFÉRENCE reste tracée par __setRoute ; on superpose ici la
  // VARIANTE (trait ambre pointillé) et on SURLIGNE les portions divergentes
  // des deux tracés, avec une étiquette « moteur · ID » sur chacun.
  var _compareLayer = L.layerGroup().addTo(map);
  var _compareKey = null;
  window.__setRouteCompare = function(c){
    try {
      _compareLayer.clearLayers();
      if (!c || !c.variant || !c.variant.waypoints || c.variant.waypoints.length < 2){
        _compareKey = null; return;
      }
      function toPts(w){
        var a = [];
        for (var i = 0; i < w.length; i++){ a.push([w[i].lat, w[i].lng]); }
        return a;
      }
      var baseCol = (c.base && c.base.color) || '#e034de';
      var varCol = c.variant.color || '#FFB703';
      var vp = toPts(c.variant.waypoints);
      // Surlignage des ÉCARTS (halo épais) — d'abord, pour rester sous les traits.
      var k, s;
      var db = c.diff_base || [];
      for (k = 0; k < db.length; k++){
        s = toPts(db[k]);
        if (s.length >= 2){
          L.polyline(s, { color: baseCol, weight: 14, opacity: 0.30, interactive: false }).addTo(_compareLayer);
        }
      }
      var dv = c.diff_variant || [];
      for (k = 0; k < dv.length; k++){
        s = toPts(dv[k]);
        if (s.length >= 2){
          L.polyline(s, { color: varCol, weight: 14, opacity: 0.34, interactive: false }).addTo(_compareLayer);
        }
      }
      // Tracé de la VARIANTE : liseré sombre + pointillé ambre.
      L.polyline(vp, { color: '#04121F', weight: 7, opacity: 0.7, interactive: false }).addTo(_compareLayer);
      L.polyline(vp, { color: varCol, weight: 4, opacity: 0.97, dashArray: '11 7', interactive: false }).addTo(_compareLayer);
      L.circleMarker(vp[vp.length - 1], {
        radius: 5, color: '#fff', weight: 2, fillColor: varCol, fillOpacity: 1, interactive: false,
      }).addTo(_compareLayer);
      // Étiquettes « moteur · ID » sur chaque tracé.
      function tag(pt, text, bg){
        L.marker(pt, {
          interactive: false, zIndexOffset: 1500,
          icon: L.divIcon({
            className: '', iconSize: [0, 0], iconAnchor: [0, 0],
            html: '<div class="sm-tag-anchor"><div class="sm-eng-tag" style="background:' + bg + '">' + text + '</div></div>',
          }),
        }).addTo(_compareLayer);
      }
      if (c.base && c.base.anchor && c.base.label){
        tag([c.base.anchor.lat, c.base.anchor.lng], c.base.label, baseCol);
      }
      if (c.variant.anchor && c.variant.label){
        tag([c.variant.anchor.lat, c.variant.anchor.lng], c.variant.label, varCol);
      }
      // Cadrage sur l'union des deux tracés, une seule fois par comparaison.
      if (c.key && c.key !== _compareKey){
        _compareKey = c.key;
        var all = vp.slice();
        if (c.base && c.base.waypoints){ all = all.concat(toPts(c.base.waypoints)); }
        map.fitBounds(L.latLngBounds(all), { padding: [50, 50], maxZoom: 15 });
      }
    } catch(_){}
  };
  // ── 23/07/2026 — SUIVI DE ROUTE : window.__setRouteProgress(p|null).
  // p = { passedIdx, lat, lng } : index du dernier waypoint DÉPASSÉ +
  // projection du bateau sur la route. Le tronçon parcouru est recouvert
  // d'une polyligne GRISE et les waypoints passés deviennent gris.
  window.__setRouteProgress = function(p){
    try {
      _progressLayer.clearLayers();
      var i;
      if (!p || !_routePts.length){
        for (i = 0; i < _routeWpMarkers.length; i++){
          if (_routeWpMarkers[i]) _routeWpMarkers[i].setStyle({ fillColor: '#e034de', fillOpacity: 1 });
        }
        return;
      }
      var idx = Math.max(-1, Math.min(_routePts.length - 1, p.passedIdx));
      var done = _routePts.slice(0, idx + 1);
      if (typeof p.lat === 'number' && typeof p.lng === 'number') done.push([p.lat, p.lng]);
      if (done.length >= 2){
        // Gris SOLIDE par-dessus le liseré blanc + rouge pointillé.
        L.polyline(done, { color: '#0B132B', weight: 8, opacity: 0.55, interactive: false }).addTo(_progressLayer);
        L.polyline(done, { color: '#9AA5B1', weight: 4, opacity: 0.95, interactive: false }).addTo(_progressLayer);
      }
      for (i = 0; i < _routeWpMarkers.length; i++){
        if (!_routeWpMarkers[i]) continue;
        if (i <= idx) _routeWpMarkers[i].setStyle({ fillColor: '#9AA5B1', fillOpacity: 0.85 });
        else _routeWpMarkers[i].setStyle({ fillColor: '#e034de', fillOpacity: 1 });
      }
    } catch(_){}
  };
  // ── 28/07/2026 — CAP À SUIVRE : window.__setTargetBearing(deg|null).
  // Projection VERT FONCÉ clonée de la projection de cap, affichée pendant
  // la navigation d'une route (tap → étiquette « Cap à suivre »).
  window.__setTargetBearing = function(deg){
    try {
      SM.targetBearing = (typeof deg === 'number' && isFinite(deg)) ? deg : null;
      SM.refreshTargetTrail();
    } catch(_){}
  };
  // ── 28/07/2026 — PROJECTION DE CAP RÉEL (rouge) : window.__setHeadingLine.
  // Forcée à true en mode Navigation ET pendant le suivi de route (la ligne
  // rouge accompagne alors la ligne verte « cap à suivre »).
  window.__setHeadingLine = function(on){
    try {
      SM.headingLineOn = !!on;
      SM.refreshTrail();
    } catch(_){}
  };
  // ── 23/07/2026 — ALARME DE MOUILLAGE : cercle de garde autour de l'ancre.
  // window.__setAnchor({lat,lng,radiusM,alarm}|null). Teal à l'ancre,
  // ROUGE pulsant si le bateau a dérivé hors du rayon (alarm=true).
  var _anchorLayer = L.layerGroup().addTo(map);
  window.__setAnchor = function(a){
    try {
      _anchorLayer.clearLayers();
      if (!a || typeof a.lat !== 'number' || typeof a.lng !== 'number') return;
      var col = a.alarm ? '#E5383B' : '#2EC4B6';
      L.circle([a.lat, a.lng], {
        radius: Math.max(1, Number(a.radiusM) || 15),
        color: col, weight: 2, dashArray: '6 5',
        fillColor: col, fillOpacity: 0.10, interactive: false,
      }).addTo(_anchorLayer);
      L.marker([a.lat, a.lng], {
        interactive: false,
        icon: L.divIcon({
          className: '',
          html: '<div class="sm-anchor' + (a.alarm ? ' sm-anchor--alarm' : '') + '">⚓</div>',
          iconSize: [28, 28], iconAnchor: [14, 14],
        }),
      }).addTo(_anchorLayer);
    } catch(_){}
  };
  // ── 22/07/2026 — ROUTE MANUELLE en cours de création : polyline teal
  // pointillée + waypoints numérotés. window.__setDraftRoute(points|null).
  var _draftLayer = L.layerGroup().addTo(map);
  window.__setDraftRoute = function(points, editIdx){
    try {
      _draftLayer.clearLayers();
      if (!points || !points.length) return;
      var pts = [];
      for (var i = 0; i < points.length; i++) pts.push([points[i].lat, points[i].lng]);
      if (pts.length >= 2){
        L.polyline(pts, { color: '#FFFFFF', weight: 6, opacity: 0.7, interactive: false }).addTo(_draftLayer);
        L.polyline(pts, { color: '#2EC4B6', weight: 3, opacity: 0.95, dashArray: '8 6', interactive: false }).addTo(_draftLayer);
      }
      var hasEdit = (typeof editIdx === 'number');
      for (var k = 0; k < pts.length; k++){
        // 22/07/2026 (demande armateur) — points DÉPLAÇABLES (drag & drop).
        // 11/08 (règle armateur) — en ÉDITION, SEUL le waypoint sélectionné
        // (editIdx) est déplaçable et numéroté ; les autres deviennent de
        // simples repères (lisibilité + ajustement fin).
        (function(idx){
          if (hasEdit && idx !== editIdx){
            L.marker(pts[idx], {
              interactive: false,
              icon: L.divIcon({ className: '', html: '<div class="sm-wp-dot"></div>', iconSize: [12, 12], iconAnchor: [6, 6] }),
            }).addTo(_draftLayer);
            return;
          }
          var cls = hasEdit ? 'sm-wp-num sm-wp-edit' : 'sm-wp-num';
          var mk = L.marker(pts[idx], {
            draggable: true,
            icon: L.divIcon({ className: '', html: '<div class="' + cls + '">' + (idx + 1) + '</div>', iconSize: [26, 26], iconAnchor: [13, 13] }),
          });
          mk.on('dragend', function(){
            var ll = mk.getLatLng();
            postMsg({ event: 'draft_move', index: idx, lat: ll.lat, lng: ll.lng });
          });
          mk.addTo(_draftLayer);
        })(k);
      }
    } catch(_){}
  };
  // ── 22/07/2026 — POINT DE BLOCAGE (route impossible) : cercle rouge
  // pulsant + tronçon ATTEIGNABLE en pointillé gris. La route existante
  // n'est JAMAIS effacée (demande armateur). __setBlocked(payload|null).
  var _blockedLayer = L.layerGroup().addTo(map);
  window.__setBlocked = function(p){
    try {
      _blockedLayer.clearLayers();
      if (!p || !p.blocked_at) return;
      var partial = p.partial_waypoints || [];
      if (partial.length >= 2){
        var pts = [];
        for (var i = 0; i < partial.length; i++) pts.push([partial[i].lat, partial[i].lng]);
        L.polyline(pts, { color: '#9AA5B1', weight: 3, opacity: 0.85, dashArray: '4 7', interactive: false }).addTo(_blockedLayer);
      }
      var at = [p.blocked_at.lat, p.blocked_at.lng];
      L.marker(at, {
        interactive: false,
        icon: L.divIcon({ className: '', html: '<div class="sm-blocked"><div class="ring"></div><div class="core"></div></div>', iconSize: [34, 34], iconAnchor: [17, 17] }),
      }).addTo(_blockedLayer);
      // 23/07 — étiquette explicite sous le cercle (l'armateur ne voyait pas
      // le point : petit anneau perdu parmi les marqueurs de signalement).
      L.marker(at, {
        interactive: false,
        icon: L.divIcon({
          className: '',
          html: '<div class="sm-tag-anchor"><div class="sm-tag sm-tag--danger" style="transform:translate(-50%,16px);">Blocage ici</div></div>',
          iconSize: [0, 0], iconAnchor: [0, 0],
        }),
      }).addTo(_blockedLayer);
      // 23/07 — recadrage GARANTI : le blocage était souvent HORS ÉCRAN.
      // fitBounds sur le tronçon atteignable + le point de blocage (vue
      // d'ensemble du « mur »), sinon flyTo sur le point seul.
      if (partial.length >= 2){
        var bb = L.latLngBounds(pts); bb.extend(at);
        map.fitBounds(bb, { padding: [70, 70], maxZoom: 14 });
      } else {
        map.flyTo(at, Math.max(map.getZoom(), 12), { duration: 0.8 });
      }
    } catch(_){}
  };
`;
