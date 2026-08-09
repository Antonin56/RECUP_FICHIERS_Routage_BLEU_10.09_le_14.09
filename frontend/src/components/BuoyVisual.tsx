// SignalMar — Visuels SVG des bouées maritimes (Région IALA A).
//
// Reprend fidèlement la planche officielle :
//   • Cardinales N/E/S/W : voyants en cônes (▲▲, ▲▼, ▼▼, ▼▲), bandes
//     jaune/noir disposées selon la position des cônes.
//   • Latérales bâbord (cylindre rouge) / tribord (cône vert).
//   • Bâbord & Tribord préférés (bandes inversées).
//   • Danger isolé : noir + bande rouge, deux boules noires au sommet.
//   • Eaux saines : bandes rouges/blanches verticales, une boule rouge au sommet.
//   • Marque spéciale : jaune, voyant en X.
//
// Le composant est entièrement responsive grâce à viewBox.

import Svg, {
  Circle,
  G,
  Path,
  Rect,
} from "react-native-svg";

import type { BuoyDef } from "@/src/lib/safety-data";

const W = 60;     // largeur viewBox
const H = 110;    // hauteur viewBox

// Niveau du sol (la base de la bouée)
const GROUND = 96;
// Hauteur d'une bande de bouée (cylindre)
const BODY_TOP = 38;
const BODY_BOTTOM = GROUND;
const BODY_LEFT = 22;
const BODY_RIGHT = 38;
const BODY_WIDTH = BODY_RIGHT - BODY_LEFT;

const COLOR = {
  black: "#0F141A",
  yellow: "#FFD22E",
  red:   "#D62828",
  green: "#2A9D8F",
  white: "#F4F6F8",
  topmarkStroke: "#0F141A",
};

type Props = {
  buoy: BuoyDef;
  size?: number;
};

export function BuoyVisual({ buoy, size = 64 }: Props) {
  // Dimensions du SVG en fonction de la taille demandée.
  const height = size * (H / W);

  return (
    <Svg width={size} height={height} viewBox={`0 0 ${W} ${H}`}>
      {/* Ligne de mer */}
      <Path d={`M0 ${GROUND + 2} H${W}`} stroke="#3B5C7A" strokeWidth={0.8} />
      {renderBody(buoy)}
      {renderTopmark(buoy)}
    </Svg>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Corps de la bouée (bandes horizontales ou verticales)
// ───────────────────────────────────────────────────────────────────────
function renderBody(buoy: BuoyDef): React.ReactNode {
  switch (buoy.id) {
    case "card_n": // Noir au-dessus, jaune en dessous
      return <BicolorH topColor={COLOR.black} botColor={COLOR.yellow} />;
    case "card_s": // Jaune au-dessus, noir en dessous
      return <BicolorH topColor={COLOR.yellow} botColor={COLOR.black} />;
    case "card_e": // Noir, jaune, noir (jaune au milieu)
      return <TricolorH colors={[COLOR.black, COLOR.yellow, COLOR.black]} />;
    case "card_w": // Jaune, noir, jaune (noir au milieu)
      return <TricolorH colors={[COLOR.yellow, COLOR.black, COLOR.yellow]} />;
    case "isolated":
      // Noir + bande rouge centrale + noir
      return <TricolorH colors={[COLOR.black, COLOR.red, COLOR.black]} />;
    case "safe_water":
      // Bandes verticales rouges/blanches alternées
      return <VerticalStripes colors={[COLOR.red, COLOR.white, COLOR.red, COLOR.white]} />;
    case "lat_p":
      // Bâbord — cylindre rouge plein (forme can)
      return <SolidCylinder color={COLOR.red} />;
    case "lat_s":
      // Tribord — cône vert plein (sera dessiné comme un cône en surcouche)
      return <SolidCone color={COLOR.green} />;
    case "lat_pref_p":
      // Bâbord préféré : rouge avec bande verte centrale
      return <TricolorH colors={[COLOR.red, COLOR.green, COLOR.red]} />;
    case "lat_pref_s":
      // Tribord préféré : vert avec bande rouge centrale
      return <TricolorH colors={[COLOR.green, COLOR.red, COLOR.green]} />;
    case "special":
      // Spéciale — jaune plein
      return <SolidCylinder color={COLOR.yellow} />;
    case "emerg":
      // Bandes verticales bleues/jaunes (danger nouveau)
      return <VerticalStripes colors={["#0A66C2", COLOR.yellow, "#0A66C2", COLOR.yellow]} />;
    default:
      return <SolidCylinder color={COLOR.yellow} />;
  }
}

// ───────────────────────────────────────────────────────────────────────
// Voyant (topmark) — au-dessus du corps
// ───────────────────────────────────────────────────────────────────────
function renderTopmark(buoy: BuoyDef): React.ReactNode {
  const cx = (BODY_LEFT + BODY_RIGHT) / 2;
  switch (buoy.id) {
    case "card_n":
      // Deux cônes pointe en haut (▲▲), empilés
      return <ConePair cx={cx} bottomY={BODY_TOP - 1} dir="up" />;
    case "card_s":
      // Deux cônes pointe en bas (▼▼), empilés
      return <ConePair cx={cx} bottomY={BODY_TOP - 1} dir="down" />;
    case "card_e":
      // Cônes opposés base-à-base (▲ haut puis ▼ bas) — losange ouvert
      return <ConePair cx={cx} bottomY={BODY_TOP - 1} dir="east" />;
    case "card_w":
      // Cônes pointe-à-pointe — sablier
      return <ConePair cx={cx} bottomY={BODY_TOP - 1} dir="west" />;
    case "isolated":
      // Deux boules noires verticales
      return (
        <G>
          <Circle cx={cx} cy={BODY_TOP - 14} r={3.2} fill={COLOR.black} stroke={COLOR.topmarkStroke} strokeWidth={0.5} />
          <Circle cx={cx} cy={BODY_TOP - 6}  r={3.2} fill={COLOR.black} stroke={COLOR.topmarkStroke} strokeWidth={0.5} />
          {/* Mât */}
          <Rect x={cx - 0.6} y={BODY_TOP - 2} width={1.2} height={4} fill={COLOR.black} />
        </G>
      );
    case "safe_water":
      // Une boule rouge au sommet
      return (
        <G>
          <Circle cx={cx} cy={BODY_TOP - 6} r={3.6} fill={COLOR.red} stroke={COLOR.topmarkStroke} strokeWidth={0.5} />
          <Rect x={cx - 0.6} y={BODY_TOP - 2.4} width={1.2} height={4.4} fill={COLOR.red} />
        </G>
      );
    case "lat_p":
    case "lat_pref_p":
      // Voyant cylindre rouge (peu utilisé sur les latérales — souvent absent)
      return (
        <G>
          <Rect x={cx - 3} y={BODY_TOP - 7} width={6} height={5} fill={COLOR.red} stroke={COLOR.topmarkStroke} strokeWidth={0.5} />
          <Rect x={cx - 0.6} y={BODY_TOP - 2} width={1.2} height={4} fill={COLOR.red} />
        </G>
      );
    case "lat_s":
    case "lat_pref_s":
      // Voyant cône vert
      return (
        <G>
          <Path
            d={`M ${cx - 3.5} ${BODY_TOP - 2} L ${cx} ${BODY_TOP - 8} L ${cx + 3.5} ${BODY_TOP - 2} Z`}
            fill={COLOR.green}
            stroke={COLOR.topmarkStroke}
            strokeWidth={0.5}
          />
        </G>
      );
    case "special":
      // Voyant en X jaune
      return (
        <G stroke={COLOR.yellow} strokeWidth={1.6} strokeLinecap="round">
          <Path d={`M ${cx - 3.5} ${BODY_TOP - 8} L ${cx + 3.5} ${BODY_TOP - 2}`} />
          <Path d={`M ${cx + 3.5} ${BODY_TOP - 8} L ${cx - 3.5} ${BODY_TOP - 2}`} />
          <Rect x={cx - 0.6} y={BODY_TOP - 2} width={1.2} height={4} fill={COLOR.yellow} />
        </G>
      );
    default:
      return null;
  }
}

// ───────────────────────────────────────────────────────────────────────
// Helpers — formes de base
// ───────────────────────────────────────────────────────────────────────
function BicolorH({ topColor, botColor }: { topColor: string; botColor: string }) {
  const mid = (BODY_TOP + BODY_BOTTOM) / 2;
  return (
    <G stroke={COLOR.topmarkStroke} strokeWidth={0.6}>
      <Rect x={BODY_LEFT} y={BODY_TOP} width={BODY_WIDTH} height={mid - BODY_TOP} fill={topColor} />
      <Rect x={BODY_LEFT} y={mid}      width={BODY_WIDTH} height={BODY_BOTTOM - mid} fill={botColor} />
    </G>
  );
}

function TricolorH({ colors }: { colors: [string, string, string] }) {
  const total = BODY_BOTTOM - BODY_TOP;
  // Bandes : 35 % / 30 % / 35 %
  const h1 = total * 0.35;
  const h2 = total * 0.30;
  const h3 = total - h1 - h2;
  return (
    <G stroke={COLOR.topmarkStroke} strokeWidth={0.6}>
      <Rect x={BODY_LEFT} y={BODY_TOP}              width={BODY_WIDTH} height={h1} fill={colors[0]} />
      <Rect x={BODY_LEFT} y={BODY_TOP + h1}         width={BODY_WIDTH} height={h2} fill={colors[1]} />
      <Rect x={BODY_LEFT} y={BODY_TOP + h1 + h2}    width={BODY_WIDTH} height={h3} fill={colors[2]} />
    </G>
  );
}

function VerticalStripes({ colors }: { colors: string[] }) {
  const stripeW = BODY_WIDTH / colors.length;
  return (
    <G stroke={COLOR.topmarkStroke} strokeWidth={0.6}>
      {colors.map((c, i) => (
        <Rect
          key={i}
          x={BODY_LEFT + i * stripeW}
          y={BODY_TOP}
          width={stripeW}
          height={BODY_BOTTOM - BODY_TOP}
          fill={c}
        />
      ))}
    </G>
  );
}

function SolidCylinder({ color }: { color: string }) {
  return (
    <Rect
      x={BODY_LEFT}
      y={BODY_TOP}
      width={BODY_WIDTH}
      height={BODY_BOTTOM - BODY_TOP}
      fill={color}
      stroke={COLOR.topmarkStroke}
      strokeWidth={0.6}
    />
  );
}

function SolidCone({ color }: { color: string }) {
  // Forme conique : haut étroit, base large
  const apex = BODY_TOP;
  const baseY = BODY_BOTTOM;
  const cx = (BODY_LEFT + BODY_RIGHT) / 2;
  const baseLeft = BODY_LEFT - 1;
  const baseRight = BODY_RIGHT + 1;
  return (
    <Path
      d={`M ${cx} ${apex} L ${baseRight} ${baseY} L ${baseLeft} ${baseY} Z`}
      fill={color}
      stroke={COLOR.topmarkStroke}
      strokeWidth={0.6}
    />
  );
}

type Dir = "up" | "down" | "east" | "west";
function ConePair({ cx, bottomY, dir }: { cx: number; bottomY: number; dir: Dir }) {
  // Chaque cône a base de 7, hauteur 6. Les deux cônes empilés, séparés d'1 px.
  const baseHW = 3.5;
  const coneH = 6;
  const gap = 0.6;

  // Mât (sous la base du voyant)
  const mast = <Rect x={cx - 0.6} y={bottomY} width={1.2} height={4} fill={COLOR.black} />;

  function coneAt(yBase: number, pointUp: boolean) {
    if (pointUp) {
      // pointe en haut
      const apex = yBase - coneH;
      return (
        <Path
          d={`M ${cx} ${apex} L ${cx + baseHW} ${yBase} L ${cx - baseHW} ${yBase} Z`}
          fill={COLOR.black}
          stroke={COLOR.topmarkStroke}
          strokeWidth={0.5}
        />
      );
    }
    // pointe en bas
    const apex = yBase + coneH;
    return (
      <Path
        d={`M ${cx} ${apex} L ${cx + baseHW} ${yBase} L ${cx - baseHW} ${yBase} Z`}
        fill={COLOR.black}
        stroke={COLOR.topmarkStroke}
        strokeWidth={0.5}
      />
    );
  }

  switch (dir) {
    case "up": {
      // ▲▲ : deux cônes pointe en haut, empilés
      const bottomCone = coneAt(bottomY, true);                 // bas = bottomY, pointe vers haut
      const topCone    = coneAt(bottomY - coneH - gap, true);   // au-dessus
      return <G>{mast}{bottomCone}{topCone}</G>;
    }
    case "down": {
      // ▼▼ : deux cônes pointe en bas
      const topCone    = coneAt(bottomY - coneH * 2 - gap, false);
      const bottomCone = coneAt(bottomY - coneH, false);
      return <G>{mast}{topCone}{bottomCone}</G>;
    }
    case "east": {
      // ▲ au dessus ▼ — bases jointes (losange ouvert)
      const topCone    = coneAt(bottomY - coneH, true);   // pointe haut
      const bottomCone = coneAt(bottomY - coneH, false);  // pointe bas
      return <G>{mast}{topCone}{bottomCone}</G>;
    }
    case "west": {
      // ▼ au dessus ▲ — pointes jointes (sablier)
      const topCone    = coneAt(bottomY - coneH * 2 + gap, false); // base haut, pointe bas
      const bottomCone = coneAt(bottomY, true);                     // base bas, pointe haut
      return <G>{mast}{topCone}{bottomCone}</G>;
    }
  }
}
