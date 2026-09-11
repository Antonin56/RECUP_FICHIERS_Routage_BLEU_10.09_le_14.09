// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Surcouche bathymétrie (calque maison rendu par notre backend) + isobathes.

export const JS_BATHY = `  // ── 10/09/2026 (V1.6 finale, preuves armateur « torchon visuel ») —
  // CALQUE BATHY MAISON : rendu LISSE (interpolation bilinéaire, palette
  // bleue continue type SHOM, ESTRAN vert pâle, TERRE TRANSPARENTE) par
  // NOTRE backend depuis la mosaïque SHOM locale (TANDEM 20 m > Litto3D
  // 20 m > ATL 100 m). Remplace les 4 WMS SHOM : fini le relief terrestre
  // orange/rouge, les trous de tuiles amont, la lenteur du WMS et la
  // limite « Morbihan seulement » — UNE seule couche, toute la façade,
  // cache disque serveur 30 j, STRICTEMENT COHÉRENTE avec la goutte d'eau
  // et les isobathes (même mosaïque, même interpolation).
  var _bathyLayer = L.tileLayer(API_BASE + '/api/tiles/bathy-local/{z}/{x}/{y}.png', {
    opacity: 0.7, maxZoom: 21, maxNativeZoom: 15, minZoom: 6,
    attribution: 'Bathymétrie © SHOM',
    keepBuffer: 6, updateWhenIdle: false, updateWhenZooming: false,
    bounds: L.latLngBounds([[45.70, -5.45], [49.01, -1.0]]),
  });
  attachTileRetry(_bathyLayer, 3);
  var _bathyOn = false;
  window.__setBathy = function(on){
    on = !!on;
    if (on === _bathyOn) return;
    _bathyOn = on;
    try {
      if (on){
        _bathyLayer.addTo(map);
        // Les seamarks OpenSeaMap restent AU-DESSUS de la bathy.
        if (_seaTiles.bringToFront) _seaTiles.bringToFront();
      } else {
        map.removeLayer(_bathyLayer);
      }
    } catch(_){}
  };
  // 19/07/2026 — opacité de la surcouche bathy (0.3-1), réglable depuis le
  // popup appui-long côté RN. setOpacity fonctionne couche montée ou non.
  window.__setBathyOpacity = function(op){
    try {
      op = Math.max(0.1, Math.min(1, Number(op) || 0.7));
      _bathyLayer.setOpacity(op);
    } catch(_){}
  };
  // ── N1 (20/07/2026) — ISOBATHES générées par NOTRE backend depuis le MNT
  // SHOM ingéré (GET /api/bathy/isobaths). Niveaux selon le zoom (peu de
  // lignes dézoomé, détail en zoomant), libellés discrets. Activées avec le
  // même bouton goutte d'eau que la surcouche bathy. Aucune requête si OFF.
  var _isoLayer = L.layerGroup();
  var _isoOn = false, _isoBase = '', _isoTimer = null, _isoSeq = 0;
  function drawIsobaths(fc){
    _isoLayer.clearLayers();
    var feats = (fc && fc.features) || [];
    var labels = 0, MAX_LABELS = 60;
    for (var i = 0; i < feats.length; i++){
      var f = feats[i];
      var depth = f.properties && f.properties.depth;
      var coords = f.geometry && f.geometry.coordinates;
      if (!coords || coords.length < 2) continue;
      var latlngs = [];
      for (var k = 0; k < coords.length; k++) latlngs.push([coords[k][1], coords[k][0]]);
      var major = (depth === 5 || depth === 10 || depth === 20 || depth === 50);
      L.polyline(latlngs, {
        color: '#1B4965', weight: major ? 1.4 : 0.9,
        opacity: major ? 0.75 : 0.55, interactive: false, smoothFactor: 1.2,
      }).addTo(_isoLayer);
      // Libellé au milieu des lignes assez longues (confort de lecture).
      if (latlngs.length >= 14 && labels < MAX_LABELS){
        var mid = latlngs[Math.floor(latlngs.length / 2)];
        L.marker(mid, {
          interactive: false,
          icon: L.divIcon({ className: 'sm-iso-label', html: String(depth), iconSize: [28, 12], iconAnchor: [14, 6] }),
        }).addTo(_isoLayer);
        labels++;
      }
    }
  }
  function refreshIsobaths(){
    if (!_isoOn || !_isoBase) return;
    // 02/08/2026 — pendant un calcul de route, on laisse la bande passante
    // (et le quota de requêtes de l'ingress) au calcul : on réessaie après.
    if (_netQuiet){ _isoRetry = true; return; }
    var z = map.getZoom();
    if (z < 9){ _isoLayer.clearLayers(); return; }
    var b = map.getBounds();
    var bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
      .map(function(v){ return v.toFixed(5); }).join(',');
    var seq = ++_isoSeq;
    fetch(_isoBase + '/api/bathy/isobaths?bbox=' + bbox + '&z=' + z)
      .then(function(r){ return r.json(); })
      .then(function(fc){ if (_isoOn && seq === _isoSeq) drawIsobaths(fc); })
      .catch(function(_){});
  }
  window.__setIsobaths = function(on, baseUrl){
    try {
      if (baseUrl) _isoBase = String(baseUrl);
      on = !!on;
      if (on === _isoOn) return;
      _isoOn = on;
      if (on){ _isoLayer.addTo(map); refreshIsobaths(); }
      else { _isoLayer.clearLayers(); map.removeLayer(_isoLayer); }
    } catch(_){}
  };
  map.on('moveend zoomend', function(){
    if (!_isoOn) return;
    if (_isoTimer) clearTimeout(_isoTimer);
    _isoTimer = setTimeout(refreshIsobaths, 350);
  });
`;
