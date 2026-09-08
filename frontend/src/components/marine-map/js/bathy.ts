// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Surcouche bathymétrie SHOM (proxy-cache) + isobathes backend.

export const JS_BATHY = `  // ── 19/07/2026 — PROTOTYPE bathymétrie SHOM (open data data.shom.fr,
  // Licence Ouverte, citation SHOM ; PAS pour la navigation officielle).
  // Le service WMS INSPIRE public refuse les requêtes multi-couches →
  // un overlay Leaflet PAR couche (façades ATL/MED + côtier Morbihan 20 m).
  // AUCUNE requête n'est émise tant que window.__setBathy(true) n'est pas
  // appelé (couches non ajoutées à la carte par défaut → « ne casse rien »).
  // 23/07/2026 (fluidité + flashs tablette) — les tuiles SHOM passent par
  // NOTRE PROXY-CACHE backend (/api/tiles/shom/...) : chaque tuile n'est
  // demandée qu'UNE seule fois au WMS SHOM (lent, cause n°1 du lag), puis
  // servie instantanément depuis le disque avec cache HTTP 30 jours.
  // 08/09/2026 (remise à plat armateur, ACTION 4) — la couche FINE (index 3)
  // n'est plus le WMS « morbihan » (limité au Morbihan) mais NOTRE rendu des
  // DALLES OVH de l'armateur (/api/tiles/dalles/) : le calque bleu s'affiche
  // PARTOUT où son index.json possède des dalles, chargé dynamiquement
  // (dalle manquante → tuile transparente). En dessous de z10, la couche WMS
  // façade régionale prend le relais (_pickBathyLayer).
  var _bathyLayers = ['atl', 'gdl', 'corse', 'dalles'].map(function(key, idx){
    // 22/07/2026 (lag tablette) — chaque couche est BORNÉE à son emprise
    // réelle : plus AUCUNE requête MED/Corse en Bretagne. + updateWhenIdle
    // (téléchargement à l'arrêt du geste) et updateWhenZooming=false.
    var boundsByLayer = [
      L.latLngBounds([[42.0, -7.0], [49.5, 1.0]]),   // façade ATL
      L.latLngBounds([[41.0, 1.5], [44.6, 8.5]]),    // MED Golfe du Lion
      L.latLngBounds([[41.0, 8.0], [43.6, 10.5]]),   // Corse
      L.latLngBounds([[43.3, -5.3], [48.9, -1.0]])   // dalles OVH (repli statique)
    ];
    var url = key === 'dalles'
      ? API_BASE + '/api/tiles/dalles/{z}/{x}/{y}.png'
      : API_BASE + '/api/tiles/shom/' + key + '/{z}/{x}/{y}.png';
    var _tl = L.tileLayer(url, {
      opacity: 0.7, maxZoom: 19,
      attribution: key === 'dalles' ? 'Bathymétrie © SHOM (dalles SignalMar)' : 'Bathymétrie © SHOM',
      // 23/07 — le proxy-cache local rend les tuiles quasi instantanées :
      // on recharge PENDANT le pan (fini les trous puis flashs à l'arrêt).
      keepBuffer: 6, updateWhenIdle: false, updateWhenZooming: false,
      bounds: boundsByLayer[idx],
    });
    attachTileRetry(_tl, 3);
    return _tl;
  });
  var _bathyOn = false;
  var _bathyActive = null; // couche actuellement montée (UNE seule à la fois)
  // 04/09/2026 (ordre armateur, VISUEL) — les LIMITES d'affichage de la
  // couche bathy fine (les « carrés bleus ») sont lues DYNAMIQUEMENT depuis
  // l'index des dalles du serveur (via /api/bathy/tiles-source → bounds
  // [w, s, e, n]) au lieu d'être restreintes au Morbihan. Repli silencieux
  // sur les bornes statiques si l'endpoint ne répond pas.
  fetch(API_BASE + '/api/bathy/tiles-source')
    .then(function(r){ return r.json(); })
    .then(function(info){
      var b = info && info.bounds;
      if (!b || b.length !== 4) return;
      var dyn = L.latLngBounds([[b[1], b[0]], [b[3], b[2]]]);
      _bathyLayers[3].options.bounds = dyn;
      if (_bathyOn) _syncBathy();
    })
    .catch(function(_){});
  function _pickBathyLayer(){
    // 22/07/2026 (lag + flashs tablette) — UNE SEULE couche à la fois.
    // 08/09/2026 — dalles OVH à partir de z10 (en dessous : WMS régional,
    // le rendu fin d'une tuile trop large coûterait trop de dalles).
    var c = map.getCenter();
    var atl = _bathyLayers[0], med = _bathyLayers[1], cor = _bathyLayers[2], dalles = _bathyLayers[3];
    if (map.getZoom() >= 10 && dalles.options.bounds.contains(c)) return dalles;
    if (med.options.bounds.contains(c)) return med;
    if (cor.options.bounds.contains(c)) return cor;
    return atl;
  }
  function _syncBathy(){
    try {
      var want = _bathyOn ? _pickBathyLayer() : null;
      if (_bathyActive === want) return;
      if (_bathyActive){ map.removeLayer(_bathyActive); _bathyActive = null; }
      if (want){
        want.addTo(map);
        _bathyActive = want;
        // Les seamarks OpenSeaMap restent AU-DESSUS de la bathy.
        if (_seaTiles.bringToFront) _seaTiles.bringToFront();
      }
    } catch(_){}
  }
  window.__setBathy = function(on){
    on = !!on;
    if (on === _bathyOn) return;
    _bathyOn = on;
    _syncBathy();
  };
  map.on('moveend zoomend', function(){ if (_bathyOn) _syncBathy(); });
  // 19/07/2026 — opacité de la surcouche bathy (0.3-1), réglable depuis le
  // popup appui-long côté RN. setOpacity fonctionne couche montée ou non.
  window.__setBathyOpacity = function(op){
    try {
      op = Math.max(0.1, Math.min(1, Number(op) || 0.7));
      for (var i = 0; i < _bathyLayers.length; i++) _bathyLayers[i].setOpacity(op);
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
