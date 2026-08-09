import { useEffect, useRef, useState } from "react";
import { Platform, StyleSheet, View } from "react-native";
import WebView from "react-native-webview";

/**
 * SignalMar — mini-map preview used inside the "share signalement" screenshot.
 *
 * Renders a Leaflet WebView at a tight zoom around the report, with:
 *  - the OSM tile layer (cohérent visuel avec la carte principale)
 *  - le marqueur du signalement
 *  - le cône de dérive (si fourni)
 *
 * The component fires `onReady` once Leaflet finishes painting so the parent
 * screen knows it's safe to capture the screenshot.
 */
export interface ReportSharePreviewProps {
  lat: number;
  lng: number;
  color: string;
  emoji?: string;
  driftPolygon?: { lat: number; lng: number }[] | null;
  height?: number;
  onReady?: () => void;
}

export function ReportSharePreview({
  lat, lng, color, emoji = "•",
  driftPolygon, height = 200, onReady,
}: ReportSharePreviewProps) {
  const ref = useRef<WebView>(null);
  const [loaded, setLoaded] = useState(false);

  // Inject the report into the WebView once it has loaded.
  useEffect(() => {
    if (!loaded) return;
    const payload = {
      lat, lng, color, emoji,
      polygon: driftPolygon || null,
    };
    const js = `window.SM && SM.setReport(${JSON.stringify(payload)}); true;`;
    ref.current?.injectJavaScript(js);
  }, [loaded, lat, lng, color, emoji, driftPolygon]);

  const html = `<!doctype html><html><head>
  <meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html,body,#m{margin:0;padding:0;height:100%;width:100%;background:#0B132B;}
    .leaflet-tile{filter:brightness(.85) contrast(1.05) saturate(.92);}
    .leaflet-control-attribution{display:none !important;}
    .sm-pin{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;
      box-shadow:0 6px 16px rgba(0,0,0,.55),0 0 0 2px #0B132B;color:#fff;font-weight:900;font-size:16px;}
    .sm-pin .em{font-size:18px;line-height:1;filter:drop-shadow(0 1px 2px rgba(0,0,0,.5));}
    .sm-watermark{position:absolute;bottom:6px;right:8px;font:600 10px/1.1 -apple-system,system-ui,Roboto,sans-serif;color:#fff;opacity:.85;
      background:rgba(11,19,43,.6);padding:3px 7px;border-radius:6px;z-index:1000;letter-spacing:.4px;}
  </style></head><body>
  <div id="m"></div>
  <div class="sm-watermark">SignalMar</div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    var map = L.map('m',{zoomControl:false,attributionControl:false,dragging:false,touchZoom:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,keyboard:false}).setView([${lat}, ${lng}], 13);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18}).addTo(map);
    L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png',{maxZoom:18,opacity:0.85}).addTo(map);
    window.SM = {
      setReport: function(r){
        var pin = '<div class="sm-pin" style="background:'+r.color+'"><span class="em">'+(r.emoji||'•')+'</span></div>';
        L.marker([r.lat,r.lng],{icon:L.divIcon({className:'',html:pin,iconSize:[40,40],iconAnchor:[20,20]})}).addTo(map);
        if (r.polygon && r.polygon.length >= 3){
          var pts = r.polygon.map(function(p){ return [p.lat, p.lng]; });
          var poly = L.polygon(pts,{color:'#FF6F1A',weight:3,opacity:1,dashArray:'8,5',fillColor:'#FFA94D',fillOpacity:0.4}).addTo(map);
          try { map.fitBounds(poly.getBounds().pad(0.35), {animate:false}); } catch(_){}
        }
        setTimeout(function(){
          try { window.ReactNativeWebView && window.ReactNativeWebView.postMessage('ready'); } catch(_){}
        }, 600);
      }
    };
    setTimeout(function(){
      try { window.ReactNativeWebView && window.ReactNativeWebView.postMessage('loaded'); } catch(_){}
    }, 50);
  </script>
  </body></html>`;

  return (
    <View style={[styles.wrap, { height }]} pointerEvents="none">
      <WebView
        ref={ref}
        source={{ html, baseUrl: Platform.OS === "android" ? "https://localhost/" : undefined }}
        style={styles.web}
        originWhitelist={["*"]}
        scalesPageToFit={false}
        scrollEnabled={false}
        bounces={false}
        javaScriptEnabled
        domStorageEnabled
        androidLayerType="hardware"
        onMessage={(e) => {
          if (e.nativeEvent.data === "loaded") {
            setLoaded(true);
          } else if (e.nativeEvent.data === "ready") {
            onReady?.();
          }
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { width: "100%", borderRadius: 14, overflow: "hidden", backgroundColor: "#0B132B" },
  web: { flex: 1, backgroundColor: "#0B132B" },
});
