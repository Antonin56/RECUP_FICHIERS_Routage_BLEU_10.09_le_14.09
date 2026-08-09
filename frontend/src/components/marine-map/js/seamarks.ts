// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Zones de tap invisibles sur les balises/dangers ingérés.

export const JS_SEAMARKS = `  // ── 22/07/2026 — BALISES CLIQUABLES : les tuiles OpenSeaMap sont du raster
  // → on superpose des zones de tap invisibles sur les seamarks ingérées
  // (GET /api/bathy/seamarks). Actif au zoom ≥ 12, rafraîchi au moveend.
  var _markLayer = L.layerGroup().addTo(map);
  var _markBase = '', _markTimer = null, _markSeq = 0;
  // 24/07 — dernier lot de balises/dangers reçus (cibles du magnétisme du
  // compas de mesure).
  var _lastMarks = [];
  function refreshSeamarks(){
    if (!_markBase) return;
    if (_netQuiet){ _markRetry = true; return; }
    var z = map.getZoom();
    if (z < 12){ _markLayer.clearLayers(); return; }
    var b = map.getBounds();
    var bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
      .map(function(v){ return v.toFixed(5); }).join(',');
    var seq = ++_markSeq;
    fetch(_markBase + '/api/bathy/seamarks?bbox=' + bbox)
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (seq !== _markSeq) return;
        _markLayer.clearLayers();
        var marks = (d && d.marks) || [];
        _lastMarks = marks;
        // 29/07/2026 (retour mer « zones de mouillage = taches noires ») —
        // les zones de tap étaient des disques NOIRS à 1 % d'opacité : dans
        // les champs de mouillage denses, des centaines de disques superposés
        // s'additionnaient en taches noires visibles à certains zooms
        // (1-(1-0.01)^300 ≈ 95 % d'opacité cumulée). Opacité 0 STRICTE (le
        // remplissage SVG capte quand même les taps, pointer-events
        // visiblePainted) + ALLÈGEMENT PAR ZOOM : bouées de mouillage
        // cliquables seulement à z ≥ 14 (moins d'objets → carte plus fluide).
        var zNow = map.getZoom();
        for (var i = 0; i < marks.length; i++){
          if (marks[i].kind === 'mooring' && zNow < 14) continue;
          (function(m){
            L.circleMarker([m.lat, m.lng], {
              radius: 16, stroke: false, fillColor: '#000', fillOpacity: 0,
              interactive: true, bubblingMouseEvents: false,
            }).on('click', function(ev){
              if (ev.originalEvent){ ev.originalEvent._smRouteTap = true; }
              postMsg({ event: 'seamark_tap', mark: m });
            }).addTo(_markLayer);
          })(marks[i]);
        }
      })
      .catch(function(_){});
  }
  window.__setSeamarkTaps = function(baseUrl){
    try { _markBase = String(baseUrl || ''); refreshSeamarks(); } catch(_){}
  };
  map.on('moveend zoomend', function(){
    if (!_markBase) return;
    if (_markTimer) clearTimeout(_markTimer);
    _markTimer = setTimeout(refreshSeamarks, 400);
  });

`;
