// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Pont postMessage, init de la carte, patchs de rotation (drag + taps),
// règles d'échelle latérale et barre Navionics.

export function jsBootstrap(
  center: { lat: number; lng: number },
  zoom: number,
  apiBase: string,
) {
  return `  function postMsg(payload){
    var data = JSON.stringify(payload);
    if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(data);
    else if (window.parent) window.parent.postMessage(data, "*");
  }
  // 23/07/2026 — base URL du backend, injectée au build du HTML : sert au
  // PROXY-CACHE de tuiles (/api/tiles/...) qui remplace les appels directs
  // au WMS SHOM (lent) et à OpenSeaMap (irrégulier).
  var API_BASE = ${JSON.stringify(apiBase)};
  var map = L.map('map', {zoomControl:false, attributionControl:false}).setView([${center.lat}, ${center.lng}], ${zoom});
  // Expose the map instance for diagnostic/testing purposes (pan direction
  // verification). Harmless in production.
  window.__map__ = map;
  // Phase K.9 — Rotation-aware pan. The #map div is CSS-rotated in course-up
  // mode via SM.setBearing, but Leaflet's built-in Draggable computes offsets
  // in raw screen pixels and applies them to _mapPane. Because _mapPane
  // inherits the parent rotation, the visual pan ends up rotated by -bearing
  // relative to the finger — swiping straight down produces a diagonal drift.
  // We fix this by rotating the drag offset by +bearing so the visual result
  // matches the finger exactly (grab-and-drag). At moveend, getCenter() reads
  // the same rotated position, so the map center updates consistently.
  // 29/07/2026 (retour mer « compas de mesure devenu fou / inutilisable ») —
  // le patch de rotation était appliqué UNIQUEMENT au Draggable de la carte :
  // les MARQUEURS déplaçables (épingles A/B du compas de mesure, waypoints de
  // route manuelle) bougeaient toujours en pixels écran BRUTS → en course-up
  // (div roté de -bearing) le doigt tirait vers le bas et l'épingle partait
  // en diagonale. Patch déplacé sur le PROTOTYPE de L.Draggable : le pan de
  // carte ET tous les marqueurs draggables sont corrigés d'un coup.
  try {
    var _dragProto = L.Draggable && L.Draggable.prototype;
    if (_dragProto && _dragProto._updatePosition) {
      var _origUpdate = _dragProto._updatePosition;
      _dragProto._updatePosition = function(){
        try {
          var b = (window.SM && typeof window.SM.bearingApplied === 'number') ? window.SM.bearingApplied : 0;
          if (b && this._newPos && this._startPos) {
            var off = this._newPos.subtract(this._startPos);
            var rad = b * Math.PI / 180;
            var cs = Math.cos(rad), sn = Math.sin(rad);
            var rx = off.x * cs - off.y * sn;
            var ry = off.x * sn + off.y * cs;
            this._newPos = this._startPos.add(L.point(rx, ry));
          }
        } catch(_){}
        return _origUpdate.call(this);
      };
    }
  } catch(_){}
  // 29/07/2026 (retour mer « pastille hauteur d'eau décalée » + « signalement
  // posé à terre, loin du point touché ») — en course-up le div #map est
  // CSS-roté : getBoundingClientRect() renvoie la boîte englobante TOURNÉE et
  // mouseEventToContainerPoint plaçait le tap au mauvais endroit (erreur
  // ∝ sin(bearing) × distance au centre de l'écran). On reconstruit le point
  // conteneur depuis le CENTRE du viewport (= centre du div, invariant par
  // rotation) en contre-rotant le vecteur écran de +bearingApplied — même
  // math que vpToLatLng (règles). No-op en nord-en-haut. Corrige TOUS les
  // taps : hauteur d'eau, appui long signalement, cônes, tracé de route.
  try {
    var _origME2CP = map.mouseEventToContainerPoint.bind(map);
    map.mouseEventToContainerPoint = function(e){
      var b = (window.SM && window.SM.bearingApplied) || 0;
      if (!b || typeof e.clientX !== 'number') return _origME2CP(e);
      var W = window.innerWidth, H = window.innerHeight;
      var s = map.getSize();
      var a = b * Math.PI / 180;
      var dx = e.clientX - W / 2, dy = e.clientY - H / 2;
      var cs = Math.cos(a), sn = Math.sin(a);
      return L.point(s.x / 2 + (dx * cs - dy * sn), s.y / 2 + (dx * sn + dy * cs));
    };
  } catch(_){}
  // Contrôle de zoom Leaflet intégré RETIRÉ (12/07/2026) — remplacé par les
  // boutons natifs +/- côté gauche (map.tsx), plus gros et accessibles.
  // Échelle custom (10/07/2026) — remplace L.control.scale : deux règles
  // discrètes (bas = 80 % de largeur, gauche = 80 % de hauteur) avec repères
  // 0 / milieu / fin recalculés à chaque déplacement/zoom.
  (function(){
    function mkRuler(id, vertical){
      var el = document.createElement('div');
      el.id = id; el.className = 'sm-ruler';
      for (var i = 0; i < 3; i++) {
        var t = document.createElement('div'); t.className = 'tick';
        var pos = (i * 50) + '%';
        if (vertical) t.style.top = pos; else t.style.left = pos;
        el.appendChild(t);
        var l = document.createElement('div'); l.className = 'lbl';
        l.id = id + '-l' + i;
        if (vertical) l.style.top = pos; else l.style.left = pos;
        el.appendChild(l);
      }
      // 16/07/2026 (retour user) — clic sur l'échelle → menu unité km/NM.
      el.addEventListener('click', function(){
        postMsg({ event: 'ruler_tap' });
      });
      document.body.appendChild(el);
    }
    // 17/07/2026 — règle horizontale du bas RETIRÉE (demande armateur) :
    // seule la règle VERTICALE gauche est créée ; la barre Navionics
    // reste la seule échelle du bas.
    mkRuler('sm-ruler-v', true);
    // Barre style Navionics (16/07/2026) — longueur physique = 1 unité.
    // Positionnée en bas-gauche, seule échelle horizontale depuis le 17/07.
    var nav = document.createElement('div');
    nav.id = 'sm-ruler-nav';
    nav.innerHTML = '<div id="sm-ruler-nav-lbl">1 km</div><div class="bar" id="sm-ruler-nav-bar"></div>';
    nav.addEventListener('click', function(){ postMsg({ event: 'ruler_tap' }); });
    document.body.appendChild(nav);

    function setLbl(id, txt){ var e = document.getElementById(id); if (e) e.textContent = txt; }
    // ── FIX 11/07/2026 (retour user : « 31 km total, moitié à 15 ») ──
    // 1) Le conteneur #map est un CARRÉ SURDIMENSIONNÉ de 140vmax (pour la
    //    rotation course-up) : mesurer 80 % de map.getSize() donnait des
    //    distances fausses (et identiques H/V). On mesure désormais aux
    //    positions RÉELLES des règles dans le VIEWPORT, converties en
    //    coordonnées du conteneur (rotation course-up comprise).
    // 2) Le repère du milieu est EXACTEMENT la moitié de la valeur de fin
    //    (fin arrondie pour un affichage propre « à l'œil »).
    function vpToLatLng(vx, vy){
      var W = window.innerWidth, H = window.innerHeight;
      var s = map.getSize();
      var aDeg = (window.SM && typeof window.SM.bearingApplied === 'number') ? window.SM.bearingApplied : 0;
      var a = aDeg * Math.PI / 180;
      var dx = vx - W / 2, dy = vy - H / 2;
      var cs = Math.cos(a), sn = Math.sin(a);
      // Le div est tourné de -bearingApplied ⇒ vecteur écran → vecteur
      // conteneur = rotation de +bearingApplied.
      var ux = dx * cs - dy * sn;
      var uy = dx * sn + dy * cs;
      return map.containerPointToLatLng([s.x / 2 + ux, s.y / 2 + uy]);
    }
    // 16/07/2026 (retour user) — arrondi pour la lisibilité « à l'œil »
    // (fini les 6,2 km) : on prend le divisor le plus proche parmi une
    // liste de valeurs rondes, puis on affiche la valeur ronde.
    function roundNice(x, thresholds){
      // thresholds ex. [1, 2, 5, 10, 20, 50, ...]
      var best = thresholds[0];
      var bestDiff = Math.abs(x - best);
      for (var i = 1; i < thresholds.length; i++){
        var d = Math.abs(x - thresholds[i]);
        if (d < bestDiff){ bestDiff = d; best = thresholds[i]; }
      }
      return best;
    }
    function setRuler(prefix, meters, unit){
      var midTxt, endTxt;
      if (unit === 'nm') {
        var nm = meters / 1852;
        var nmR;
        if (nm < 0.5) nmR = roundNice(nm, [0.05, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5]);
        else if (nm < 5) nmR = roundNice(nm, [0.5, 1, 1.5, 2, 3, 4, 5]);
        else if (nm < 50) nmR = roundNice(nm, [5, 10, 15, 20, 25, 30, 40, 50]);
        else nmR = roundNice(nm, [50, 75, 100, 150, 200, 300, 500]);
        var nmH = nmR / 2;
        midTxt = (nmH < 0.1 ? nmH.toFixed(2) : nmH.toString()).replace('.', ',') + ' NM';
        endTxt = (nmR < 1 ? nmR.toString().replace('.', ',') : nmR.toString()) + ' NM';
      } else if (meters < 2000){
        var m = meters;
        var mR;
        if (m < 200) mR = roundNice(m, [20, 50, 100, 150, 200]);
        else if (m < 1000) mR = roundNice(m, [200, 300, 400, 500, 700, 1000]);
        else mR = roundNice(m, [1000, 1200, 1500, 2000]);
        midTxt = (mR / 2) + ' m'; endTxt = mR + ' m';
      } else {
        var kmX = meters / 1000;
        var kmR;
        if (kmX < 10) kmR = roundNice(kmX, [2, 3, 4, 5, 6, 8, 10]);
        else if (kmX < 100) kmR = roundNice(kmX, [10, 15, 20, 25, 30, 40, 50, 75, 100]);
        else kmR = roundNice(kmX, [100, 150, 200, 300, 500, 750, 1000]);
        midTxt = (kmR / 2) + ' km'; endTxt = kmR + ' km';
      }
      // ─── Inversion échelle verticale (16/07/2026 retour user) ────────
      // Verticale (seule règle restante depuis le 17/07) : 0 EN BAS (l2),
      // fin EN HAUT (l0).
      setLbl(prefix + '-l0', endTxt);
      setLbl(prefix + '-l1', midTxt);
      setLbl(prefix + '-l2', '0');
    }
    // ── FIX 17/07/2026 (v2 « alignement Navionics ↔ échelle H ») ─────
    // La barre Navionics et l'échelle horizontale ont des LARGEURS
    // différentes (barre = jusqu'à 45 % ; échelle = 80 %) donc leurs
    // extrémités ne pouvaient jamais coïncider. Nouveau système :
    //   • Les deux partent du MÊME bord gauche (10 % du viewport).
    //   • La barre Navionics prend une longueur = fraction du couloir de
    //     l'échelle H (80 % de viewport) proportionnelle à nice/dH.
    //   • On plafonne « nice » à dH (l'échelle H couvre plus loin) donc la
    //     barre Navionics est TOUJOURS un sous-ensemble propre de l'échelle.
    function updateNavBar(unit, dHmeters){
      try {
        var W = window.innerWidth;
        var hRulerPx = W * 0.8; // couloir de référence (10 % → 90 % du viewport)
        var dH = dHmeters;
        if (!(dH > 0)) return;
        var candidates;
        // 18/07 (demande armateur « barre à 80 % de largeur ») : liste
        // DENSIFIÉE de valeurs rondes (pas ~1,25×) pour que la plus grande
        // valeur ≤ dH donne une barre qui occupe 60-80 % du viewport.
        if (unit === 'nm') {
          var nmVals = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7,
            1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50,
            60, 80, 100, 150, 200, 250, 300, 400, 500];
          candidates = nmVals.map(function(v){
            return {m: v * 1852, lbl: String(v).replace('.', ',') + ' NM'};
          });
        } else {
          var mVals = [20, 30, 50, 70, 100, 150, 200, 250, 300, 400, 500, 700];
          var kmVals = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30,
            40, 50, 60, 80, 100, 150, 200, 250, 300, 400, 500];
          candidates = mVals.map(function(v){
            return {m: v, lbl: v + ' m'};
          }).concat(kmVals.map(function(v){
            return {m: v * 1000, lbl: String(v).replace('.', ',') + ' km'};
          }));
        }
        // Plus grande valeur ronde ≤ dH → frac ∈ [~0,75 ; 1], la barre
        // occupe donc ~60-80 % de la largeur du viewport.
        var best = candidates[0];
        for (var i = 0; i < candidates.length; i++) {
          if (candidates[i].m <= dH) best = candidates[i]; else break;
        }
        // Fraction de l'échelle H que représente best.m.
        var frac = Math.min(1, best.m / dH);
        var pxLen = Math.max(30, frac * hRulerPx);
        var bar = document.getElementById('sm-ruler-nav-bar');
        var lbl = document.getElementById('sm-ruler-nav-lbl');
        if (bar) bar.style.width = pxLen + 'px';
        if (lbl) lbl.textContent = best.lbl;
      } catch(_){}
    }
    window.__mapUnit = 'km';
    window.__updateRulers = function(){
      try {
        var W = window.innerWidth, H = window.innerHeight;
        var unit = window.__mapUnit || 'km';
        // Horizontal : plus de règle affichée (17/07), mais on mesure
        // toujours le segment 10 % → 90 % de la largeur à ~12 px du bas :
        // c'est la métrique de référence de la barre Navionics.
        var yH = H - 12;
        var dH = vpToLatLng(W * 0.1, yH).distanceTo(vpToLatLng(W * 0.9, yH));
        // Vertical : de 10 % à 90 % de la HAUTEUR du viewport, à ~10 px du
        // bord gauche.
        var xV = 10;
        var dV = vpToLatLng(xV, H * 0.1).distanceTo(vpToLatLng(xV, H * 0.9));
        setRuler('sm-ruler-v', dV, unit);
        updateNavBar(unit, dH);
      } catch(_){}
    };
    window.__setMapUnit = function(u){
      window.__mapUnit = (u === 'nm') ? 'nm' : 'km';
      window.__updateRulers();
    };
    map.on('move zoom resize viewreset', window.__updateRulers);
    window.__updateRulers();
  })();
  // 16/07/2026 (retour terrain « zones noires en mer ») — augmentation du
  // buffer de tuiles conservées en mémoire (2 → 4) : Leaflet garde ainsi
  // les tuiles environnantes après un pan/zoom léger, évitant les carrés
  // noirs le temps du téléchargement. Combiné au prefetch actif ci-dessous
  // (SM.prefetchAroundUser), ça donne un « cache navigateur » ~2 km autour
  // du bateau sur 3 zooms (Z-1, Z, Z+1) — voir SM.prefetchAroundUser.
  // 24/07/2026 (bug armateur « balises qui disparaissent ») — l'ingress de
  // la plateforme limite le débit : lors d'un pan/zoom rapide une partie des
  // requêtes de tuiles reçoit un 429 → la tuile reste VIDE (trou dans le
  // balisage jusqu'au prochain déplacement). On RÉ-ESSAIE automatiquement
  // chaque tuile en échec (backoff exponentiel 1 s / 2 s / 4 s + aléa, avec
  // cache-buster uniquement sur les retries pour forcer un vrai re-fetch).
  // 02/08/2026 — SILENCE RÉSEAU (window.__setNetQuiet) : pendant un calcul de
  // route, les requêtes secondaires de la carte (ré-essais de tuiles,
  // préchargement, isobathes, balises) sont mises en pause. L'ingress de la
  // plateforme limite les requêtes simultanées par IP : c'est ce qui faisait
  // échouer le calcul en « Erreur 429 » (et perdre le point de départ).
`;
}
