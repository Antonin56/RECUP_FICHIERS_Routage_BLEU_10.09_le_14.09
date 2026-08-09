// SignalMar — fragment du JS embarqué de la carte Leaflet.
// Découpé de leaflet-html.ts le 06/06/2026 (refactor N1) : déplacement PUR,
// aucun changement fonctionnel. Le HTML final est reconstitué par buildHtml.
// Évènements carte, détection d'interaction, pont web, ready.

export const JS_EVENTS = `  map.on('moveend', function(){
    var c = map.getCenter();
    postMsg({event:'move', lat:c.lat, lng:c.lng, zoom: map.getZoom()});
  });
  // Phase J — détection d'INTERACTION utilisateur (pan / zoom à la main).
  // Ces évènements ne sont déclenchés QUE par les gestes humains, jamais par
  // map.setView() programmatique → c'est un détecteur fiable de "main
  // levée". Le chrono de 5 s du recentrage automatique repart à la FIN du
  // geste (dragend/zoomend) — pas au début — pour laisser consulter la carte.
  map.on('dragstart', function(){
    window.SM.userDragging = true;
    window.SM.lastUserPan = Date.now();
  });
  map.on('dragend', function(){
    window.SM.userDragging = false;
    window.SM.lastUserPan = Date.now();
  });
  map.on('zoomstart', function(){
    // Le zoom déclenché par les boutons +/- en bas-gauche est aussi un acte
    // volontaire → on le compte comme une interaction.
    if (!window.SM.programmaticMove) window.SM.lastUserPan = Date.now();
  });
  map.on('zoomend', function(){
    if (!window.SM.programmaticMove) window.SM.lastUserPan = Date.now();
  });
  // 13/07/2026 — TOUT contact tactile sur la carte (tap sur un marqueur
  // inclus) repousse le recentrage automatique de 5 s. Sans ça, le chrono
  // pouvait expirer PENDANT que le doigt visait un marqueur : la carte se
  // recentrait sous le doigt → mauvais signalement ouvert / « éjection ».
  (function(){
    var mc = document.getElementById('map');
    ['touchstart','mousedown','wheel'].forEach(function(evt){
      mc.addEventListener(evt, function(){
        window.SM.lastUserPan = Date.now();
      }, {passive:true, capture:true});
    });
  })();
  // Web bridge: listen to parent postMessage so SM.* calls execute on the iframe.
  window.addEventListener('message', function(e){
    var raw = e.data;
    if (typeof raw !== 'string') return;
    try {
      var d = JSON.parse(raw);
      if (d && d.__sm_eval) { (0,eval)(d.__sm_eval); }
    } catch(_){}
  });
  // ready
  setTimeout(function(){ postMsg({event:'ready'}); }, 200);
`;
