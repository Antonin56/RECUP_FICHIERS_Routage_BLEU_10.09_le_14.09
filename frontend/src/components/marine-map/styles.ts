// SignalMar — feuille de style de la carte Leaflet (WebView).
// Découpée de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR.

export const MAP_CSS = `  html,body{margin:0;padding:0;height:100%;width:100%;background:#0B132B;overflow:hidden;}
  /* Phase I (v5) — Smoother course-up rotation:
     - longer transition (550ms ease-out) makes 1-Hz heading updates blend
     - cumulative angle math is done in setBearing so 359°→1° animates the
       short way (+2°) instead of -358°. */
  #map{position:absolute;top:50%;left:50%;width:140vmax;height:140vmax;
    transform-origin:50% 50%;transform:translate(-50%,-50%);
    transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .leaflet-container{background:#0B132B;}
  .leaflet-tile{filter:brightness(.78) contrast(1.05) saturate(.92);}
  .leaflet-control-attribution{font-size:9px;background:rgba(11,19,43,.7);color:#A3CEF1;}
  .leaflet-control-attribution a{color:#48CAE4;}
  .leaflet-control-zoom a{background:#1C2541;color:#fff;border:1px solid rgba(255,255,255,.15);}
  .leaflet-control-zoom a:hover{background:#22305B;}
  /* Lift bottom-left zoom controls above the tab bar / FAB area. */
  .leaflet-bottom.leaflet-left{bottom:88px !important;left:8px !important;}
  .leaflet-control-zoom{box-shadow:0 6px 18px rgba(0,0,0,.45);border-radius:8px;overflow:hidden;}
  .leaflet-control-zoom a{width:38px;height:38px;line-height:38px;font-size:18px;}
  .sm-hit{width:54px;height:54px;display:flex;align-items:center;justify-content:center;cursor:pointer;position:relative;}
  /* --- Phase D: sexy zoom-adaptive markers ------------------------------- */
  .sm-pin{position:relative;width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    box-shadow:0 6px 16px rgba(0,0,0,.55),0 0 0 2px #0B132B;color:#fff;font-weight:900;font-size:16px;line-height:1;
    transition:transform .15s ease, width .15s ease, height .15s ease;}
  .sm-pin .sm-emoji{font-size:18px;line-height:1;filter:drop-shadow(0 1px 2px rgba(0,0,0,.5));}
  .sm-pin.sm-compact{width:24px;height:24px;}
  .sm-pin.sm-compact .sm-emoji{font-size:11px;}
  .sm-pin.sm-compact .sm-galon,.sm-pin.sm-compact .sm-rel{display:none;}
  .sm-pin.sm-marker-focus{transform:scale(1.18);box-shadow:0 0 0 4px rgba(72,202,228,.65),0 0 26px #48CAE4;}
  /* 19/07/2026 — badge « TEST » (mode test bêta) au-dessus du pin. */
  .sm-test-badge{position:absolute;top:-9px;left:50%;transform:translateX(-50%);background:#F4A261;color:#04121F;
    font-size:8px;font-weight:900;letter-spacing:.5px;padding:1px 4px;border-radius:6px;
    border:1px solid rgba(0,0,0,.35);pointer-events:none;white-space:nowrap;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}
  .sm-pin.sm-compact .sm-test-badge{font-size:7px;top:-8px;padding:0 3px;}
  .sm-galon{position:absolute;top:-5px;right:-5px;width:18px;height:18px;border-radius:9px;display:flex;align-items:center;justify-content:center;
    border:2px solid #0B132B;font-size:9px;font-weight:900;color:#0B132B;line-height:1;box-shadow:0 2px 6px rgba(0,0,0,.5);}
  .sm-rel{position:absolute;bottom:-4px;right:-4px;min-width:18px;height:14px;padding:0 4px;border-radius:7px;
    background:#0B132B;color:#fff;font-size:9px;font-weight:900;display:flex;align-items:center;justify-content:center;line-height:1;
    border:1px solid rgba(255,255,255,.4);box-shadow:0 2px 4px rgba(0,0,0,.4);}
  .sm-marker{display:flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:50%;color:#fff;font-weight:900;font-size:14px;box-shadow:0 4px 14px rgba(0,0,0,.4);border:2px solid #0B132B;}
  .sm-marker.sm-marker-focus{box-shadow:0 0 0 4px rgba(72,202,228,.6),0 0 24px #48CAE4;transform:scale(1.18);}
  .sm-user{width:18px;height:18px;border-radius:50%;background:#48CAE4;border:3px solid rgba(72,202,228,.35);box-shadow:0 0 14px #48CAE4;}
  /* Phase I — Boat marker (red arrow) + projection line ahead. */
  .sm-boat-wrap{width:40px;height:40px;display:flex;align-items:center;justify-content:center;position:relative;}
  .sm-boat{width:0;height:0;border-left:11px solid transparent;border-right:11px solid transparent;border-bottom:24px solid #E63946;
    filter:drop-shadow(0 2px 4px rgba(0,0,0,.55));transform-origin:50% 70%;}
  .sm-boat-halo{position:absolute;width:30px;height:30px;border-radius:50%;background:rgba(230,57,70,.18);border:1px solid rgba(230,57,70,.45);
    top:50%;left:50%;transform:translate(-50%,-50%);}
  /* Phase K — Navigation projection cone (yellow). Sits ABOVE tiles but
     BELOW markers (see zIndex on the polygon layer via bringToBack after
     drift-cone rendering). The stroke is dashed to distinguish it from the
     drift cone (which is orange dashed 8,5). */
  .sm-nav-cone{filter:drop-shadow(0 0 8px rgba(244,162,97,.45));}
  /* Phase K.5 — Radar-ping animation (Vigie mode). Two concentric SVG
     circles centred on the boat; radius + opacity are driven by JS in
     requestAnimationFrame (see drawRadarPing) so we can control the exact
     expansion timing and the 1.5–2 s pause between two consecutive waves.
     No CSS keyframes on purpose — CSS cannot animate the SVG radius
     attribute reliably across browsers, and JS lets us keep the two waves
     in lockstep with any live change of the alert radius. */
  /* 20/07/2026 (bug vidéo armateur « scintillement du radar après une
     alerte ») — l'ancienne animation JS (requestAnimationFrame + setRadius
     à chaque frame) sautait des frames dès que le thread du WebView était
     chargé (corne + vibrations répétées, dizaines de marqueurs, retour
     d'écran) → anneaux qui clignotent par à-coups. Remplacée par une
     animation CSS pure (compositeur GPU, insensible au jank JS) : le rayon
     Leaflet est FIXE (= zone de veille) et l'onde est un scale 0→1 + fondu
     de stroke-opacity. 2 anneaux décalés d'un demi-cycle (délai négatif). */
  .sm-radar-ping{fill:none;pointer-events:none;transform-box:fill-box;transform-origin:center;
    animation:smPing 3200ms linear infinite;}
  .sm-radar-ping.sm-radar-b{animation-delay:-1600ms;}
  /* 26/07/2026 — PASTILLE D'INFO type « hauteur d'eau » (réutilisée pour
     « reste X à vue », « Blocage ici », « passage compromis »). */
  .sm-tag{display:inline-flex;align-items:center;gap:6px;background:rgba(13,27,42,.95);
    border:1px solid rgba(72,202,228,.5);border-radius:12px;padding:5px 11px;
    color:#E8ECFB;font:700 12.5px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    white-space:nowrap;box-shadow:0 4px 14px rgba(0,0,0,.45);}
  .sm-tag--danger{border-color:rgba(229,56,59,.7);}
  .sm-tag--warn{border-color:rgba(244,162,97,.7);}
  .sm-tag-drop{font-size:13px;line-height:1;}
  /* 28/07/2026 (retour armateur) — en mode course-up la carte est tournée de
     -bearing ; les pastilles .sm-tag tournaient donc avec elle (texte de
     travers). Ce wrapper CONTRE-tourne autour du point d'ancrage (var
     --sm-counter = +bearing) pour garder le texte TOUJOURS À L'HORIZONTALE.
     No-op en mode nord-en-haut (--sm-counter = 0deg). */
  .sm-tag-anchor{transform:rotate(var(--sm-counter,0deg));transform-origin:0 0;
    transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  /* 02/08/2026 — COMPARAISON A/B DE MOTEURS : étiquette posée sur chaque
     tracé (nom + ID du moteur). Toujours horizontale (.sm-tag-anchor). */
  .sm-eng-tag{transform:translate(-50%,-50%);display:inline-block;
    border-radius:9px;padding:3px 8px;color:#04121F;
    font:800 10.5px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    white-space:nowrap;box-shadow:0 3px 10px rgba(0,0,0,.5);}
  @keyframes smPing{
    0%    {transform:scale(0.02);stroke-opacity:.9;
           animation-timing-function:cubic-bezier(0.215,0.61,0.355,1);}
    46.9% {transform:scale(1);stroke-opacity:0;}
    100%  {transform:scale(1);stroke-opacity:0;}
  }
  /* Phase K — Sober info popup shown on cone tap. Compact 3-row table with
     flare / corridor / angle. */
  .sm-cone-popup .leaflet-popup-content-wrapper{background:rgba(11,19,43,.96);color:#E8ECFB;border:1px solid #F4A261;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.45);padding:2px 4px;}
  .sm-cone-popup .leaflet-popup-content{margin:8px 12px 10px 12px;min-width:170px;}
  .sm-cone-popup .leaflet-popup-tip{background:#F4A261;}
  /* 29/07/2026 — compas de mesure façon Navionics : carte sombre translucide
     centrée sur le trait, toujours horizontale (dans .sm-tag-anchor). */
  .sm-ms-card2{transform:translate(-50%,-50%);display:flex;align-items:center;gap:13px;
    background:rgba(11,19,43,.66);border:1px solid rgba(255,255,255,.20);border-radius:12px;
    padding:7px 14px;box-shadow:0 4px 14px rgba(0,0,0,.35);white-space:nowrap;pointer-events:auto;}
  .sm-ms-col{display:flex;flex-direction:column;align-items:center;}
  .sm-ms-val{color:#fff;font:800 14px system-ui;}
  .sm-ms-cap{color:#C4CDD8;font:600 9px system-ui;letter-spacing:.3px;margin-top:1px;}
  .sm-ms-sep{width:1px;height:26px;background:rgba(255,255,255,.25);}
  /* 31/07/2026 — POPUP CLIC CARTE (mode hauteur d'eau désactivé) façon
     Navionics : carte transparente translucide + coordonnées + hauteur ZH +
     boutons (capture support, fermer). Toujours horizontale à l'écran grâce
     à .sm-tag-anchor (contre-rotation en course-up). */
  .sm-tap-card{transform:translate(-50%,-140%);display:inline-flex;flex-direction:column;
    background:rgba(11,19,43,.85);border:1px solid rgba(72,202,228,.55);border-radius:12px;
    padding:7px 11px 7px 11px;box-shadow:0 6px 18px rgba(0,0,0,.55);white-space:nowrap;
    pointer-events:auto;min-width:150px;}
  .sm-tap-row1{display:flex;align-items:center;gap:8px;}
  .sm-tap-coords{color:#E8ECFB;font:700 12.5px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    letter-spacing:.2px;font-variant-numeric:tabular-nums;}
  .sm-tap-depth{color:#B7E4EE;font:700 12px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    margin-top:2px;font-variant-numeric:tabular-nums;}
  .sm-tap-btns{display:flex;gap:6px;margin-left:auto;}
  .sm-tap-btn{width:26px;height:26px;border-radius:6px;display:inline-flex;
    align-items:center;justify-content:center;cursor:pointer;user-select:none;
    background:rgba(72,202,228,.18);border:1px solid rgba(72,202,228,.45);
    color:#B7E4EE;font-size:14px;line-height:1;transition:background .15s;}
  .sm-tap-btn:hover{background:rgba(72,202,228,.35);}
  .sm-tap-btn--close{background:rgba(255,255,255,.06);border-color:rgba(255,255,255,.2);
    color:#C4CDD8;}
  /* Marqueur central au point du clic (petit disque cyan). */
  .sm-tap-pin{position:absolute;left:-5px;top:-5px;width:10px;height:10px;border-radius:50%;
    background:#0D1B2A;border:2px solid #48CAE4;box-shadow:0 0 6px rgba(72,202,228,.6);}
  /* 29/07/2026 — popup rouge « Eau peu profonde » (tap sur tronçon rouge). */
  .sm-danger-pop .leaflet-popup-content-wrapper{background:rgba(190,18,60,.92);color:#fff;
    border-radius:10px;box-shadow:0 6px 18px rgba(0,0,0,.4);}
  .sm-danger-pop .leaflet-popup-content{margin:8px 14px;font:700 12px system-ui;}
  .sm-danger-pop .leaflet-popup-tip{background:rgba(190,18,60,.92);}
  .sm-danger-tri{transform:translate(-50%,-50%);font-size:17px;line-height:17px;color:#FF1744;
    text-shadow:0 0 3px #fff,0 1px 3px rgba(0,0,0,.5);}
  .sm-cone-popup .leaflet-popup-close-button{display:none;}
  .sm-cone-info .ttl{color:#F4A261;font-weight:900;font-size:10px;letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px;text-align:center;}
  .sm-cone-info .row{display:flex;justify-content:space-between;align-items:baseline;gap:14px;padding:4px 0;border-top:1px solid rgba(232,236,251,.09);}
  .sm-cone-info .row:first-of-type{border-top:none;padding-top:2px;}
  .sm-cone-info .lbl{color:rgba(232,236,251,.72);font-size:11px;font-weight:500;}
  .sm-cone-info .val{color:#FFFFFF;font-weight:800;font-size:12px;font-variant-numeric:tabular-nums;letter-spacing:.2px;}
  /* Bande côtière < 20 km — avertissement « vent seul » dans la popup cône. */
  .sm-cone-warn{display:block;margin-top:6px;padding-top:6px;border-top:1px solid rgba(244,162,97,.4);color:#F4A261;font-size:11px;font-weight:600;line-height:1.35;max-width:230px;white-space:normal;}
  /* Phase K — Markers outside the navigation cone are dimmed to 30% opacity
     so the pilot's eye is naturally drawn to reports inside their travel
     corridor. 0.6 s ease-in-out smooths out jitter when a marker is right
     on the cone boundary (avoids visible flickering at GPS tick rate). */
  .sm-hit.sm-outside-cone{opacity:.3;transition:opacity .6s ease-in-out;}
  .sm-hit{transition:opacity .6s ease-in-out;}
  /* Phase I (v4) — course-up rotation. The map div is rotated via setBearing
     (composed with the centering translate); child icons (.sm-hit, .sm-user,
     .sm-boat-wrap) are counter-rotated via --sm-counter to stay upright. */
  .leaflet-control-container{transform:rotate(var(--sm-counter,0deg));transform-origin:50% 50%;transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-hit,.sm-user,.sm-boat-wrap{transform:rotate(var(--sm-counter,0deg));transform-origin:50% 50%;transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-arrow-tip{display:flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;color:#0B132B;font-weight:900;font-size:10px;line-height:18px;text-align:center;border:2px solid #0B132B;box-shadow:0 2px 8px rgba(0,0,0,.4);}
  .crosshair{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none;z-index:500;}
  .crosshair::before,.crosshair::after{content:"";position:absolute;background:#E63946;}
  .crosshair::before{left:-22px;top:-1px;width:44px;height:2px;}
  .crosshair::after{left:-1px;top:-22px;width:2px;height:44px;}
  .crosshair-dot{width:14px;height:14px;border:2px solid #E63946;border-radius:50%;background:rgba(230,57,70,.18);}
  /* Phase E.6 — "Position dans +/- 1 h" label along the drift-cone arc. */
  .sm-cone-label-wrap{background:transparent !important;border:none !important;box-shadow:none !important;overflow:visible !important;
    transform:rotate(var(--sm-counter,0deg));transform-origin:50% 50%;transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-cone-label{display:inline-block;background:rgba(11,19,43,.88);color:#FFE0B3;font-weight:800;font-size:11px;
    padding:4px 10px;border-radius:12px;border:1.5px solid #FF6F1A;letter-spacing:.3px;line-height:1;
    box-shadow:0 3px 10px rgba(0,0,0,.55);white-space:nowrap;text-shadow:0 1px 2px rgba(0,0,0,.6);
    transform-origin:50% 50%;pointer-events:none;}
  .sm-cone-popup .leaflet-popup-content-wrapper{background:#0B132B;color:#E8F1FF;border:1.5px solid #FF6F1A;border-radius:12px;
    /* 16/07/2026 (retour user) — la carte est CSS-rotée en course-up ;
       le contenu du popup héritait de cette rotation et devenait illisible
       (renversé/oblique). On CONTRE-ROTE le contenu autour de l'ancre bas =
       pointe du popup : la bulle reste toujours à la verticale, la pointe
       reste bien fixée sur le cône. */
    transform:rotate(var(--sm-counter,0deg));
    transform-origin:50% 100%;
    transition:transform .55s cubic-bezier(.2,.7,.2,1);}
  .sm-cone-popup .leaflet-popup-content{margin:10px 12px;font-size:12px;line-height:1.45;}
  .sm-cone-popup .leaflet-popup-tip{background:#0B132B;border:1.5px solid #FF6F1A;}
  .sm-cone-popup .leaflet-popup-close-button{color:#E8F1FF !important;}

  /* ─── Animation « pulse » du cône ROUGE (17/07 v2) ─────────────────────
     Le cône rouge pulse doucement à 1 Hz pour signaler l'urgence sans être
     agressif. La classe sm-nav-cone--red est ajoutée / retirée par
     SM.setConeState() sur l'élément SVG path du cône Leaflet. */
  @keyframes sm-cone-pulse {
    0%,100% { fill-opacity: 0.14; stroke-opacity: 0.95; }
    50%     { fill-opacity: 0.32; stroke-opacity: 1.00; }
  }
  .sm-nav-cone--red { animation: sm-cone-pulse 1s ease-in-out infinite; }
  /* Orange : contour HACHURÉ épais (dashed) — daltonisme rouge/vert (~8 %
     des hommes) : la TEXTURE en dash + épaisseur double sert de 2ᵉ canal
     de communication en plus de la couleur. */
  .sm-nav-cone--orange { }
  /* Vert : contour FIN uni (état par défaut, non-menaçant). */
  .sm-nav-cone--green  { }
  /* Échelle custom (10/07/2026 · 17/07 : règle HORIZONTALE du bas RETIRÉE
     à la demande de l'armateur — seule la barre type Navionics reste en
     bas ; la règle verticale à gauche est conservée telle quelle). Fixée
     au body (espace écran), donc toujours droite même en course-up.
     Métrique OU nautique selon le réglage user (16/07/2026). */
  .sm-ruler{position:fixed;pointer-events:auto;z-index:600;cursor:pointer;}
  #sm-ruler-v{left:8px;top:10%;bottom:10%;width:18px;border-left:1px solid rgba(255,255,255,.55);}
  #sm-ruler-v .tick{position:absolute;left:0;height:1px;width:6px;background:rgba(255,255,255,.55);}
  #sm-ruler-v .lbl{position:absolute;left:8px;transform:translateY(-50%);color:rgba(255,255,255,.85);
    font-size:9.5px;font-weight:700;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    text-shadow:0 1px 3px rgba(0,0,0,.9),0 0 4px rgba(0,0,0,.7);white-space:nowrap;letter-spacing:.2px;}
  /* Barre style Navionics (16/07 · 17/07 : SEULE échelle du bas depuis le
     retrait de la règle horizontale — descendue à 10 px du bord). Longueur
     = fraction d'un couloir virtuel de 80 % du viewport (même métrique
     qu'avant), bord gauche à 10 % du viewport. */
  /* Barre style Navionics (16/07 · 18/07 : LARGE ~80 % de la largeur ·
     18/07 v2 : CENTRÉE horizontalement quelle que soit l'orientation ·
     18/07 v3 : libellé CENTRÉ dans la barre, demande armateur). */
  #sm-ruler-nav{position:fixed;bottom:10px;left:50%;transform:translateX(-50%);z-index:601;pointer-events:auto;cursor:pointer;
    background:rgba(11,19,43,.72);border:1px solid rgba(255,255,255,.55);border-radius:5px;
    padding:2px 0 3px 0;color:#FFFFFF;font-weight:800;font-size:10px;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    letter-spacing:.3px;text-align:center;
    box-shadow:0 2px 6px rgba(0,0,0,.55);}
  #sm-ruler-nav .bar{position:relative;height:8px;margin-top:2px;border-left:1px solid #FFFFFF;border-right:1px solid #FFFFFF;
    border-bottom:1px solid #FFFFFF;}
  /* N1 (20/07/2026) — libellés des isobathes (profondeur en m). Halo blanc
     pour rester lisible sur les fonds OSM/bathy sans encombrer. */
  .sm-iso-label{font:800 10px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    color:#1B4965;text-align:center;pointer-events:none;
    text-shadow:0 0 3px #fff,0 0 3px #fff,0 0 2px #fff;}
  /* 22/07/2026 — POINT DE BLOCAGE de la route (pulsation rouge). */
  @keyframes smBlockPulse{
    0%{transform:scale(0.6);opacity:0.9}
    70%{transform:scale(1.6);opacity:0}
    100%{transform:scale(1.6);opacity:0}
  }
  .sm-blocked{position:relative;width:34px;height:34px;pointer-events:none;}
  .sm-blocked .ring{position:absolute;inset:0;border:3px solid #E5383B;border-radius:50%;
    animation:smBlockPulse 1.4s ease-out infinite;}
  .sm-blocked .core{position:absolute;left:10px;top:10px;width:14px;height:14px;border-radius:50%;
    background:#E5383B;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5);}
  /* 22/07/2026 — numéros des waypoints de la route MANUELLE en création
     (agrandis pour le DRAG & DROP au doigt). */
  .sm-wp-num{display:flex;align-items:center;justify-content:center;width:26px;height:26px;
    border-radius:50%;background:#2EC4B6;color:#0B132B;border:2px solid #fff;
    font:800 13px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    box-shadow:0 1px 3px rgba(0,0,0,.4);}
  /* 23/07/2026 — ALARME DE MOUILLAGE : icône ancre au centre du cercle de
     garde. Clignote en rouge quand le bateau dérive hors du rayon. */
  @keyframes smAnchorBlink{0%,100%{opacity:1}50%{opacity:.35}}
  .sm-anchor{display:flex;align-items:center;justify-content:center;width:28px;height:28px;
    border-radius:50%;background:rgba(11,19,43,.88);border:2px solid #2EC4B6;
    color:#2EC4B6;font-size:15px;line-height:1;box-shadow:0 1px 4px rgba(0,0,0,.5);
    transform:rotate(var(--sm-counter,0deg));}
  .sm-anchor--alarm{border-color:#E5383B;color:#E5383B;animation:smAnchorBlink 0.9s ease-in-out infinite;}
  /* 24/07/2026 — COMPAS DE MESURE : épingles A/B + carte distance/relèvement */
  .sm-ms-pin{position:relative;width:34px;height:34px;pointer-events:none;}
  .sm-ms-ring{position:absolute;inset:5px;border:2.5px solid #FFD166;border-radius:50%;
    background:rgba(11,19,43,.22);box-shadow:0 1px 5px rgba(0,0,0,.45);}
  .sm-ms-dot{position:absolute;left:15px;top:15px;width:4px;height:4px;border-radius:50%;background:#FFD166;}
  .sm-ms-tag{position:absolute;left:50%;top:-11px;transform:translateX(-50%);
    color:#0B132B;font:800 10px system-ui;padding:1px 6px;border-radius:7px;background:#FFD166;
    box-shadow:0 1px 3px rgba(0,0,0,.4);}
  .sm-ms-card{transform:translate(-50%,-135%);white-space:nowrap;background:rgba(11,19,43,.94);
    border:1px solid rgba(255,209,102,.65);border-radius:10px;padding:5px 10px;
    box-shadow:0 3px 10px rgba(0,0,0,.45);text-align:center;pointer-events:auto;cursor:pointer;}
  .sm-ms-dist{color:#FFD166;font:800 15px system-ui;letter-spacing:.3px;}
  .sm-ms-brg2{color:#CFE9F2;font:700 14px system-ui;}
  .sm-ms-brg{color:#CFE9F2;font:600 10px system-ui;margin-top:1px;}
  .sm-ms-magnet{color:#2EC4B6;font:700 9px system-ui;margin-top:2px;}
  /* Accroche en cours de drag : on TOGGLE une classe sur l'élément existant
     (setIcon remplacerait le DOM et tuerait le drag Leaflet). */
  .sm-ms-snap .sm-ms-ring{border-color:#2EC4B6 !important;}
  .sm-ms-snap .sm-ms-dot{background:#2EC4B6 !important;}
  .sm-ms-snap .sm-ms-tag{background:#2EC4B6 !important;}
`;
