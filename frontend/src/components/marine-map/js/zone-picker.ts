// SignalMar — OUTIL DE ZONE « Cartes 📥 » (V1.6, ordre armateur 09/09/2026).
// window.__zoneStart() : carré semi-transparent de 50 km de rayon centré sur
// la vue, 4 coins DÉPLAÇABLES (markers draggables) pour ajuster la zone.
// Chaque ajustement poste {event:'zone_corners', corners:[{lat,lng}×4]} au RN.
// window.__zoneStop() : retire l'outil.

export const JS_ZONE_PICKER = `  // ── Outil de sélection de zone (cartes hors ligne) ──
  var _zonePoly = null, _zoneMarkers = [];
  function _zonePost(){
    try {
      var corners = _zoneMarkers.map(function(m){
        var p = m.getLatLng();
        return { lat: p.lat, lng: p.lng };
      });
      postMsg({ event: 'zone_corners', corners: corners });
      if (_zonePoly) _zonePoly.setLatLngs(corners.map(function(c){ return [c.lat, c.lng]; }));
    } catch(_){}
  }
  window.__zoneStart = function(){
    window.__zoneStop();
    var c = map.getCenter();
    // Carré de 50 km de « rayon » (100 km de côté) centré sur la vue.
    var dLat = 50000 / 111320;
    var dLng = 50000 / (111320 * Math.max(0.2, Math.cos(c.lat * Math.PI / 180)));
    var pts = [
      [c.lat + dLat, c.lng - dLng], [c.lat + dLat, c.lng + dLng],
      [c.lat - dLat, c.lng + dLng], [c.lat - dLat, c.lng - dLng]
    ];
    _zonePoly = L.polygon(pts, {
      color: '#48CAE4', weight: 2, fillColor: '#48CAE4', fillOpacity: 0.15,
      dashArray: '6 4',
    }).addTo(map);
    var cornerIcon = L.divIcon({
      className: '', iconSize: [22, 22], iconAnchor: [11, 11],
      html: '<div style="width:22px;height:22px;border-radius:11px;' +
            'background:#48CAE4;border:3px solid #04121F;box-shadow:0 0 6px rgba(0,0,0,.6)"></div>',
    });
    _zoneMarkers = pts.map(function(p){
      var m = L.marker(p, { icon: cornerIcon, draggable: true, zIndexOffset: 4000 }).addTo(map);
      m.on('drag dragend', _zonePost);
      return m;
    });
    map.fitBounds(_zonePoly.getBounds(), { padding: [40, 40] });
    _zonePost();
  };
  window.__zoneStop = function(){
    try {
      if (_zonePoly) map.removeLayer(_zonePoly);
      _zoneMarkers.forEach(function(m){ map.removeLayer(m); });
    } catch(_){}
    _zonePoly = null; _zoneMarkers = [];
  };
`;
