// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Silence réseau, ré-essai de tuiles, couches OSM + OpenSeaMap.

export const JS_TILES = `  var _netQuiet = false, _isoRetry = false, _markRetry = false;
  function attachTileRetry(layer, maxRetries){
    layer.on('tileerror', function(e){
      try {
        var img = e.tile;
        if (!img || !img.src) return;
        var n = img._smRetry || 0;
        if (n >= maxRetries) return;
        img._smRetry = n + 1;
        var base = img._smSrc0 || img.src;
        img._smSrc0 = base;
        var delay = 1000 * Math.pow(2, n) + Math.floor(Math.random() * 500);
        setTimeout(function(){
          try {
            // Silence réseau : on repousse le ré-essai après le calcul.
            if (_netQuiet){ img._smRetry = n; return; }
            img.src = base + (base.indexOf('?') >= 0 ? '&' : '?') + 'r=' + img._smRetry;
          } catch(_){}
        }, delay);
      } catch(_){}
    });
  }
  var _osmTiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution:'© OpenStreetMap', keepBuffer: 4,
  }).addTo(map);
  attachTileRetry(_osmTiles, 3);
  // 23/07/2026 (fluidité) — tuiles seamark servies par NOTRE proxy-cache
  // backend (téléchargées UNE fois, puis disque + cache HTTP 7 jours).
  var _seaTiles = L.tileLayer(
    (API_BASE ? API_BASE + '/api/tiles/seamark/{z}/{x}/{y}.png'
              : 'https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png'), {
    // 22/07/2026 (bug armateur « balise qui disparaît au zoom ») : les tuiles
    // OpenSeaMap s'arrêtent au z18 → au-delà la couche disparaissait. On
    // AGRANDIT les tuiles z18 (maxNativeZoom) au lieu de les perdre.
    maxZoom: 19, maxNativeZoom: 18, attribution:'© OpenSeaMap', opacity:0.95, keepBuffer: 6,
  }).addTo(map);
  // 26/07/2026 (bug armateur « carte blanche au démarrage — il faut zoomer/
  // dézoomer pour la faire apparaître ») — au premier chargement, une partie
  // des tuiles échoue (taille du WebView pas encore stabilisée + rafale
  // initiale → 429 ingress) et Leaflet ne les redemande jamais. On refait
  // PROGRAMMATIQUEMENT ce que faisait l'utilisateur : à 3 reprises après le
  // chargement, invalidateSize + re-demande des SEULES tuiles manquantes
  // (aucun redraw complet → pas de flash visible).
  function _retileMissing(){
    try {
      map.invalidateSize({ animate: false });
      [_osmTiles, _seaTiles].forEach(function(layer){
        if (!layer) return;
        var tiles = layer._tiles || {};
        var keys = Object.keys(tiles);
        if (!keys.length){ if (layer.redraw) layer.redraw(); return; }
        keys.forEach(function(k){
          var t = tiles[k], img = t && t.el;
          if (img && img.tagName === 'IMG' && (!img.complete || !img.naturalWidth)){
            var base = img._smSrc0 || img.src;
            img._smSrc0 = base;
            img.src = base + (base.indexOf('?') >= 0 ? '&' : '?') + 'boot=' + Date.now();
          }
        });
      });
    } catch(_){}
  }
  setTimeout(_retileMissing, 1200);
  setTimeout(_retileMissing, 3500);
  setTimeout(_retileMissing, 8000);
`;
