// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// window.SM : API appelée depuis React Native (vue, zoom, bateau, cône Nav,
// radar Vigie, opacité des signalements, projections de cap, follow-mode).

export function jsSmApi(crosshair: boolean) {
  return `  window.SM = {
    // 23/07/2026 — restauration INSTANTANÉE de la dernière vue après un
    // rechargement de la WebView (pas d'animation, et le recentrage auto est
    // mis en pause 5 s pour ne pas re-sauter sur la position GPS).
    setView: function(lat,lng,z){
      this.lastUserPan = Date.now();
      map.setView([lat,lng], z || map.getZoom(), {animate:false});
    },
    flyTo: function(lat,lng,z){
      // Un flyTo programmatique (nouveau signalement, bannière, focus…)
      // accorde le même délai de grâce de 5 s que un geste utilisateur
      // avant que le recentrage automatique ne reprenne la main.
      this.lastUserPan = Date.now();
      map.flyTo([lat,lng], z || map.getZoom(), {duration:0.8});
    },
    // 13/07/2026 — accorde 5 s de grâce au recentrage auto SANS bouger la
    // carte (retour depuis un écran détail, tap sur la carte, etc.).
    grantGrace: function(){ this.lastUserPan = Date.now(); },
    // 20/07/2026 — auto-recentrage en PAUSE (appui long / consultation libre).
    // Réactivé UNIQUEMENT quand l'utilisateur tape le bouton de recentrage.
    followSuspended: false,
    setFollowSuspended: function(on){ this.followSuspended = !!on; },
    // Zoom INSTANTANÉ (non animé) — indispensable en follow-mode : le
    // recentrage périodique (setUser → recenterOnUser) réutilise
    // map.getZoom() et annulerait toute animation de zoom en cours.
    setZoom: function(z){
      this.programmaticMove = true;
      try { map.setView(map.getCenter(), z, { animate: false }); }
      finally { var self=this; setTimeout(function(){ self.programmaticMove = false; }, 50); }
    },
    // Boutons +/- natifs côté gauche (12/07/2026) — zoom pas-à-pas instantané.
    zoomIn: function(){ this.setZoom(Math.min(map.getMaxZoom ? map.getMaxZoom() : 19, map.getZoom() + 1)); },
    zoomOut: function(){ this.setZoom(Math.max(map.getMinZoom ? map.getMinZoom() : 2, map.getZoom() - 1)); },
    setCrosshair: function(on){
      this.crosshairOn = !!on;
      document.getElementById('ch').style.display = on ? 'block':'none';
    },
    // Phase I — Navigation projection helpers.
    userHeading: null,
    // 28/07 (retour armateur) — projection de cap réel (rouge) forcée en
    // Navigation ET en suivi de route (indépendante des paramètres du cône).
    headingLineOn: false,
    userSpeed: null,
    userTrail: null,          // L.polyline showing the projected route ahead
    userIsBoat: false,        // whether the current marker is the boat arrow
    bearing: null,            // course-up rotation applied to the map (deg)
    /** Phase J — follow-mode state. */
    navMode: false,
    lastUserPan: 0,
    userDragging: false,
    crosshairOn: ${crosshair},
    programmaticMove: false,
    lastHeadingApplied: null,
    /** Phase K — Navigation cone (yellow). Redrawn each time setUser is
     *  called with a valid heading + speed. Params are set by setNavCone(). */
    coneLayer: null,
    coneHalfAngle: null,
    coneDistanceKm: null,
    // 17/07/2026 (v2 cône coloré) — état visuel courant du cône navigation.
    // Piloté depuis React via SM.setConeState('green'|'orange'|'red').
    // Persisté ici pour que redrawNavCone conserve la bonne couleur au
    // rebuild (ex. rotation course-up, changement de cap, redraw ping).
    coneStateWanted: 'green',
    __coneStyleForState: function(state){
      switch (state) {
        case 'red':
          return { color:'#EF4444', weight:3.0, fillOpacity:0.20, dashArray:null };
        case 'orange':
          // Dashed épais → distinctible en daltonisme même sans couleur.
          return { color:'#F59E0B', weight:3.2, fillOpacity:0.14, dashArray:'10,7' };
        case 'green':
        default:
          return { color:'#22C55E', weight:1.8, fillOpacity:0.10, dashArray:null };
      }
    },
    setConeState: function(state){
      if (state !== 'green' && state !== 'orange' && state !== 'red') state = 'green';
      this.coneStateWanted = state;
      if (!this.coneLayer) return;
      var s = this.__coneStyleForState(state);
      try {
        this.coneLayer.setStyle({
          color: s.color, weight: s.weight, opacity: 0.95,
          fillColor: s.color, fillOpacity: s.fillOpacity,
          dashArray: s.dashArray,
        });
        // Bascule la classe CSS (pulse pour red, textures pour daltonisme).
        var el = this.coneLayer._path;
        if (el) {
          el.classList.remove('sm-nav-cone--green', 'sm-nav-cone--orange', 'sm-nav-cone--red');
          el.classList.add('sm-nav-cone--' + state);
        }
      } catch(_){}
    },
    // Phase K.5 — Radar ping (Vigie mode). 3 stacked circles at 0.33/0.66/1.0
    // of the alert radius, each with CSS animation staggered so it looks like
    // a soft sonar pulse. Recreated when radiusM changes; position tracks the
    // boat marker every setUser tick.
    // Phase K.5 — Radar ping (Vigie mode). 2 rings expanding from the boat
    // to the alert radius, driven by requestAnimationFrame so we can insert
    // a 1.5–1.75 s pause between two consecutive waves. Each ring runs a
    // 1.5 s ease-out expansion then goes idle for the pause; the second ring
    // is offset by half a cycle so waves alternate smoothly (CSS-driven).
    pingLayers: null,
    pingRadiusM: 0,
    setRadarPing: function(radiusM){
      var target = (typeof radiusM === 'number' && radiusM > 0) ? radiusM : 0;
      // Redraw needed when the radius changed OR the layers died (e.g. after
      // a Vigie↔Nav round-trip or a WebView init race) — safely idempotent.
      if (target === this.pingRadiusM && this.pingLayers) { return; }
      this.pingRadiusM = target;
      this.drawRadarPing();
    },
    drawRadarPing: function(){
      // 20/07/2026 — animation 100 % CSS (voir .sm-radar-ping) : plus AUCUN
      // requestAnimationFrame ici. On pose simplement 2 cercles Leaflet au
      // rayon FIXE de la zone de veille ; le CSS anime scale + opacité.
      // Remove previous layers.
      if (this.pingLayers){
        for (var i=0;i<this.pingLayers.length;i++){ try { map.removeLayer(this.pingLayers[i]); } catch(_){} }
        this.pingLayers = null;
      }
      if (!userMarker || !this.pingRadiusM) return;
      var ll = userMarker.getLatLng();
      // 26/07 (bug vidéo armateur « la vigie scintille avec le compas ») —
      // les anneaux radar partageaient le <svg> Leaflet global : chaque
      // mise à jour du compas de mesure (polylignes redessinées à chaque
      // tick GPS aimanté) re-calculait le SVG entier → l'animation CSS des
      // anneaux (transform-box:fill-box) repartait par à-coups. PANE DÉDIÉ
      // + renderer SVG séparé : plus aucune interaction entre les couches.
      if (!map.getPane('smRadarPane')){
        var rp = map.createPane('smRadarPane');
        rp.style.zIndex = 350;           // sous l'overlayPane (400) → sous routes/mesure
        rp.style.pointerEvents = 'none';
      }
      if (!this._radarRenderer) this._radarRenderer = L.svg({ pane: 'smRadarPane' });
      // Phase K.10 — Radar drawn at the exact user-configured alert radius
      // (Zone de veille Vigie — voiceSettings.zoneVigieM, valeur fixe).
      // Ratio 1:1 with the map scale so 25 km configured = 25 km ring on screen.
      var maxR = this.pingRadiusM;
      var layers = [];
      // 2 anneaux identiques, décalés d'un demi-cycle via la classe CSS.
      for (var i = 0; i < 2; i++){
        var c = L.circle(ll, {
          radius: maxR,
          color: '#E63946',
          weight: 2.5,
          opacity: 0.9,
          fill: false,
          interactive: false,
          className: 'sm-radar-ping' + (i === 1 ? ' sm-radar-b' : ''),
          bubblingMouseEvents: false,
          pane: 'smRadarPane',
          renderer: this._radarRenderer,
        }).addTo(map);
        layers.push(c);
      }
      this.pingLayers = layers;
    },
    updateRadarPingPos: function(){
      if (!this.pingLayers || !userMarker) return;
      var ll = userMarker.getLatLng();
      for (var i=0;i<this.pingLayers.length;i++){ this.pingLayers[i].setLatLng(ll); }
    },
    /** Store current markers-latlng dict so updateReportsOpacity can be a
     *  fast in-place iteration without re-fetching from markers[]. */
    currentReports: [],
    // ── Anti-clignotement (14/07/2026) ─────────────────────────────
    // État courant d'opacité par marqueur (true=grisé) et changements en
    // attente (anti-rebond 1,5 s sur le GRISAGE uniquement).
    dimState: {},
    dimPending: {},
    DIM_DEBOUNCE_MS: 1500,
    setNavCone: function(halfAngleDeg, distKm){
      this.coneHalfAngle = (typeof halfAngleDeg === 'number' && halfAngleDeg > 0) ? halfAngleDeg : null;
      this.coneDistanceKm = (typeof distKm === 'number' && distKm > 0) ? distKm : null;
      this.drawCone();
      this.refreshTrail();
      this.updateReportsOpacity();
    },
    refreshTrail: function(){
      // Redraw / remove the long red projection line based on the current
      // cone-active state. Called from setUser (each GPS tick) and from
      // setNavCone (mode toggle) so the trail vanishes as soon as user
      // switches to Vigie mode without waiting for the next GPS update.
      if (this.userTrail){ map.removeLayer(this.userTrail); this.userTrail = null; }
      if (!userMarker || !this.userIsBoat) return;
      if (this.userHeading == null) return;
      // 28/07 (retour armateur) — la PROJECTION DE CAP RÉEL (rouge) doit
      // s'afficher en mode Navigation ET pendant le SUIVI DE ROUTE (en plus
      // de la ligne verte « cap à suivre »). Elle était auparavant liée aux
      // seuls paramètres du cône (mode Navigation) → disparue en suivi de
      // route et parfois en navigation simple. On la pilote désormais par un
      // drapeau dédié (headingLineOn = Navigation OU suivi de route).
      if (!this.headingLineOn && (this.coneHalfAngle == null || this.coneDistanceKm == null)) return;
      var ll = userMarker.getLatLng();
      // 15/07/2026 (bug terrain, capture user) : la ligne était tracée comme
      // UNE corde droite de 500 km — or une géodésique de 500 km COURBE sur
      // la projection Mercator, la corde s'écartait donc de l'axe du couloir
      // (lui, calculé par points géodésiques successifs). On échantillonne
      // désormais la géodésique tous les 25 km : la ligne rouge passe
      // exactement par l'axe du cône, à tous les caps.
      var pts = [[ll.lat, ll.lng]];
      for (var dk = 25; dk <= 500; dk += 25){
        pts.push(destPoint(ll.lat, ll.lng, this.userHeading, dk));
      }
      this.userTrail = L.polyline(pts, {
        color:'#E63946', weight:3, opacity:0.95, interactive:false,
      }).addTo(map);
      try { this.userTrail.bringToFront(); } catch(_){}
    },
    // ── 28/07/2026 (demande armateur) — PROJECTION « CAP À SUIVRE » ──────
    // Clone de la projection de cap (ligne rouge) mais VERT FONCÉ, tracée
    // depuis le bateau le long du cap à suivre pendant la NAVIGATION d'une
    // route. Tap sur la ligne → étiquette « Cap à suivre — XXX° » (3 s).
    targetBearing: null,
    targetTrail: null,
    targetTrailHalo: null,
    targetTagMarker: null,
    refreshTargetTrail: function(){
      if (this.targetTrail){ try { map.removeLayer(this.targetTrail); } catch(_){} this.targetTrail = null; }
      if (this.targetTrailHalo){ try { map.removeLayer(this.targetTrailHalo); } catch(_){} this.targetTrailHalo = null; }
      if (this.targetBearing == null || !userMarker) {
        if (this.targetTagMarker){ try { map.removeLayer(this.targetTagMarker); } catch(_){} this.targetTagMarker = null; }
        return;
      }
      var ll = userMarker.getLatLng();
      var brg = this.targetBearing;
      // Géodésique échantillonnée (même règle que la projection rouge).
      var pts = [[ll.lat, ll.lng]];
      for (var dk = 25; dk <= 500; dk += 25){
        pts.push(destPoint(ll.lat, ll.lng, brg, dk));
      }
      this.targetTrailHalo = L.polyline(pts, {
        color:'#FFFFFF', weight:6, opacity:0.55, interactive:false,
      }).addTo(map);
      this.targetTrail = L.polyline(pts, {
        color:'#15803D', weight:3.5, opacity:0.95, interactive:true,
        bubblingMouseEvents:false,
      }).addTo(map);
      var self = this;
      this.targetTrail.on('click', function(ev){
        try {
          if (self.targetTagMarker){ map.removeLayer(self.targetTagMarker); self.targetTagMarker = null; }
          var deg = Math.round(((self.targetBearing % 360) + 360) % 360);
          self.targetTagMarker = L.marker(ev.latlng, {
            interactive: false,
            icon: L.divIcon({
              className: '',
              html: '<div class="sm-tag-anchor"><div class="sm-tag" style="transform:translate(-50%,-130%);border-color:#15803D;color:#B7F5C9;">Cap à suivre — ' + String(deg).padStart(3, '0') + '°</div></div>',
              iconSize: [0, 0], iconAnchor: [0, 0],
            }),
          }).addTo(map);
          setTimeout(function(){
            if (self.targetTagMarker){ try { map.removeLayer(self.targetTagMarker); } catch(_){} self.targetTagMarker = null; }
          }, 3000);
        } catch(_){}
      });
      try { this.targetTrail.bringToFront(); } catch(_){}
    },
    drawCone: function(){
      if (this.coneLayer){ map.removeLayer(this.coneLayer); this.coneLayer = null; }
      if (!userMarker || !this.userIsBoat) return;
      if (this.coneHalfAngle == null || this.coneDistanceKm == null) return;
      if (this.userHeading == null) return;
      var ll = userMarker.getLatLng();
      var hd = this.userHeading;
      var half = this.coneHalfAngle;
      var totalDist = this.coneDistanceKm;
      var flareKm = 1.0;
      var halfRad = half * Math.PI / 180;
      var halfWidthKm = flareKm * Math.sin(halfRad);
      var alongFlareKm = flareKm * Math.cos(halfRad);
      // If the total forward reach is smaller than the flare projection
      // itself, we just draw a triangle (no corridor section).
      var effectiveEndKm = Math.max(totalDist, alongFlareKm + 0.05);
      // Convert local (perp, along) km → lat/lng. Perp is positive to the right
      // of heading. Along is along heading.
      function toLL(perpKm, alongKm){
        if (perpKm === 0 && alongKm === 0) return [ll.lat, ll.lng];
        var d = Math.sqrt(perpKm*perpKm + alongKm*alongKm);
        var b = hd + Math.atan2(perpKm, alongKm) * 180 / Math.PI;
        return destPoint(ll.lat, ll.lng, b, d);
      }
      var verts = [
        toLL(0, 0),
        toLL(-halfWidthKm, alongFlareKm),
      ];
      // 15/07/2026 — les longs bords du couloir sont échantillonnés (pas de
      // simple corde droite) : sur de grandes distances, une corde s'écarte
      // de la géodésique en Mercator et le couloir n'était plus centré sur
      // la ligne de cap (capture user). Pas d'échantillon ≈ 1/24 de longueur.
      var stepKm = Math.max(2, (effectiveEndKm - alongFlareKm) / 24);
      var a;
      for (a = alongFlareKm + stepKm; a < effectiveEndKm; a += stepKm){
        verts.push(toLL(-halfWidthKm, a));
      }
      verts.push(toLL(-halfWidthKm, effectiveEndKm));
      verts.push(toLL( halfWidthKm, effectiveEndKm));
      for (a = effectiveEndKm - stepKm; a > alongFlareKm; a -= stepKm){
        verts.push(toLL( halfWidthKm, a));
      }
      verts.push(toLL( halfWidthKm, alongFlareKm));
      // ─── 17/07/2026 (v2 cône coloré) ──────────────────────────────────
      // Le cône est créé en VERT (état par défaut, aucun signalement dans
      // le cône). SM.setConeState(state) modifiera couleur + style ensuite.
      // Palette (validée UX : distinctive même en daltonisme rouge/vert
      // grâce à la texture — dashed pour orange, pulse pour rouge) :
      //   • green  → #22C55E  fin uni      (rien dans le cône)
      //   • orange → #F59E0B  dashed épais  (signalement présent mais hors
      //                                       zone d'alerte critique)
      //   • red    → #EF4444  solide + pulse 1 Hz (signalement dans zone
      //                                             d'alerte → sonne aussi)
      var initState = (this.coneStateWanted || 'green');
      var initStyle = this.__coneStyleForState(initState);
      this.coneLayer = L.polygon(verts, {
        color: initStyle.color, weight: initStyle.weight, opacity: 0.95,
        fillColor: initStyle.color, fillOpacity: initStyle.fillOpacity,
        dashArray: initStyle.dashArray, lineJoin: 'round',
        interactive: true,
        className: 'sm-nav-cone sm-nav-cone--' + initState,
        bubblingMouseEvents: false,
      }).addTo(map);
      try { this.coneLayer.bringToBack(); } catch(_){}
      // Tap on cone → sober info popup with flare + corridor dimensions.
      this.coneLayer.off('click');
      this.coneLayer.on('click', function(e){
        var wKm = 2 * halfWidthKm;
        var content = '<div class="sm-cone-info">'
          + '<div class="ttl">Cône de navigation</div>'
          + '<div class="row"><span class="lbl">Évasement</span><span class="val">' + flareKm.toFixed(1) + ' km</span></div>'
          + '<div class="row"><span class="lbl">Corridor</span><span class="val">' + wKm.toFixed(2) + ' × ' + totalDist.toFixed(1) + ' km</span></div>'
          + '<div class="row"><span class="lbl">Angle</span><span class="val">' + Math.round(half * 2) + '°</span></div>'
          + '</div>';
        L.popup({ className: 'sm-cone-popup', closeButton: false, autoPan: false, offset: [0, -6] })
          .setLatLng(e.latlng)
          .setContent(content)
          .openOn(map);
        try { L.DomEvent.stopPropagation(e); } catch(_){}
      });
    },
    updateReportsOpacity: function(){
      if (!markers) return;
      var boatLat = null, boatLng = null;
      if (userMarker && this.userIsBoat){
        var ll = userMarker.getLatLng();
        boatLat = ll.lat; boatLng = ll.lng;
      }
      var half = this.coneHalfAngle;
      var dist = this.coneDistanceKm;
      var hd = this.userHeading;
      var coneActive = (boatLat != null && half != null && dist != null && hd != null);
      var arr = this.currentReports || [];
      var now = Date.now();
      for (var i = 0; i < arr.length; i++){
        var r = arr[i];
        var m = markers[r.id];
        if (!m) continue;
        var el = m.getElement && m.getElement();
        if (!el) continue;
        var hit = el.querySelector && el.querySelector('.sm-hit');
        if (!hit) continue;

        // ── ANTI-CLIGNOTEMENT (14/07/2026, retour terrain) ──────────────
        // Le jitter GPS (cap ±2-5°/s + position) fait balayer la frontière
        // du couloir sur les marqueurs proches → bascule gris↔couleur à
        // 1 Hz (« clignotement »). Deux gardes VISUELLES (le déclenchement
        // des alertes, lui, vit dans sound-alert.ts et n'est PAS touché) :
        //  1. HYSTÉRÉSIS géométrique : pour passer de allumé→grisé, il faut
        //     être hors d'un couloir ÉLARGI (+5° d'angle, +12 % de longueur) ;
        //     pour repasser grisé→allumé, il faut être dans le couloir exact.
        //  2. ANTI-REBOND temporel : le changement d'état doit persister
        //     ≥ 1,5 s avant d'être appliqué au marqueur.
        var target;
        if (!coneActive){
          target = false; // Vigie / pas de cap → tout allumé, immédiatement.
        } else {
          var cur = Object.prototype.hasOwnProperty.call(this.dimState, r.id)
            ? !!this.dimState[r.id]
            : null; // premier passage : pas d'état connu
          if (cur === true){
            // Grisé → se rallume dès qu'il entre dans le couloir EXACT.
            target = !isInsideCone(r.lat, r.lng, boatLat, boatLng, hd, half, dist);
          } else {
            // Allumé (ou inconnu) → ne se grise que s'il est clairement hors
            // du couloir ÉLARGI (marge anti-jitter).
            target = !isInsideCone(r.lat, r.lng, boatLat, boatLng, hd, half + 5, dist * 1.12);
          }
          if (cur === null){
            // Premier passage (nouveau marqueur / entrée en mode Nav) :
            // application immédiate, sans anti-rebond.
            this.dimState[r.id] = target;
            delete this.dimPending[r.id];
            if (target){ hit.classList.add('sm-outside-cone'); }
            else { hit.classList.remove('sm-outside-cone'); }
            continue;
          }
          if (target !== cur){
            if (!target){
              // Rallumage (entrée dans le couloir exact) : IMMÉDIAT — pour
              // re-griser ensuite il faudra sortir du couloir ÉLARGI pendant
              // ≥ 1,5 s, donc pas d'aller-retour possible (anti-jitter).
              delete this.dimPending[r.id];
            } else {
              var p = this.dimPending[r.id];
              if (!p || p.state !== target){
                this.dimPending[r.id] = { state: target, since: now };
                target = cur; // pas encore stabilisé → on garde l'état courant
              } else if (now - p.since < this.DIM_DEBOUNCE_MS){
                target = cur; // en cours de stabilisation
              } else {
                delete this.dimPending[r.id]; // stabilisé → on grise
              }
            }
          } else {
            delete this.dimPending[r.id];
          }
        }
        this.dimState[r.id] = target;
        if (target){ hit.classList.add('sm-outside-cone'); }
        else { hit.classList.remove('sm-outside-cone'); }
      }
    },
    /** Dernière position GPS jugée fiable (i.e. obtenue alors que la vitesse
     *  dépassait le seuil). Quand on retombe sous le seuil, on RÉUTILISE
     *  cette position au lieu d'accepter le bruit du GPS (qui fait dériver
     *  le marqueur de 5-15 m même bateau parfaitement à l'arrêt). */
    lastReliablePos: null,
    /** 3 km/h in m/s (0.833) — below this speed, the GPS heading is jitter,
     *  so we hold the last reliable position + heading instead of letting
     *  the map vibrate. Same threshold used for the auto course-up switch
     *  in the useEffect below: < 3 km/h → freeze north-up, ≥ 3 km/h → rotate
     *  to heading. */
    MIN_NAV_SPEED_MS: 0.833,
    setNavMode: function(on, skipRecenter){
      this.navMode = !!on;
      if (this.navMode && userMarker && !skipRecenter) this.recenterOnUser(true);
      if (!this.navMode) {
        this.lastHeadingApplied = null;
        this.lastReliablePos = null;
        // Phase K — Kill the yellow cone & restore full opacity to markers
        // as soon as the pilot leaves Navigation mode.
        if (this.coneLayer){ map.removeLayer(this.coneLayer); this.coneLayer = null; }
        this.coneHalfAngle = null;
        this.coneDistanceKm = null;
        this.dimState = {};
        this.dimPending = {};
        this.updateReportsOpacity();
      }
    },
    /** Recentre la carte sur le bateau en plaçant l'icône :
     *  • horizontalement au milieu de l'écran,
     *  • verticalement à 60 % depuis le haut (= 3/5).
     *  Le décalage tient compte de la rotation course-up active. */
    recenterOnUser: function(animate){
      if (!userMarker) return;
      var ll = userMarker.getLatLng();
      var z = map.getZoom();
      var center;
      if (this.navMode){
        var vh = window.innerHeight;
        var bearing = this.bearing || 0;
        var rad = bearing * Math.PI / 180;
        // Décalage en pixels (dans le repère du div carte, non-tourné) :
        // on veut placer le marqueur 10 % vh sous le centre du viewport.
        var V = vh * 0.10;
        var dx = -V * Math.sin(rad);
        var dy =  V * Math.cos(rad);
        var p = map.project(ll, z).subtract(L.point(dx, dy));
        center = map.unproject(p, z);
      } else {
        center = ll;
      }
      this.programmaticMove = true;
      try {
        map.setView(center, z, { animate: animate !== false, duration: 0.45 });
      } finally {
        var self = this;
        setTimeout(function(){ self.programmaticMove = false; }, 600);
      }
    },
    /** Phase I (v5) — Rotate the map smoothly so the heading points UP.
     *  We accumulate the rotation continuously (no mod-360 reset) so the
     *  CSS transition always animates the SHORTEST arc — fixes the 359°→1°
     *  glitch that previously made the map spin 358° backwards. */
    bearingApplied: 0,
    setBearing: function(deg){
      var el = document.getElementById('map');
      if (!el) return;
      if (typeof deg !== 'number'){
        this.bearing = null;
        this.bearingApplied = 0;
        el.style.transform = 'translate(-50%, -50%)';
        el.style.setProperty('--sm-counter', '0deg');
      } else {
        // Shortest delta between the current applied angle (mod 360) and the
        // new target. Result lies in (-180, 180].
        var cur = ((this.bearingApplied % 360) + 360) % 360;
        var delta = ((deg - cur + 540) % 360) - 180;
        this.bearingApplied += delta;
        this.bearing = deg;
        el.style.transform = 'translate(-50%, -50%) rotate(' + (-this.bearingApplied) + 'deg)';
        el.style.setProperty('--sm-counter', this.bearingApplied + 'deg');
      }
      // Re-render the boat so its inline rotation (= heading - bearing)
      // converges to 0 in course-up mode and the triangle stays straight up.
      if (userMarker && this.userIsBoat){
        var ll = userMarker.getLatLng();
        this.setUser(ll.lat, ll.lng, this.userHeading, this.userSpeed, true);
      }
      // La rotation change la portion de carte sous les règles → recalcul.
      if (window.__updateRulers) window.__updateRulers();
    },
    setUser: function(lat,lng,heading,speed,asBoat){
      var hd = (typeof heading === 'number' && heading >= 0) ? heading : this.userHeading;
      var sp = (typeof speed === 'number' && speed >= 0) ? speed : this.userSpeed;
      // Phase J — jitter gate. En mode bateau (navigation), si la vitesse
      // est sous 1 nœud :
      //   • on FIGE le cap au dernier cap fiable,
      //   • on FIGE LA POSITION sur la dernière position fiable enregistrée
      //     (sinon le marker dérive de 5-15 m à cause du bruit GPS et fait
      //     vibrer toute la carte via le follow-mode).
      if (asBoat) {
        var fastEnough = (typeof sp === 'number' && sp >= this.MIN_NAV_SPEED_MS);
        if (fastEnough) {
          this.lastReliablePos = { lat: lat, lng: lng };
          if (typeof hd === 'number' && hd >= 0) this.lastHeadingApplied = hd;
        } else {
          if (this.lastReliablePos) {
            lat = this.lastReliablePos.lat;
            lng = this.lastReliablePos.lng;
          } else {
            // Premier fix reçu en nav mode mais sans vitesse — on l'accepte
            // comme position de référence pour bloquer les suivants.
            this.lastReliablePos = { lat: lat, lng: lng };
          }
          if (this.lastHeadingApplied != null) hd = this.lastHeadingApplied;
        }
      }
      this.userHeading = hd;
      this.userSpeed = sp;
      // In course-up mode the container is already rotated by -bearing, so
      // the boat's inner triangle just needs to undo that to point straight
      // up. Math: screen-rot = -bearing + counter + inline-rot = inline-rot.
      // We want screen-rot = 0 → inline-rot = bearing. Wait — let me redo:
      //   container: rotate(-bearing)
      //   .sm-boat-wrap: rotate(+bearing) (via --sm-counter, cancels container)
      //   .sm-boat: rotate(inline)  → net screen rot = inline
      // To point along heading (screen-up when bearing=heading) we want
      // inline = heading - bearing. ✅
      var rot = (hd != null) ? (hd - (this.bearing || 0)) : 0;
      var iconSize = asBoat ? [40,40] : [18,18];
      var anchor   = asBoat ? [20,20] : [9,9];
      var html;
      if (asBoat) {
        html = '<div class="sm-boat-wrap">'
             + '<div class="sm-boat-halo"></div>'
             + '<div class="sm-boat" style="transform:rotate('+rot+'deg)"></div>'
             + '</div>';
      } else {
        html = '<div class="sm-user"></div>';
      }
      var icon = L.divIcon({className:'',html:html,iconSize:iconSize,iconAnchor:anchor});
      if (userMarker && this.userIsBoat !== asBoat) {
        map.removeLayer(userMarker);
        userMarker = null;
      }
      if (userMarker) {
        userMarker.setLatLng([lat,lng]);
        userMarker.setIcon(icon);
      } else {
        userMarker = L.marker([lat,lng], {icon:icon, zIndexOffset:1000, interactive:false}).addTo(map);
      }
      this.userIsBoat = !!asBoat;
      // 24/07 — compas de mesure : les extrémités aimantées au bateau suivent.
      if (window.__msBoatTick) window.__msBoatTick(lat, lng);
      // Projection line — only visible in Navigation mode (yellow cone active).
      // Delegated to refreshTrail() so setNavCone can also update it when the
      // user toggles the mode without waiting for the next GPS tick.
      this.refreshTrail();
      // 28/07 — la projection « cap à suivre » (verte) suit aussi le bateau.
      this.refreshTargetTrail();
      // Recentrage automatique (10/07/2026) — Vigie ET Navigation :
      // l'utilisateur peut consulter librement la carte ; 5 s après la FIN
      // de son geste (dragend/zoomend — plus le début comme avant), la
      // carte se recentre sur le bateau à chaque tick GPS. Jamais pendant
      // un drag en cours ni en mode placement de signalement (croix rouge).
      // recenterOnUser gère la différence : Vigie = centré, Nav = ancrage 3/5.
      if (asBoat && !this.userDragging && !this.crosshairOn &&
          !this.followSuspended &&
          (Date.now() - this.lastUserPan) >= 5000) {
        this.recenterOnUser(true);
      }
      // Phase K — Redraw the yellow navigation cone at the new position/
      // heading, and refresh the outside-cone opacity on every report.
      this.drawCone();
      this.updateReportsOpacity();
      // Phase K.5 — Keep the radar ping centred on the boat. If the marker
      // was just (re)created (e.g. after a Vigie/Nav toggle or first fix),
      // ensure the rings are (re)drawn — updateRadarPingPos is a no-op when
      // no layers exist yet.
      if (!this.pingLayers) this.drawRadarPing();
      else this.updateRadarPingPos();
    },
    /** Phase I — clear the projection line and reset to the legacy blue dot. */
    clearBoat: function(){
      if (this.userTrail){ map.removeLayer(this.userTrail); this.userTrail = null; }
      if (this.coneLayer){ map.removeLayer(this.coneLayer); this.coneLayer = null; }
      // We DON'T remove userMarker — the dot variant takes its place via the
      // next setUser() call. If the marker exists as a boat, swap it.
    },
    setReports: function(list){
      // Phase K — Remember the reports so updateReportsOpacity() can iterate
      // in place after each GPS tick without needing to rebuild anything.
      this.currentReports = list || [];
      // 17/07/2026 (retour terrain « carte noire pendant une alerte ») —
      // sur Android certains cas d'affichage (bannière d'alerte plein
      // écran, apparition d'une modale au-dessus du WebView, split-screen)
      // laissent Leaflet avec une taille de conteneur invalidée : les
      // tuiles ne se redemandent plus et la carte apparaît noire (fond du
      // body). Un invalidateSize défensif à chaque
      // rafraîchissement des reports (toutes les ~90 s) corrige ça sans
      // impact visible.
      try { map.invalidateSize({animate: false}); } catch(_){}
      var keep = {};
      var keepArrows = {};
      var keepCones = {};
      for (var i=0;i<list.length;i++){
        var r = list[i];
        keep[r.id] = true;
        // ---- Drift cone (Phase B) -------------------------------------
        // Drawn first so the marker icon visually sits on top of it.
        if (r.drift_cone && r.drift_cone.polygon && r.drift_cone.polygon.length >= 3
            && r.drift_cone.distance_km > 0.005){
          keepCones[r.id] = true;
          var pts = r.drift_cone.polygon.map(function(p){ return [p.lat, p.lng]; });
          // Arc middle & apex from the polygon vertices (robust for legacy
          // reports missing r.drift_cone.bearing_deg).
          var arcMidIdx = Math.floor((pts.length - 1) / 2) + 1;
          if (arcMidIdx >= pts.length) arcMidIdx = pts.length - 1;
          var apex = pts[0];
          var arcMid = pts[arcMidIdx];
          // Label right at the arc extremity (92% along the axis) — user
          // requested the text to hug the outer edge, not the middle.
          var lblLat = apex[0] + (arcMid[0] - apex[0]) * 0.92;
          var lblLng = apex[1] + (arcMid[1] - apex[1]) * 0.92;
          var popupLat = arcMid[0], popupLng = arcMid[1];
          // Compute the *screen*-space rotation so the text runs PARALLEL
          // to the arc (perpendicular to the drift bearing). We use a
          // Mercator-flat approximation which is more than accurate enough
          // over a ~10 km cone.
          var latAvg = (apex[0] + arcMid[0]) / 2;
          var dxScr = (arcMid[1] - apex[1]) * Math.cos(latAvg * Math.PI / 180);
          var dyScr = -(arcMid[0] - apex[0]); // screen Y grows downward
          // Bearing measured clockwise from screen-up (north).
          var bearingScr = Math.atan2(dxScr, -dyScr) * 180 / Math.PI;
          // Text parallel to arc = same angle. Normalize so it stays upright
          // (never printed upside-down).
          var textRot = bearingScr;
          while (textRot >  90) textRot -= 180;
          while (textRot < -90) textRot += 180;
          textRot = Math.round(textRot);
          // Only show the label when the arc is wide enough on screen to
          // fit the text — otherwise it overflows the cone which looks bad.
          // We measure the arc's outer chord in *pixels* via the current
          // map projection, then compare it against the label width.
          var LBL_TEXT = 'Position dans +/- 1 h';
          var LBL_FONT_PX = 11;        // matches CSS .sm-cone-label font-size
          var labelPxW = Math.max(120, LBL_TEXT.length * (LBL_FONT_PX * 0.55) + 20);
          var arcChordPx = 0;
          try {
            var arcStart = pts[1] || arcMid;
            var arcEnd = pts[pts.length - 1] || arcMid;
            var p1 = map.latLngToLayerPoint(arcStart);
            var p2 = map.latLngToLayerPoint(arcEnd);
            arcChordPx = Math.hypot(p2.x - p1.x, p2.y - p1.y);
          } catch(_){ arcChordPx = 0; }
          var showLabel = map.getZoom() >= 13 && arcChordPx >= labelPxW * 0.85;
          var lblHtml = '<span class="sm-cone-label" style="transform:rotate(' + textRot + 'deg)">' + LBL_TEXT + '</span>';

          // Popup content — always built from THIS cone's data.
          var popupParts = ['<b>Cône de dérive</b>'];
          if (typeof r.drift_cone.distance_km === 'number'){
            var km = r.drift_cone.distance_km < 1
              ? Math.round(r.drift_cone.distance_km * 1000) + ' m'
              : r.drift_cone.distance_km.toFixed(2) + ' km';
            popupParts.push('Position estimée à ~ 1 h : <b>' + km + '</b>');
          }
          if (typeof r.drift_cone.bearing_deg === 'number'){
            popupParts.push('Cap : <b>' + Math.round(r.drift_cone.bearing_deg) + '°</b>');
          }
          if (r.drift_cone.wind_source){
            popupParts.push('Vent : ' + r.drift_cone.wind_source);
          }
          // Bande côtière < 20 km (13/07/2026) : courant modèle non fiable →
          // dérive au vent seul + avertissement clair au clic sur le cône.
          if (r.drift_cone.wind_only){
            popupParts.push('<span class="sm-cone-warn">\u26A0\uFE0F Dérive estimée uniquement avec les valeurs des vents sur le secteur, utilisez vos connaissances des courants locaux pour affiner l\u2019estimation de la direction de dérive de l\u2019objet.</span>');
          }
          var popupContent = popupParts.join('<br/>');

          if (cones[r.id]){
            // Legacy migration: old polygons were created before the E.6c fix
            // (bubblingMouseEvents:false + arc-mid manual popup). They still
            // exhibit the "popup on wrong cone" bug because their options are
            // frozen at creation time. Detect that case and force a full
            // rebuild — new polygons flow through the else-branch below.
            if (cones[r.id].poly && cones[r.id].poly.options
                && cones[r.id].poly.options.bubblingMouseEvents !== false){
              try { map.removeLayer(cones[r.id].poly); } catch(_){}
              if (cones[r.id].label){
                try { map.removeLayer(cones[r.id].label); } catch(_){}
              }
              delete cones[r.id];
            }
          }
          if (cones[r.id]){
            cones[r.id].poly.setLatLngs(pts);
            cones[r.id].popupLatLng = [popupLat, popupLng];
            cones[r.id].popupContent = popupContent;
            cones[r.id].arcChordPx = arcChordPx;
            if (cones[r.id].label){
              cones[r.id].label.setLatLng([lblLat, lblLng]);
              cones[r.id].label.setIcon(L.divIcon({
                className: 'sm-cone-label-wrap', html: lblHtml,
                iconSize: [labelPxW, 22], iconAnchor: [labelPxW / 2, 11],
              }));
              if (showLabel) cones[r.id].label.addTo(map);
              else map.removeLayer(cones[r.id].label);
            } else if (showLabel) {
              cones[r.id].label = L.marker([lblLat, lblLng], {
                icon: L.divIcon({
                  className: 'sm-cone-label-wrap', html: lblHtml,
                  iconSize: [labelPxW, 22], iconAnchor: [labelPxW / 2, 11],
                }),
                interactive: false, keyboard: false, zIndexOffset: 800,
              }).addTo(map);
            }
          } else {
            var poly = L.polygon(pts, {
              color: '#FF6F1A', weight: 3, opacity: 1, dashArray: '8,5',
              fillColor: '#FFA94D', fillOpacity: 0.4,
              // Polygon does NOT intercept clicks — the map-level handler
              // below does the geometric hit-testing itself. This is the
              // only way to guarantee that a tap physically inside cone A's
              // polygon opens A's popup (and not a sibling B's, no matter
              // how they are stacked in Leaflet's render order).
              interactive: false,
              className: 'sm-drift-cone',
              bubblingMouseEvents: false,
            }).addTo(map);
            // Bind the report id on the polygon so the map-level click
            // handler can look up the correct popup content by id.
            poly._smReportId = r.id;
            var coneEntry = {
              poly: poly, label: null,
              reportId: r.id,
              popupLatLng: [popupLat, popupLng],
              popupContent: popupContent,
            };
            // Click handling is done at the map level via geometric
            // hit-testing (see map.on('click', ...) below). No per-polygon
            // handler here — that avoids the whole class of overlap bugs.
            if (showLabel) {
              coneEntry.label = L.marker([lblLat, lblLng], {
                icon: L.divIcon({
                  className: 'sm-cone-label-wrap', html: lblHtml,
                  iconSize: [labelPxW, 22], iconAnchor: [labelPxW / 2, 11],
                }),
                interactive: false, keyboard: false, zIndexOffset: 800,
              }).addTo(map);
            }
            cones[r.id] = coneEntry;
            try { poly.bringToBack(); } catch(_){}
          }
        }
        var color = r.color || '#48CAE4';
        var focusClass = r.focus ? ' sm-marker-focus' : '';
        var compactClass = (map.getZoom() < 12) ? ' sm-compact' : '';
        var emoji = TYPE_ICON[r.label] || (r.label || '?').charAt(0).toUpperCase();
        // Phase E.6 — removed the sm-galon (rank glyph) + sm-rel (reliability
        // score) overlays from the map pins. They cluttered the pin, forced
        // odd icon offsets, and often produced a stray "●" or "100" bubble
        // even when the underlying rank was unknown. The full grade and
        // reliability are still visible on the report detail screen.
        var galon = '';
        var rel = '';
        // 19/07/2026 — signalement de TEST (mode bêta) : badge orange.
        var testBadge = r.is_test ? '<span class="sm-test-badge">TEST</span>' : '';
        var pinHtml = '<div class="sm-hit"><div class="sm-pin'+focusClass+compactClass+'" style="background:'+color+'">'
                    + '<span class="sm-emoji">'+emoji+'</span>'+galon+rel+testBadge+'</div></div>';
        if (markers[r.id]){
          markers[r.id].setLatLng([r.lat, r.lng]);
          // Anti-flash (14/07/2026) : ne remplacer l'élément DOM de l'icône
          // que si son HTML a réellement changé (focus, zoom compact…) —
          // recréer le nœud à chaque poll provoquait un bref clignotement
          // (l'état grisé était perdu puis ré-appliqué).
          if (markers[r.id]._smPinHtml !== pinHtml){
            markers[r.id].setIcon(L.divIcon({className:'',html:pinHtml,iconSize:[54,54],iconAnchor:[27,27]}));
            markers[r.id]._smPinHtml = pinHtml;
          }
        } else {
          var icon = L.divIcon({className:'',html:pinHtml,iconSize:[54,54],iconAnchor:[27,27]});
          var m = L.marker([r.lat, r.lng], {icon:icon, riseOnHover:true}).addTo(map);
          m._smPinHtml = pinHtml;
          m.on('click', function(id){ return function(e){
            if (e && L.DomEvent) L.DomEvent.stopPropagation(e);
            postMsg({event:'marker', id:id});
          }; }(r.id));
          markers[r.id] = m;
        }
        // Heading / speed vector for authority + navigation reports.
        if (r.heading != null && r.speed_knots != null && r.speed_knots > 0){
          keepArrows[r.id] = true;
          // 5-minute projection in km: speed_kn * 1.852 / 12.
          var distKm = Math.max(0.3, Math.min(8, r.speed_knots * 1.852 / 12));
          var end = destPoint(r.lat, r.lng, r.heading, distKm);
          if (arrows[r.id]){
            arrows[r.id].line.setLatLngs([[r.lat, r.lng], end]);
            arrows[r.id].tip.setLatLng(end);
            arrows[r.id].tip.setIcon(L.divIcon({className:'',
              html:'<div class="sm-arrow-tip" style="background:'+color+';transform:rotate('+r.heading+'deg)">▲</div>',
              iconSize:[18,18], iconAnchor:[9,9]}));
          } else {
            var line = L.polyline([[r.lat, r.lng], end], {color: color, weight: 3, opacity: 0.85, dashArray: '6,4'}).addTo(map);
            var tip = L.marker(end, {icon: L.divIcon({className:'',
              html:'<div class="sm-arrow-tip" style="background:'+color+';transform:rotate('+r.heading+'deg)">▲</div>',
              iconSize:[18,18], iconAnchor:[9,9]})}).addTo(map);
            arrows[r.id] = { line: line, tip: tip };
          }
        }
      }
      var self2 = this;
      Object.keys(markers).forEach(function(id){
        if (!keep[id]){
          map.removeLayer(markers[id]); delete markers[id];
          delete self2.dimState[id]; delete self2.dimPending[id];
        }
      });
      Object.keys(arrows).forEach(function(id){
        if (!keepArrows[id]){
          map.removeLayer(arrows[id].line);
          map.removeLayer(arrows[id].tip);
          delete arrows[id];
        }
      });
      Object.keys(cones).forEach(function(id){
        if (!keepCones[id]){
          try { map.removeLayer(cones[id].poly); } catch(_){}
          if (cones[id].label){ try { map.removeLayer(cones[id].label); } catch(_){} }
          delete cones[id];
        }
      });
      // Phase K — Refresh per-marker opacity so newly-added reports get their
      // cone-inclusion state applied instantly (no waiting for next GPS tick).
      this.updateReportsOpacity();
    }
  };

`;
}
