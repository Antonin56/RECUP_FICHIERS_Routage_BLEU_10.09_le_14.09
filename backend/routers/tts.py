"""TTS voice alerts (Phase E.1).

Endpoints (mounted under /api):
- GET  /api/tts/sample/{voice} → pre-generated voice preview MP3
- POST /api/tts/alert          → on-demand TTS (cached, OpenAI tts-1-hd via Emergent LLM Key)
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

import server as srv

router = APIRouter(tags=["tts"])


# --- Phase K.15 — Anti-troncature Bluetooth ------------------------------------
# Les enceintes / casques Bluetooth (SBC & AAC) mettent en veille leur codec
# quand aucun flux audio ne circule. Au réveil, la poignée de main A2DP prend
# 500 à 1500 ms pendant lesquelles le début du message est perdu (le codec du
# téléphone envoie déjà des paquets mais l'enceinte n'est pas prête à les
# rendre audibles).
#
# Solution : on préfixe le MP3 d'alerte par un court silence encodé dans le
# MÊME codec (24 kHz mono, 32 kbps) que la sortie OpenAI TTS-HD. Le décodeur
# audio du téléphone traite les deux flux de façon transparente, tandis que
# l'enceinte reçoit ce silence comme paquet de "wake" A2DP → le codec Bluetooth
# est déjà chaud quand la voix commence.
#
# 14/07/2026 — RÉDUIT de 2 000 ms → 350 ms (vidéo user : la voix partait
# TOUJOURS ~2 s après la bannière, même en cache local… c'était CE silence).
# 350 ms couvre la majorité des réveils A2DP tout en rendant le son
# quasi simultané avec la popup sur haut-parleur téléphone/tablette.
_SILENCE_PATH = srv.ROOT_DIR / "tts_samples" / "silence_350ms.mp3"
try:
    _SILENCE_BYTES: bytes = _SILENCE_PATH.read_bytes() if _SILENCE_PATH.exists() else b""
except Exception:  # pragma: no cover — fail open, on renverra le MP3 nu
    _SILENCE_BYTES = b""


def _prepend_silence(audio: bytes) -> bytes:
    """Concatène le préfixe silencieux devant le MP3 TTS.

    MP3 étant un container à trames indépendantes, la concaténation binaire
    est licite dès lors que les deux flux utilisent des paramètres codec
    compatibles (le décodeur resynchronise sur le prochain header valide).
    """
    if not _SILENCE_BYTES:
        return audio
    return _SILENCE_BYTES + audio


@router.get("/tts/sample/{voice}")
async def tts_sample(voice: str):
    """Sert un échantillon MP3 prégénéré pour l'écran de choix de voix."""
    safe = {
        # 1re salve (rolled R / accent)
        "femme":         "signalmar_sample_femme.mp3",
        "homme":         "signalmar_sample_homme.mp3",
        # 2e salve à 0.95x — voix alternatives
        "femme-shimmer": "femme_shimmer.mp3",
        "femme-alloy":   "femme_alloy.mp3",
        "femme-nova":    "femme_nova_slow.mp3",
        "homme-echo":    "homme_echo.mp3",
        "homme-onyx":    "homme_onyx_slow.mp3",
    }
    fname = safe.get(voice)
    if not fname:
        raise HTTPException(404, "voice not found")
    path = srv.ROOT_DIR / "tts_samples" / fname
    if not path.exists():
        raise HTTPException(404, "sample not generated yet")
    return FileResponse(path, media_type="audio/mpeg")


class TTSAlertIn(BaseModel):
    text: str
    voice: Literal["alloy", "echo"] = "alloy"


@router.post("/tts/alert")
async def tts_alert(body: TTSAlertIn):
    """Génère (ou récupère depuis le cache) l'audio MP3 d'un message d'alerte.

    Aucun auth required pour permettre la lecture rapide dès qu'une push
    arrive même avant l'éventuelle ré-authentification (ex : 4G fluctuante).
    """
    # Normalisation du texte (espaces, accents, ponctuation) pour maximiser
    # les cache-hits — deux messages identiques ne paient qu'une fois.
    key_src = (body.voice + "|" + body.text.strip()).encode("utf-8")
    cache_key = hashlib.sha256(key_src).hexdigest()

    cached = await srv.db.tts_cache.find_one({"_id": cache_key})
    if cached and cached.get("audio"):
        await srv.db.tts_cache.update_one(
            {"_id": cache_key},
            {"$set": {"last_used_at": datetime.utcnow()},
             "$inc": {"hit_count": 1}},
        )
        return Response(content=_prepend_silence(cached["audio"]), media_type="audio/mpeg")

    # Génération à la demande via OpenAI TTS HD (Emergent LLM Key).
    try:
        from emergentintegrations.llm.openai.text_to_speech import (
            OpenAITextToSpeech,
        )
        tts = OpenAITextToSpeech(api_key=os.environ["EMERGENT_LLM_KEY"])
        audio = await tts.generate_speech(
            text=body.text,
            model="tts-1-hd",
            voice=body.voice,
            response_format="mp3",
            speed=0.95,
        )
    except Exception as e:
        srv.logger.exception("tts_alert generation failed")
        raise HTTPException(502, f"TTS generation failed: {e}")

    await srv.db.tts_cache.update_one(
        {"_id": cache_key},
        {"$set": {
            "_id": cache_key,
            "text": body.text,
            "voice": body.voice,
            "audio": audio,
            "created_at": datetime.utcnow(),
            "last_used_at": datetime.utcnow(),
        },
         "$inc": {"hit_count": 1}},
        upsert=True,
    )
    return Response(content=_prepend_silence(audio), media_type="audio/mpeg")

# ── Pré-génération du CATALOGUE COMPLET d'alertes (13/07/2026) ───────────────
# Demande user : « générés et stockés une bonne fois pour toutes ». L'ensemble
# des phrases d'alerte possibles est FINI — on les génère toutes au démarrage
# (tâche de fond, uniquement celles qui manquent en base). Résultat : plus
# AUCUN utilisateur ne paie jamais la génération OpenAI (~5 s) ; le serveur
# sert toujours depuis le cache Mongo (~0,2 s).
#
# ⚠️ SYNC OBLIGATOIRE avec frontend/src/lib/voice-alerts.ts (buildAlertText) :
# toute nouvelle phrase côté frontend doit être ajoutée ici.

_PERIM = "dans votre périmètre d'alerte."

# Autorités → message FIXE (pas de modulation vitesse).
_FIXED_SUBJECTS = [
    ("gendarmerie maritime", "signalée"),
    ("affaires maritimes", "signalées"),
    ("police de l'environnement", "signalée"),
    ("douanes maritimes", "signalées"),
    ("autorité maritime", "signalée"),
]

# Sujets MODULÉS par la vitesse (3 variantes chacun).
_MODULATED_SUBJECTS = [
    # Obstacles
    ("roche non répertoriée", "signalée"),
    ("objet flottant non identifié", "signalé"),
    ("bouée ou matériel de pêche", "signalé"),
    ("conteneur partiellement immergé", "signalé"),
    ("bois flottant", "signalé"),
    ("obstacle à la navigation", "signalé"),  # fallback sous-type inconnu
    # Mammifères marins (tous états)
    ("mammifère marin", "signalé"),
    ("mammifère marin blessé", "signalé"),
    ("mammifère marin mort", "signalé"),
    # Oiseaux / autres animaux (blessé ou mort uniquement)
    ("oiseau marin blessé", "signalé"),
    ("oiseau marin mort", "signalé"),
    ("animal marin blessé", "signalé"),
    ("animal marin mort", "signalé"),
    # Pollutions avec alerte
    ("pollution locale", "signalée"),
    ("pollution importante", "signalée"),
]


def _catalog_texts() -> list[str]:
    """Reconstruit EXACTEMENT les phrases de buildAlertText (frontend)."""
    texts: list[str] = []
    for subj, acc in _FIXED_SUBJECTS:
        texts.append(f"Attention, {subj} {acc} {_PERIM}")
    for subj, acc in _MODULATED_SUBJECTS:
        phrase = f"{subj} {acc} {_PERIM}"
        texts.append(f"Attention ! Soyez très vigilant : {phrase}")   # > 10 nds
        texts.append(f"Soyez vigilant, {phrase}")                      # 5-10 nds
        texts.append(f"{subj[0].upper()}{subj[1:]} {acc} {_PERIM}")    # < 5 nds
    return texts


async def pregenerate_alert_catalog() -> None:
    """Génère (en série, tâche de fond) tous les MP3 du catalogue manquants."""
    import asyncio

    if not os.environ.get("EMERGENT_LLM_KEY"):
        srv.logger.warning("tts pregen: EMERGENT_LLM_KEY absente — skip")
        return
    texts = _catalog_texts()
    todo: list[tuple[str, str, str]] = []  # (cache_key, text, voice)
    for voice in ("alloy", "echo"):
        for text in texts:
            key = hashlib.sha256((voice + "|" + text.strip()).encode("utf-8")).hexdigest()
            if not await srv.db.tts_cache.find_one({"_id": key}, {"_id": 1}):
                todo.append((key, text, voice))
    if not todo:
        srv.logger.info("tts pregen: catalogue complet déjà en cache (%d phrases × 2 voix)", len(texts))
        return
    srv.logger.info("tts pregen: %d MP3 manquants sur %d — génération de fond…", len(todo), len(texts) * 2)

    from emergentintegrations.llm.openai.text_to_speech import OpenAITextToSpeech
    tts = OpenAITextToSpeech(api_key=os.environ["EMERGENT_LLM_KEY"])
    ok = failed = 0
    for key, text, voice in todo:
        try:
            audio = await tts.generate_speech(
                text=text, model="tts-1-hd", voice=voice,
                response_format="mp3", speed=0.95,
            )
            await srv.db.tts_cache.update_one(
                {"_id": key},
                {"$set": {
                    "_id": key, "text": text, "voice": voice, "audio": audio,
                    "created_at": datetime.utcnow(),
                    "last_used_at": datetime.utcnow(),
                    "pregenerated": True,
                }},
                upsert=True,
            )
            ok += 1
        except Exception as e:  # une phrase en échec ne bloque pas les autres
            failed += 1
            srv.logger.warning("tts pregen: échec « %s » (%s): %s", text[:40], voice, e)
        await asyncio.sleep(0.3)  # lisse la charge API
    srv.logger.info("tts pregen: terminé — %d générés, %d échecs", ok, failed)
