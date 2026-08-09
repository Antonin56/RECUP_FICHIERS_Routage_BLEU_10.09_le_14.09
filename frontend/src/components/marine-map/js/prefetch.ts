// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Préchargement lissé des tuiles autour du bateau.

export const JS_PREFETCH = `  // Prefetch actif de tuiles autour du bateau (16/07/2026 retour user).
  // Idée : on TÉLÉCHARGE en arrière-plan un rayon de 2 km autour de la
  // position user aux niveaux Z-1 / Z / Z+1. Les tuiles téléchargées sont
  // mises en cache navigateur (HTTP cache + Leaflet _tiles) → si on zoome
  // ou dézoome d'un pas, elles sont IMMÉDIATEMENT disponibles, plus de
  // carré noir. Best-effort (ignore les erreurs réseau).
  window.__prefetched = window.__prefetched || {};
  function tileUrl(template, z, x, y){
    return template.replace('{z}', z).replace('{x}', x).replace('{y}', y);
  }
  // 24/07/2026 (rafales 429) — FILE D'ATTENTE du prefetch : avant, ~200
  // requêtes partaient d'un coup (2 couches × 3 zooms × ~35 tuiles) → burst
  // qui déclenchait la limite de débit de l'ingress et faisait AUSSI échouer
  // les tuiles VISIBLES (balises disparues). Débit lissé : 1 tuile / 60 ms
  // (~16 req/s en tâche de fond), file bornée à 400 entrées.
  var _pfQueue = [], _pfTimer = null;
  function _pfDrain(){
    if (!_pfQueue.length){ _pfTimer = null; return; }
    // 02/08/2026 — silence réseau (calcul de route en cours) : la file
    // patiente, elle reprendra toute seule.
    if (_netQuiet){ _pfTimer = setTimeout(_pfDrain, 1200); return; }
    var url = _pfQueue.shift();
    try { var im = new Image(); im.decoding = 'async'; im.src = url; } catch(_){}
    _pfTimer = setTimeout(_pfDrain, 100);
  }
  // 02/08/2026 (armateur : 429 pendant les calculs de route côtiers) —
  // window.__setNetQuiet(on) : coupe TOUT le trafic secondaire de la carte
  // pendant un calcul, puis rattrape ce qui a été mis de côté.
  window.__setNetQuiet = function(on){
    try {
      on = !!on;
      if (on === _netQuiet) return;
      _netQuiet = on;
      if (!on){
        if (_isoRetry){ _isoRetry = false; refreshIsobaths(); }
        if (_markRetry){ _markRetry = false; refreshSeamarks(); }
        if (_pfQueue.length && !_pfTimer) _pfTimer = setTimeout(_pfDrain, 400);
      }
    } catch(_){}
  };
  function _pfEnqueue(url){
    _pfQueue.push(url);
    if (_pfQueue.length > 400) _pfQueue.splice(0, _pfQueue.length - 400);
    // 26/07 (tuiles visibles prioritaires au démarrage) — le prefetch de
    // fond démarre 1,5 s après la première demande : les tuiles À L'ÉCRAN
    // passent d'abord, moins de 429 au chargement initial.
    if (!_pfTimer) _pfTimer = setTimeout(_pfDrain, 1500);
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
        // OSM standard (24/07 — via la file lissée, plus de burst 429)
        _pfEnqueue(tileUrl('https://tile.openstreetmap.org/{z}/{x}/{y}.png', z, x, y));
        // OpenSeaMap seamark overlay (via le proxy-cache backend — 23/07)
        _pfEnqueue(tileUrl(API_BASE ? API_BASE + '/api/tiles/seamark/{z}/{x}/{y}.png'
                                    : 'https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', z, x, y));
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

`;
