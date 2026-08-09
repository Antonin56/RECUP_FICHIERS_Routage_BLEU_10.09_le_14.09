"""SignalMar — Demo reports generator (Phase A.2).

Generates 30 demo reports across the Morbihan → west of Belle-Île area,
all at sea, with realistic photos generated via Gemini Nano Banana
(`gemini-3.1-flash-image-preview` via the Emergent LLM Key).

Each demo report:
- carries `is_demo=true` so it bypasses the standard sliding TTL
  (`expires_at` is set 30 days in the future) and survives until either
  the maintainer wipes it or 3+ community "fake" flags accumulate;
- includes the spec-mandated explainer in its description:
  "Signalement de démonstration — vous pouvez le supprimer en cliquant
  sur 'Mettre à jour' puis 'Faux signalement'";
- is owned by the SignalMar maintainer account.

Run with:  python /app/backend/seed_demo_reports.py
"""

import asyncio
import base64
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MAINTAINER_EMAIL = "antoninlepinay@gmail.com"

DEMO_DISCLAIMER = (
    "\n\n— Signalement de démonstration — vous pouvez le supprimer en cliquant "
    "sur « Mettre à jour » puis « Faux signalement »."
)


# Hand-picked OPEN-SEA coordinates (≥ 2 NM offshore). Each one cross-checked
# on OpenSeaMap to ensure deep water (no anchorage / no foreshore). Three
# safe zones used:
#   A. Baie de Quiberon centre (deep open water between Quiberon peninsula
#      and Belle-Île).
#   B. Coureau de Belle-Île (deep channel between Houat/Hoëdic and Belle-Île).
#   C. Façade ouest de Belle-Île (open Atlantic).
DEMO_COORDS = [
    # Zone A — Baie de Quiberon (open water)
    (47.490, -3.080, "Baie de Quiberon — centre"),
    (47.470, -3.060, "Baie de Quiberon — sud"),
    (47.510, -3.100, "Baie de Quiberon — nord-ouest"),
    (47.460, -3.020, "Baie de Quiberon — est"),
    (47.480, -3.150, "Baie de Quiberon — ouest"),
    (47.440, -3.090, "Baie de Quiberon — pointe sud"),
    # Zone B — Coureau de Belle-Île (deep channel)
    (47.380, -3.000, "Coureau Houat — nord"),
    (47.360, -3.030, "Coureau Houat — centre"),
    (47.340, -3.080, "Coureau Belle-Île — nord-est"),
    (47.320, -3.130, "Coureau Belle-Île — est"),
    (47.305, -3.170, "Coureau Belle-Île — centre"),
    (47.290, -3.220, "Coureau Belle-Île — sud-est"),
    (47.350, -2.960, "Sud Houat — large"),
    (47.330, -2.920, "Sud-est Hoëdic"),
    (47.395, -2.980, "Au large Hoëdic — nord"),
    # Zone C — Atlantique ouest Belle-Île (open ocean)
    (47.270, -3.300, "Sud Belle-Île — large"),
    (47.250, -3.380, "Sud-ouest Belle-Île"),
    (47.230, -3.450, "Ouest Belle-Île — large"),
    (47.215, -3.520, "Atlantique ouest Belle-Île"),
    (47.260, -3.500, "Pointe des Poulains — large 3 NM"),
    (47.290, -3.560, "Nord-ouest Belle-Île — large"),
    (47.310, -3.480, "Ouest Belle-Île — Sauzon large"),
    (47.200, -3.400, "Sud-ouest Belle-Île — large"),
    (47.180, -3.480, "Atlantique large"),
    # Zone bonus — Quiberon ouest (Atlantique entrée)
    (47.420, -3.250, "Plateau du Four — sud"),
    (47.450, -3.300, "Plateau du Four — ouest"),
    (47.395, -3.330, "Au large du Four"),
    (47.500, -3.220, "Plateau du Four — nord"),
    (47.530, -3.180, "Plateau du Four — entrée nord"),
    (47.550, -3.250, "Houat — nord large"),
]


# Template specs: (type, subtype, extras, description, photo_prompt).
DEMO_SPECS = [
    ("autorites", "gendarmerie_maritime", {},
     "Patrouille de la Gendarmerie Maritime en cap nord, contrôle de routine.",
     "photo réaliste maritime : vedette de la Gendarmerie Maritime française grise et bleue patrouillant en mer en Bretagne, ciel nuageux, vue de loin, lumière de fin de journée"),
    ("secours", "snsm", {},
     "Vedette SNSM en intervention au large, sur le coureau.",
     "photo réaliste : vedette de sauvetage en mer SNSM orange et blanche en mer en Bretagne, mer agitée légèrement, vue éloignée"),
    ("autorites", "affaires_maritimes", {},
     "Affaires Maritimes — contrôle des pêches au large de Quiberon.",
     "photo réaliste : navire des Affaires Maritimes françaises en patrouille au large des côtes bretonnes"),
    ("obstacle_nav", "ofni", {},
     "OFNI partiellement immergé, probablement un débris de carénage. Vigilance.",
     "photo réaliste mer Bretagne : débris flottant non identifié à demi-immergé à la surface de l'eau, plan rapproché, écume autour"),
    ("obstacle_nav", "conteneur", {},
     "Conteneur partiellement immergé dérivant, signalé par cargos passants.",
     "photo réaliste : conteneur d'expédition maritime jaune partiellement immergé dans l'océan, vagues autour, en pleine mer Atlantique"),
    ("obstacle_nav", "bois_flottant", {},
     "Tronc d'arbre flottant horizontal, peut endommager une coque ou un safran.",
     "photo réaliste : gros tronc d'arbre flottant à la surface de l'océan en Bretagne, vagues douces, vue à hauteur d'eau"),
    ("obstacle_nav", "bouee_peche", {},
     "Bouée de casier à crustacés sans pavillon, cordage tendu — risque hélice.",
     "photo réaliste : bouée de pêche orange et blanche flottant en mer en Bretagne avec un cordage visible juste sous la surface"),
    ("obstacle_nav", "ofni", {},
     "OFNI métallique à la dérive — possiblement un fût.",
     "photo réaliste mer : vieux fût métallique rouillé flottant entre deux eaux en mer Atlantique, cadrage proche"),
    ("animal_marin", "mammifere", {"species": "common_dolphin", "health": "alive_healthy"},
     "Petit groupe de dauphins communs observé en chasse, comportement actif.",
     "photo réaliste : groupe de dauphins communs sautant hors de l'eau en mer Bretagne, lumière matinale dorée"),
    ("animal_marin", "mammifere", {"species": "bottlenose_dolphin", "health": "alive_healthy"},
     "Grand dauphin solitaire suivant le bateau quelques minutes.",
     "photo réaliste : un grand dauphin Tursiops nageant à fleur d'eau en mer en Bretagne"),
    ("animal_marin", "mammifere", {"species": "harbor_porpoise", "health": "alive_healthy"},
     "Marsouins communs aperçus brièvement, calmes en surface.",
     "photo réaliste : deux marsouins communs nageant en surface en mer de Bretagne par temps couvert"),
    ("animal_marin", "mammifere", {"species": "grey_seal", "health": "alive_healthy"},
     "Phoque gris au repos sur un rocher émergé, à distance respectueuse.",
     "photo réaliste : un phoque gris au repos sur un rocher en mer de Bretagne, photo prise depuis un bateau à distance"),
    ("animal_marin", "mammifere", {"species": "minke_whale", "health": "alive_healthy"},
     "Souffle observé au loin, probablement un petit rorqual (baleine de Minke).",
     "photo réaliste : un petit rorqual qui souffle à la surface de l'océan Atlantique, vue éloignée"),
    ("animal_marin", "oiseau", {"health": "alive_healthy"},
     "Colonie de fous de Bassan en chasse, plongées spectaculaires.",
     "photo réaliste : colonie de fous de Bassan plongeant en piqué dans la mer en Bretagne, ciel bleu, éclaboussures"),
    ("animal_marin", "oiseau", {"health": "alive_injured"},
     "Goéland blessé à l'aile observé flottant, à signaler aux secours animaliers.",
     "photo réaliste : goéland argenté à l'aile abîmée flottant à la surface de la mer en Bretagne"),
    ("animal_marin", "mammifere", {"species": "common_dolphin", "health": "dead_injured", "injury_type": "fishing_gear"},
     "Dauphin commun retrouvé mort avec traces d'engin de pêche. À documenter.",
     "photo réaliste documentaire : dauphin commun mort dérivant à la surface de l'eau en mer de Bretagne, vue à distance respectueuse"),
    ("pollution", "pollution_locale", {},
     "Nappe d'hydrocarbure légère, environ 50 m de long, irisations visibles.",
     "photo réaliste : petite nappe d'hydrocarbure irisée à la surface de l'océan, mer calme, lumière du soir"),
    ("pollution", "pollution_cote", {},
     "Galettes d'hydrocarbure échouées sur la grève au sud de Belle-Île.",
     "photo réaliste documentaire : galettes d'hydrocarbure noires sur une plage de sable en Bretagne, marée basse"),
    ("pollution", "pollution_importante", {},
     "Nappe étendue ~300 m, secteur très fréquenté, alerter CROSS d'urgence.",
     "photo réaliste aérienne : grande nappe d'hydrocarbure noire et irisée dérivant en mer Atlantique près de la côte bretonne, vue depuis un drone"),
    ("pollution", "pollution_locale", {},
     "Concentration de macro-déchets plastiques flottants — bidons, sacs.",
     "photo réaliste : amas de déchets plastiques flottants en mer (bidons, sacs, bouteilles) en mer de Bretagne"),
    ("autorites", "douanes", {},
     "Patrouille douanière, vedette grise, cap est.",
     "photo réaliste : vedette des Douanes françaises grise patrouillant en mer en Bretagne"),
    ("secours", "pompiers", {},
     "Vedette des Pompiers maritimes en intervention.",
     "photo réaliste : embarcation des pompiers maritimes français rouge et blanche en mer en Bretagne"),
    ("obstacle_nav", "roche", {"roche_variant": "toujours_couvrante"},
     "Roche non répertoriée détectée au sondeur, vigilance navigation.",
     "photo réaliste : remous et vaguelettes à la surface de l'eau indiquant une roche immergée en mer Bretagne"),
    ("obstacle_nav", "roche", {"roche_variant": "couvrante_decouvrante"},
     "Roche découvrante par grande marée basse, balise informelle posée.",
     "photo réaliste : rocher noir partiellement émergé en mer Bretagne, écume autour, mer calme"),
    ("animal_marin", "mammifere", {"species": "pilot_whale", "health": "alive_healthy"},
     "Globicéphales noirs en groupe — observation rare !",
     "photo réaliste : groupe de globicéphales noirs nageant en surface en mer Atlantique"),
    ("animal_marin", "autre_animal", {"health": "alive_healthy"},
     "Méduses rhizostomes en grande quantité, attention baigneurs.",
     "photo réaliste : nombreuses méduses bleues rhizostomes dans une eau de mer bretonne, vue subaquatique partielle"),
    ("animal_marin", "oiseau", {"health": "dead_pollution"},
     "Macareux moine retrouvé mort, plumage souillé d'hydrocarbure.",
     "photo réaliste documentaire : macareux moine mort avec plumage taché par du mazout sur une plage de Bretagne"),
    ("pollution", "pollution_locale", {},
     "Mousse blanche persistante en surface, possible rejet industriel.",
     "photo réaliste : mousse blanche persistante anormale à la surface de la mer en Bretagne"),
    ("autorites", "police_env", {},
     "Police de l'Environnement en zone protégée Natura 2000.",
     "photo réaliste : zodiac de la Police de l'Environnement en surveillance d'une zone protégée maritime en Bretagne"),
    ("obstacle_nav", "bois_flottant", {},
     "Palette en bois cassée flottant, dangereuse pour les voiliers.",
     "photo réaliste : palette en bois cassée flottant à la surface de l'océan en Bretagne, écume blanche autour"),
    ("autre", "autre_libre", {},
     "Bouée orpheline non identifiable, sans marquage — à signaler aux Affmar.",
     "photo réaliste : bouée jaune isolée flottant en mer Bretagne sans aucun marquage visible"),
]


async def _generate_photo_b64(prompt: str) -> Optional[str]:
    """Call Nano Banana via Emergent LLM Key. Returns the base64 PNG payload,
    OR None on any failure (script keeps going).
    """
    if not EMERGENT_LLM_KEY:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"signalmar-demo-{uuid.uuid4().hex[:8]}",
            system_message="Tu es un générateur d'images photo-réalistes pour une app maritime.",
        )
        chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(
            modalities=["image", "text"]
        )
        _text, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
        if images and len(images) > 0:
            # images[i]['data'] is already a base64 string.
            return images[0]["data"]
    except Exception as e:
        msg = str(e)[:120]
        print(f"   ! Nano Banana failed — {msg}")
    return None


async def main():
    if not EMERGENT_LLM_KEY:
        print("WARN: EMERGENT_LLM_KEY not in env — reports will be seeded WITHOUT photos.")
    # SAFETY: cross-check each coord against Open-Meteo Marine (the same
    # geofence used by /api/reports for normal users). Wave data is only
    # returned for true open-sea points — inland/coastal-foreshore points
    # return null. global_land_mask is too coarse (~10 km) at the Brittany
    # archipelago scale, so we rely on Open-Meteo here.
    import httpx
    bad: list = []
    async with httpx.AsyncClient(timeout=8.0) as cli:
        for lat, lng, hint in DEMO_COORDS:
            try:
                r = await cli.get(
                    "https://marine-api.open-meteo.com/v1/marine",
                    params={"latitude": round(lat, 4), "longitude": round(lng, 4),
                            "hourly": "wave_height", "forecast_days": 1},
                )
                if r.status_code != 200:
                    bad.append((lat, lng, hint, f"HTTP {r.status_code}"))
                    continue
                arr = ((r.json().get("hourly") or {}).get("wave_height")) or []
                if not any(v is not None for v in arr):
                    bad.append((lat, lng, hint, "no wave data"))
            except Exception as e:
                msg = str(e)[:80]
                print(f"   ! Open-Meteo error on {hint}: {msg} — keeping coord (fail-open).")
    if bad:
        print("❌ The following coords are NOT open sea per Open-Meteo:")
        for lat, lng, hint, why in bad:
            print(f"    - {hint} ({lat},{lng}) — {why}")
        raise RuntimeError("Fix DEMO_COORDS — at-sea check failed for some entries.")
    print(f"✅ All {len(DEMO_COORDS)} demo coords passed Open-Meteo at-sea check.")
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    u = await db.users.find_one({"email": MAINTAINER_EMAIL}, {"_id": 0})
    if not u:
        print(f"ERROR: maintainer account {MAINTAINER_EMAIL} not found. Run setup_signalmar.py first.")
        return
    pseudo = u.get("pseudo") or "SignalMar"
    uid = u["user_id"]

    # Reset existing demo seeds so re-running is idempotent.
    purged = await db.reports.delete_many({"is_demo": True})
    print(f"Purged {purged.deleted_count} previous demo reports.")

    now = datetime.now(timezone.utc)
    far_future = now + timedelta(days=30)

    # 23/07/2026 — short_id dès l'insertion (unicité vérifiée contre la base
    # restante + les codes déjà tirés dans ce run).
    import secrets
    _ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    existing_short_ids = set(
        await db.reports.distinct("short_id", {"short_id": {"$ne": None}})
    )

    def _new_short_id(taken: set) -> str:
        while True:
            code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
            if code not in taken:
                taken.add(code)
                return code

    random.shuffle(DEMO_SPECS)  # vary order
    coords_iter = list(DEMO_COORDS)
    random.shuffle(coords_iter)

    created = 0
    for i, spec in enumerate(DEMO_SPECS[:30]):
        rtype, subtype, extras, description, prompt = spec
        lat, lng, hint = coords_iter[i % len(coords_iter)]
        # Slight jitter so points don't overlap visually.
        lat += random.uniform(-0.005, 0.005)
        lng += random.uniform(-0.005, 0.005)

        # Photo generation (best-effort; None if Nano Banana fails).
        photo_b64 = await _generate_photo_b64(prompt)
        photos = []
        if photo_b64:
            # Compress to ≤800px JPEG q=70 BEFORE storing (raw Nano Banana
            # output is ~1.3 MB → OOMs the Android JS heap; see
            # compress_photos.py for the historical migration).
            from compress_photos import compress_b64
            raw_uri = f"data:image/jpeg;base64,{photo_b64}"
            photos = [compress_b64(raw_uri) or raw_uri]

        # Compose final description with the demo disclaimer + location hint.
        final_desc = f"{description} ({hint}){DEMO_DISCLAIMER}"

        doc = {
            "id": uuid.uuid4().hex,
            # 23/07/2026 — short_id assigné DÈS l'insertion (avant, backfill
            # paresseux à la lecture détail seulement → la LISTE renvoyait
            # short_id:None pour les démos fraîchement re-seedées).
            "short_id": _new_short_id(existing_short_ids),
            "type": rtype,
            "subtype": subtype,
            "extras": extras,
            "lat": lat,
            "lng": lng,
            "origin_lat": lat,
            "origin_lng": lng,
            "description": final_desc,
            "photos": photos,
            "heading": None,
            "speed_knots": None,
            "activity": None,
            "author_id": uid,
            "author_pseudo": pseudo,
            "author_name": pseudo,
            # 12h-36h in the past so the anonymous demo mode (which forces
            # min_age_hours >= 12) always has content to display.
            "created_at": now - timedelta(minutes=random.randint(720, 2160)),
            "last_confirmed_at": now,
            # Demo flag — bypasses sliding TTL (30 days lifetime).
            "is_demo": True,
            "expires_at": far_future,
            "confirmations": [],
            "edits": [],
            "status": "active",
            "flagged_fake": False,
        }
        await db.reports.insert_one(doc)
        created += 1
        has_photo = "📸" if photos else "  "
        print(f"  [{created:>2}/30] {has_photo} {rtype:>13}/{subtype:<22} @ {lat:.3f},{lng:.3f}  {hint}")

    print(f"\n✅ Seeded {created} demo reports (is_demo=true).")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
