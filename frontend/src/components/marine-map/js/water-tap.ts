// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Pastille hauteur d'eau au point + popup de tap carte.

export const JS_WATER_TAP = `  // ── 26/07/2026 (demande armateur) — HAUTEUR D'EAU AU POINT : pastille
  // affichée SUR la carte au point cliqué (plus de carte en bas d'écran).
  // Tap sur la pastille → RN désactive le mode (event water_close).
  var _wpLayer = null;
  window.__setWaterPoint = function(p){
    try {
      if (_wpLayer){ map.removeLayer(_wpLayer); _wpLayer = null; }
      if (!p || typeof p.lat !== 'number') return;
      _wpLayer = L.layerGroup().addTo(map);
      L.circleMarker([p.lat, p.lng], {
        radius: 5, color: '#48CAE4', weight: 2,
        fillColor: '#0D1B2A', fillOpacity: 1, interactive: false,
      }).addTo(_wpLayer);
      var txt = p.loading ? 'Mesure de la hauteur d\u2019eau\u2026' : (p.text || '');
      var mk = L.marker([p.lat, p.lng], { interactive: true, zIndexOffset: 1600,
        icon: L.divIcon({ className: '', iconSize: [0, 0], iconAnchor: [0, 0],
          html: '<div class="sm-tag-anchor"><div class="sm-tag" style="transform:translate(-50%,-160%);">'
              + '<span class="sm-tag-drop">\uD83D\uDCA7</span>' + txt + '</div></div>' }) });
      mk.on('click', function(ev){
        if (ev.originalEvent){ ev.originalEvent._smRouteTap = true; }
        postMsg({ event: 'water_close' });
      });
      mk.addTo(_wpLayer);
    } catch(_){}
  };

  // ── 31/07/2026 — POPUP CLIC CARTE (mode hauteur d'eau OFF) ────────────
  // Affiché quand l'icône « goutte d'eau » est désactivée et que l'utilisateur
  // tape sur la carte : coordonnées GPS + hauteur d'eau ZH + bouton capture
  // support (compte SignalMar admin uniquement — l'affichage du bouton est
  // contrôlé côté RN via p.showSupport). Toujours horizontal à l'écran
  // (wrapper .sm-tag-anchor contre-rote).
  var _tapLayer = null;
  function _fmtDM(lat, lng){
    var latDir = lat >= 0 ? 'N' : 'S';
    var lngDir = lng >= 0 ? 'E' : 'W';
    lat = Math.abs(lat); lng = Math.abs(lng);
    var latD = Math.floor(lat), latM = (lat - latD) * 60;
    var lngD = Math.floor(lng), lngM = (lng - lngD) * 60;
    var pad = function(n){ return n < 10 ? '0' + n : String(n); };
    return pad(latD) + '\u00B0' + latM.toFixed(3) + '\u2032 ' + latDir
      + '  ' + pad(lngD) + '\u00B0' + lngM.toFixed(3) + '\u2032 ' + lngDir;
  }
  window.__setMapTapInfo = function(p){
    try {
      if (_tapLayer){ map.removeLayer(_tapLayer); _tapLayer = null; }
      if (!p || typeof p.lat !== 'number') return;
      _tapLayer = L.layerGroup().addTo(map);
      // Petit disque au point exact du tap.
      L.circleMarker([p.lat, p.lng], {
        radius: 4, color: '#48CAE4', weight: 2,
        fillColor: '#0D1B2A', fillOpacity: 1, interactive: false,
      }).addTo(_tapLayer);
      var coords = _fmtDM(p.lat, p.lng);
      var depthTxt;
      if (p.loading) {
        depthTxt = 'Sondage\u2026';
      } else if (p.error) {
        depthTxt = 'Sondage indisponible';
      } else if (p.covered === false) {
        depthTxt = 'Hors couverture carte';
      } else if (p.water === false) {
        depthTxt = 'Terre / estran';
      } else if (typeof p.depth_zh_m === 'number') {
        depthTxt = 'Fond au ZH : ' + p.depth_zh_m.toFixed(1) + ' m';
      } else {
        depthTxt = 'Fond indisponible';
      }
      var showSupport = !!p.showSupport;
      var supportBtn = showSupport
        ? '<div class="sm-tap-btn" data-act="support" title="Capturer + envoyer au support">\uD83D\uDCF8</div>'
        : '';
      var html = '<div class="sm-tag-anchor"><div class="sm-tap-card">'
        + '<div class="sm-tap-row1">'
        + '<div><div class="sm-tap-coords">' + coords + '</div>'
        + '<div class="sm-tap-depth">' + depthTxt + '</div></div>'
        + '<div class="sm-tap-btns">' + supportBtn
        + '<div class="sm-tap-btn sm-tap-btn--close" data-act="close" title="Fermer">\u2715</div>'
        + '</div></div>'
        + '</div></div>';
      var mk = L.marker([p.lat, p.lng], { interactive: true, zIndexOffset: 1700,
        icon: L.divIcon({ className: '', iconSize: [0, 0], iconAnchor: [0, 0], html: html }) });
      mk.on('click', function(ev){
        if (ev.originalEvent){
          ev.originalEvent._smRouteTap = true;
          var t = ev.originalEvent.target;
          var act = t && t.getAttribute && t.getAttribute('data-act');
          if (act === 'support'){
            postMsg({ event: 'map_tap_support', lat: p.lat, lng: p.lng,
                      depth_zh_m: (typeof p.depth_zh_m === 'number') ? p.depth_zh_m : null });
            return;
          }
        }
        postMsg({ event: 'map_tap_close' });
      });
      mk.addTo(_tapLayer);
    } catch(_){}
  };

`;
