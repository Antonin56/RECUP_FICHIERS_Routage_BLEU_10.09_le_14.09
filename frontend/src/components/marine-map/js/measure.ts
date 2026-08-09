// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Compas de mesure A→B avec magnétisme.

export const JS_MEASURE = `  // ── 24/07/2026 — COMPAS DE MESURE (demande armateur) ─────────────────
  // Segment A→B déplaçable, distance au mètre près + relèvement vrai.
  // MAGNÉTISME pendant le drag : bateau, balises/roches/épaves (marks
  // ingérés), signalements, tracé de la route (point PROJETÉ sur le
  // segment le plus proche). Une extrémité lâchée sur le BATEAU le suit
  // ensuite en temps réel (mesure dynamique des écarts). Tap sur la
  // carte de mesure → bascule mètres ⇄ NM.
  var _msOn = false, _msLayer = null, _msPins = { A: null, B: null },
      _msLine = null, _msHalo = null, _msLabel = null, _msUnit = 'm',
      _msMagnet = { A: null, B: null }, _msSnapState = { A: false, B: false };
  var _MS_SNAP_PX = 30;

  function _msPinIcon(snapped, letter, boat){
    var col = (boat || snapped) ? '#2EC4B6' : '#FFD166';
    return L.divIcon({ className: '', iconSize: [34, 34], iconAnchor: [17, 17],
      html: '<div class="sm-ms-pin">'
        + '<div class="sm-ms-ring" style="border-color:' + col + '"></div>'
        + '<div class="sm-ms-dot" style="background:' + col + '"></div>'
        + '<div class="sm-ms-tag" style="background:' + col + '">' + letter + '</div>'
        + '</div>' });
  }
  function _msBearing(a, b){
    var f1 = a.lat * Math.PI / 180, f2 = b.lat * Math.PI / 180;
    var dl = (b.lng - a.lng) * Math.PI / 180;
    var y = Math.sin(dl) * Math.cos(f2);
    var x = Math.cos(f1) * Math.sin(f2) - Math.sin(f1) * Math.cos(f2) * Math.cos(dl);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }
  function _msFmtDist(m){
    if (_msUnit === 'nm'){
      return (m / 1852).toFixed(2).replace('.', ',') + ' NM';
    }
    // 24/07 (retour armateur) — au-dessus du km : 2 décimales.
    if (m >= 1000) return (m / 1000).toFixed(2).replace('.', ',') + ' km';
    return Math.round(m) + ' m';
  }
  function _msCandidates(){
    var c = [];
    try { if (userMarker){ var u = userMarker.getLatLng(); c.push({ lat: u.lat, lng: u.lng, kind: 'boat' }); } } catch(_){}
    try { for (var id in markers){ var ll = markers[id].getLatLng(); c.push({ lat: ll.lat, lng: ll.lng, kind: 'report' }); } } catch(_){}
    try { for (var i = 0; i < _lastMarks.length; i++){ c.push({ lat: _lastMarks[i].lat, lng: _lastMarks[i].lng, kind: 'mark' }); } } catch(_){}
    return c;
  }
  function _msSnapTo(latlng){
    var p = map.latLngToContainerPoint(latlng);
    var best = null, bestD = _MS_SNAP_PX;
    var cands = _msCandidates();
    for (var i = 0; i < cands.length; i++){
      var q = map.latLngToContainerPoint([cands[i].lat, cands[i].lng]);
      var dx = p.x - q.x, dy = p.y - q.y, d = Math.sqrt(dx * dx + dy * dy);
      if (d < bestD){ bestD = d; best = { lat: cands[i].lat, lng: cands[i].lng, kind: cands[i].kind }; }
    }
    if (_routePts && _routePts.length >= 2){
      for (var j = 0; j < _routePts.length - 1; j++){
        var a = map.latLngToContainerPoint(_routePts[j]);
        var b = map.latLngToContainerPoint(_routePts[j + 1]);
        var vx = b.x - a.x, vy = b.y - a.y;
        var L2 = vx * vx + vy * vy;
        if (!L2) continue;
        var t = Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.y - a.y) * vy) / L2));
        var qx = a.x + t * vx, qy = a.y + t * vy;
        var d2 = Math.sqrt((p.x - qx) * (p.x - qx) + (p.y - qy) * (p.y - qy));
        if (d2 < bestD){
          var ll2 = map.containerPointToLatLng(L.point(qx, qy));
          bestD = d2; best = { lat: ll2.lat, lng: ll2.lng, kind: 'route' };
        }
      }
    }
    return best;
  }
  function _msRefresh(){
    if (!_msOn || !_msPins.A || !_msPins.B) return;
    var a = _msPins.A.getLatLng(), b = _msPins.B.getLatLng();
    var pts = [[a.lat, a.lng], [b.lat, b.lng]];
    _msHalo.setLatLngs(pts); _msLine.setLatLngs(pts);
    var dist = map.distance(a, b);
    var brg = Math.round(_msBearing(a, b)) % 360;
    var brgTxt = (brg < 100 ? (brg < 10 ? '00' : '0') : '') + brg;
    var magnetTxt = '';
    if (_msMagnet.A === 'boat' || _msMagnet.B === 'boat'){
      magnetTxt = '<div class="sm-ms-magnet">aimant\u00e9 au bateau \u2014 mesure en direct</div>';
    }
    // 29/07/2026 (vidéo Navionics 00:09, demande armateur) — popup façon
    // Navionics : carte sombre SEMI-TRANSPARENTE (fond de carte visible)
    // centrée SUR le trait (z-index au-dessus), TOUJOURS horizontale
    // (sm-tag-anchor contre-rote en course-up). Deux colonnes :
    // Distance | Relèvement. Tap → bascule m/km ↔ NM (inchangé).
    var html = '<div class="sm-tag-anchor"><div class="sm-ms-card2">'
      + '<div class="sm-ms-col"><div class="sm-ms-val">' + _msFmtDist(dist) + '</div>'
      + '<div class="sm-ms-cap">Distance</div></div>'
      + '<div class="sm-ms-sep"></div>'
      + '<div class="sm-ms-col"><div class="sm-ms-val">' + brgTxt + '\u00b0</div>'
      + '<div class="sm-ms-cap">Rel\u00e8vement</div></div>'
      + '</div>' + magnetTxt + '</div>';
    _msLabel.setLatLng([(a.lat + b.lat) / 2, (a.lng + b.lng) / 2]);
    _msLabel.setIcon(L.divIcon({ className: '', iconSize: [0, 0], iconAnchor: [0, 0], html: html }));
  }
  function _msMakePin(letter, latlng){
    var pin = L.marker(latlng, { icon: _msPinIcon(false, letter, false), draggable: true, zIndexOffset: 1400 });
    pin.on('dragstart', function(){
      _msMagnet[letter] = null;               // on détache l'aimant en reprenant le point
      if (window.SM) SM.lastUserPan = Date.now();  // pas de recentrage auto pendant la mesure
    });
    pin.on('drag', function(){
      if (window.SM) SM.lastUserPan = Date.now();
      // NOTE : pendant le drag, NI setLatLng NI setIcon (les deux cassent le
      // Draggable de Leaflet : désynchronisation / remplacement du DOM).
      // On toggle une CLASSE CSS sur l'élément existant pour signaler
      // l'accroche (teal + haptique) ; l'aimantation s'applique au dragend.
      var s = _msSnapTo(pin.getLatLng());
      var snapped = !!s;
      if (snapped !== _msSnapState[letter]){
        _msSnapState[letter] = snapped;
        if (pin._icon){
          if (snapped) L.DomUtil.addClass(pin._icon, 'sm-ms-snap');
          else L.DomUtil.removeClass(pin._icon, 'sm-ms-snap');
        }
        if (snapped) postMsg({ event: 'measure_snap', kind: s.kind });
      }
      _msRefresh();
    });
    pin.on('dragend', function(){
      var s = _msSnapTo(pin.getLatLng());
      if (s){
        pin.setLatLng([s.lat, s.lng]);
        if (s.kind === 'boat') _msMagnet[letter] = 'boat';
      }
      _msSnapState[letter] = false;
      pin.setIcon(_msPinIcon(false, letter, _msMagnet[letter] === 'boat'));
      _msRefresh();
    });
    return pin;
  }
  // Appelé par SM.setUser à chaque tick GPS : les extrémités aimantées au
  // bateau suivent, la mesure se met à jour en continu.
  window.__msBoatTick = function(lat, lng){
    if (!_msOn) return;
    var moved = false;
    if (_msMagnet.A === 'boat' && _msPins.A){ _msPins.A.setLatLng([lat, lng]); moved = true; }
    if (_msMagnet.B === 'boat' && _msPins.B){ _msPins.B.setLatLng([lat, lng]); moved = true; }
    if (moved) _msRefresh();
  };
  window.__setMeasure = function(on){
    on = !!on;
    if (on === _msOn) return;
    _msOn = on;
    if (!on){
      if (_msLayer) map.removeLayer(_msLayer);
      _msLayer = null; _msPins = { A: null, B: null };
      _msLine = null; _msHalo = null; _msLabel = null;
      _msMagnet = { A: null, B: null }; _msSnapState = { A: false, B: false };
      return;
    }
    var sz = map.getSize();
    // 26/07 (bug vidéo armateur « le compas dérive en navigation ») —
    // orientation GÉOGRAPHIQUE déterministe du segment par défaut :
    //   • bateau EN ROUTE (mode nav + vitesse ≥ 3 km/h) → segment aligné
    //     sur l'AXE DE NAVIGATION (cap courant), A derrière, B devant ;
    //   • sinon → segment plein NORD-SUD (A au sud, B au nord).
    // Avant : diagonale en fractions d'ÉCRAN → avec la rotation course-up,
    // le relèvement initial semblait aléatoire et « dérivait » à chaque
    // ouverture. Longueur ≈ 1/4 du petit côté de l'écran (suit le zoom).
    var c0 = map.containerPointToLatLng(L.point(sz.x * 0.5, sz.y * 0.5));
    var hd0 = 0;
    try {
      if (window.SM && SM.userIsBoat && typeof SM.userHeading === 'number' &&
          typeof SM.userSpeed === 'number' && SM.userSpeed >= SM.MIN_NAV_SPEED_MS){
        hd0 = SM.userHeading;
      }
    } catch(_){}
    var mPerPx0 = 156543.03392 * Math.cos(c0.lat * Math.PI / 180) / Math.pow(2, map.getZoom());
    var halfLenKm = Math.min(sz.x, sz.y) * 0.14 * mPerPx0 / 1000;
    var paA = destPoint(c0.lat, c0.lng, (hd0 + 180) % 360, halfLenKm);
    var pbA = destPoint(c0.lat, c0.lng, hd0, halfLenKm);
    var pa = L.latLng(paA[0], paA[1]);
    var pb = L.latLng(pbA[0], pbA[1]);
    _msLayer = L.layerGroup().addTo(map);
    _msHalo = L.polyline([], { color: '#0B132B', weight: 6, opacity: 0.55, interactive: false }).addTo(_msLayer);
    // 24/07 (retour armateur) — ligne PLEINE (les pointillés faisaient laid).
    _msLine = L.polyline([], { color: '#FFD166', weight: 3, opacity: 0.98, lineCap: 'round', interactive: false }).addTo(_msLayer);
    _msLabel = L.marker([pa.lat, pa.lng], { interactive: true, zIndexOffset: 1500,
      icon: L.divIcon({ className: '', iconSize: [0, 0], html: '' }) });
    _msLabel.on('click', function(ev){
      if (ev.originalEvent){ ev.originalEvent._smRouteTap = true; }
      _msUnit = (_msUnit === 'm') ? 'nm' : 'm';
      _msRefresh();
    });
    _msLabel.addTo(_msLayer);
    _msPins.A = _msMakePin('A', pa).addTo(_msLayer);
    _msPins.B = _msMakePin('B', pb).addTo(_msLayer);
    _msRefresh();
  };
`;
