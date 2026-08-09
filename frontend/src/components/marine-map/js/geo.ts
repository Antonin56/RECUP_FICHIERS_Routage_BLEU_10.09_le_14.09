// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Helpers géodésiques (destPoint, bearingTo, distanceKm, isInsideCone).

export const JS_GEO = `  function destPoint(lat, lng, bearingDeg, distKm){
    var R = 6371.0;
    var br = bearingDeg * Math.PI / 180;
    var lat1 = lat * Math.PI / 180;
    var lng1 = lng * Math.PI / 180;
    var dr = distKm / R;
    var lat2 = Math.asin(Math.sin(lat1)*Math.cos(dr) + Math.cos(lat1)*Math.sin(dr)*Math.cos(br));
    var lng2 = lng1 + Math.atan2(
      Math.sin(br)*Math.sin(dr)*Math.cos(lat1),
      Math.cos(dr)-Math.sin(lat1)*Math.sin(lat2)
    );
    return [lat2 * 180 / Math.PI, lng2 * 180 / Math.PI];
  }
  /* Phase K — Great-circle bearing from (lat1,lng1) to (lat2,lng2), degrees. */
  function bearingTo(lat1, lng1, lat2, lng2){
    var p1 = lat1 * Math.PI / 180;
    var p2 = lat2 * Math.PI / 180;
    var dl = (lng2 - lng1) * Math.PI / 180;
    var y = Math.sin(dl) * Math.cos(p2);
    var x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    var brg = Math.atan2(y, x) * 180 / Math.PI;
    return (brg + 360) % 360;
  }
  /* Phase K — Haversine distance in km. */
  function distanceKm(lat1, lng1, lat2, lng2){
    var R = 6371.0;
    var dl = (lat2 - lat1) * Math.PI / 180;
    var dg = (lng2 - lng1) * Math.PI / 180;
    var a = Math.sin(dl/2)*Math.sin(dl/2)
          + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
          * Math.sin(dg/2) * Math.sin(dg/2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
  }
  /* Phase K — Is a report inside the navigation cone ?
   * heading: user's course (deg 0-360)
   * halfAngle: cone half-spread (deg)
   * totalDistKm: forward reach of the corridor (km)
   * Geometry: near-field is a triangle flare (2 km deep, ± halfAngle wide);
   * far-field is a parallel corridor of width 2 * flareKm * sin(halfAngle).
   * Returns true when the report lies inside this pill-like footprint. */
  function isInsideCone(rLat, rLng, bLat, bLng, heading, halfAngle, totalDistKm){
    if (heading == null || halfAngle == null || totalDistKm == null || totalDistKm <= 0) return true;
    var d = distanceKm(bLat, bLng, rLat, rLng);
    if (d > totalDistKm) return false;
    var brg = bearingTo(bLat, bLng, rLat, rLng);
    var diff = ((brg - heading + 540) % 360) - 180; // signed [-180,180]
    var absDiff = Math.abs(diff);
    if (absDiff >= 90) return false; // behind or beam-abeam
    var halfRad = halfAngle * Math.PI / 180;
    var diffRad = diff * Math.PI / 180;
    var flareKm = 1.0;
    var halfWidthKm = flareKm * Math.sin(halfRad);
    var alongKm = d * Math.cos(diffRad);
    var perpKm = Math.abs(d * Math.sin(diffRad));
    if (alongKm < 0) return false;
    if (alongKm > totalDistKm) return false;
    var alongFlareEnd = flareKm * Math.cos(halfRad);
    if (alongKm <= alongFlareEnd) {
      // Flare (triangle) zone: pure angular check.
      return absDiff <= halfAngle;
    }
    // Corridor (parallel) zone: perpendicular distance check.
    return perpKm <= halfWidthKm;
  }

`;
