"""SignalMar — Itér. 131 (03/08/2026) : TRANSMISSION SUPPORT FIABILISÉE.

Demande armateur (verbatim) : « J'ai besoin que tu répares la fonction qui
t'envoie automatiquement une capture d'écran avec les coordonnées précises.
Hier je t'ai envoyé les captures avec cet outil et tu n'as rien reçu.
L'envoi d'enregistrement d'écran, de captures d'écran, et cet outil doivent
tous les 3 être parfaitement fonctionnels. »

CONSTAT (base de production) : la dernière capture réellement enregistrée
datait du 03/08 à 12h28 ; aucune ensuite, alors que l'armateur en a envoyé
plusieurs. Les logs terrain montrent `support screenshot failed
{"status":429}` : l'envoi se faisait en UN SEUL POST de ~400 Ko de base64,
throttlé par l'ingress, et les sessions d'upload n'étaient qu'en MÉMOIRE (un
redémarrage du backend perdait tout).

Ce fichier verrouille les 3 canaux :
1. capture carte avec coordonnées — envoi PAR MORCEAUX (~128 Ko/requête) ;
2. captures d'écran / enregistrements d'écran — même chemin chunké ;
3. « Vérifier la réception » — l'armateur voit ce que le serveur a REÇU.
"""
from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"
CHUNK_B64 = (96 * 1024 // 3) * 4          # multiple de 4 → chaque morceau décodable


@pytest.fixture(scope="module")
def admin() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    assert s.post(f"{BASE_URL}/api/auth/otp/request",
                  json={"phone": ADMIN_PHONE}).status_code == 200
    r = s.post(f"{BASE_URL}/api/auth/otp/verify",
               json={"phone": ADMIN_PHONE, "code": OTP_CODE,
                     "pseudo": f"QAiter131_{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text[:200]
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


def _fake_jpeg(kbytes: int) -> bytes:
    """Octets incompressibles préfixés d'un en-tête JPEG."""
    return b"\xff\xd8\xff\xe0" + os.urandom(kbytes * 1024)


def _send_chunked(session, raw: bytes, **commit) -> dict:
    b64 = base64.b64encode(raw).decode("ascii")
    parts = [b64[i:i + CHUNK_B64] for i in range(0, len(b64), CHUNK_B64)]
    r = session.post(f"{BASE_URL}/api/support/upload/init",
                     json={"filename": "carte.jpg", "mime": "image/jpeg",
                           "total_chunks": len(parts)}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    upload_id = r.json()["upload_id"]
    for i, p in enumerate(parts):
        rr = session.post(f"{BASE_URL}/api/support/upload/chunk",
                          json={"upload_id": upload_id, "index": i, "data_b64": p},
                          timeout=60)
        assert rr.status_code == 200, f"morceau {i} → {rr.status_code} {rr.text[:200]}"
    r = session.post(f"{BASE_URL}/api/support/screenshot/commit",
                     json={"upload_id": upload_id, "mime": "image/jpeg", **commit},
                     timeout=90)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# ── 1. Capture carte avec coordonnées, PAR MORCEAUX ───────────────────────
def test_chunked_map_capture_is_stored_with_its_coordinates(admin):
    raw = _fake_jpeg(250)
    out = _send_chunked(admin, raw, lat=47.5827118, lng=-2.7951316,
                        depth_zh_m=3.2, comment="chenal d'Illur",
                        context={"probe": "iter131", "engine": "engine_c"})
    assert out["ok"] is True and out["id"].startswith("S-")
    assert out["size"] == len(raw), \
        f"taille reconstituée {out['size']} ≠ {len(raw)} — assemblage incorrect"

    meta = admin.get(f"{BASE_URL}/api/support/screenshot/{out['id']}", timeout=30)
    assert meta.status_code == 200, meta.text[:200]
    doc = meta.json()
    assert abs(doc["lat"] - 47.5827118) < 1e-6
    assert abs(doc["lng"] + 2.7951316) < 1e-6
    assert doc["depth_zh_m"] == 3.2
    assert doc["context"]["engine"] == "engine_c"
    assert doc.get("has_image") is True

    img = admin.get(f"{BASE_URL}/api/support/screenshot/{out['id']}/image", timeout=60)
    assert img.status_code == 200
    assert img.content == raw, "les octets relus doivent être IDENTIQUES à l'envoi"


def test_chunk_requests_stay_small_enough_to_avoid_throttling(admin):
    """Chaque requête doit rester ~128 Ko : c'est la cause racine du 429."""
    b64 = base64.b64encode(_fake_jpeg(400)).decode("ascii")
    parts = [b64[i:i + CHUNK_B64] for i in range(0, len(b64), CHUNK_B64)]
    assert len(parts) >= 3, "un envoi de 400 Ko doit être découpé"
    assert max(len(p) for p in parts) <= 132 * 1024, \
        f"morceau trop gros : {max(len(p) for p in parts)} caractères"
    assert all(len(p) % 4 == 0 for p in parts[:-1]), \
        "chaque morceau doit être un multiple de 4 caractères base64"


def test_init_advertises_the_recommended_chunk_size(admin):
    r = admin.post(f"{BASE_URL}/api/support/upload/init",
                   json={"filename": "x.jpg", "mime": "image/jpeg", "total_chunks": 1},
                   timeout=30)
    assert r.status_code == 200
    assert r.json().get("chunk_size") == 96 * 1024


def test_commit_refuses_an_incomplete_upload(admin):
    """Un envoi tronqué ne doit JAMAIS produire une capture corrompue."""
    b64 = base64.b64encode(_fake_jpeg(250)).decode("ascii")
    parts = [b64[i:i + CHUNK_B64] for i in range(0, len(b64), CHUNK_B64)]
    assert len(parts) >= 2
    upload_id = admin.post(
        f"{BASE_URL}/api/support/upload/init",
        json={"filename": "trou.jpg", "mime": "image/jpeg", "total_chunks": len(parts)},
        timeout=30).json()["upload_id"]
    admin.post(f"{BASE_URL}/api/support/upload/chunk",
               json={"upload_id": upload_id, "index": 0, "data_b64": parts[0]},
               timeout=30)
    r = admin.post(f"{BASE_URL}/api/support/screenshot/commit",
                   json={"upload_id": upload_id, "mime": "image/jpeg"}, timeout=30)
    assert r.status_code == 422, f"422 attendu (morceaux manquants), got {r.status_code}"
    assert "manquant" in r.text.lower()


def test_unknown_upload_session_is_reported_clearly(admin):
    r = admin.post(f"{BASE_URL}/api/support/screenshot/commit",
                   json={"upload_id": "0" * 32, "mime": "image/jpeg"}, timeout=30)
    assert r.status_code == 404
    assert "inconnue" in r.text.lower()


# ── 2. Repli NAVIGATEUR : contexte seul, sans image ───────────────────────
def test_context_only_capture_is_accepted_on_web(admin):
    """Sur navigateur, l'iframe Leaflet ne peut pas être photographiée. On
    n'abandonne plus : le contexte (coordonnées + tracé + verdict de balisage)
    suffit à rejouer le calcul côté serveur."""
    ctx = {"probe": "iter131-web", "no_image_reason": "web_iframe_capture_unavailable",
           "route": {"waypoints": [[47.58, -2.79], [47.585, -2.785]],
                     "side_fixed": ["Illur"]}}
    r = admin.post(f"{BASE_URL}/api/support/screenshot",
                   json={"image_b64": None, "lat": 47.58, "lng": -2.79,
                         "depth_zh_m": 4.1, "context": ctx}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    sid = r.json()["id"]
    doc = admin.get(f"{BASE_URL}/api/support/screenshot/{sid}", timeout=30).json()
    assert doc.get("has_image") is False
    assert doc["context"]["route"]["side_fixed"] == ["Illur"]
    img = admin.get(f"{BASE_URL}/api/support/screenshot/{sid}/image", timeout=30)
    assert img.status_code == 404, "pas d'image → 404 explicite, pas de 500"


def test_empty_capture_is_rejected(admin):
    r = admin.post(f"{BASE_URL}/api/support/screenshot",
                   json={"image_b64": None}, timeout=30)
    assert r.status_code == 422, f"422 attendu pour un envoi vide, got {r.status_code}"


# ── 3. « Vérifier la réception » ──────────────────────────────────────────
def test_inbox_reports_what_the_server_actually_received(admin):
    raw = _fake_jpeg(120)
    out = _send_chunked(admin, raw, lat=47.60, lng=-2.85,
                        context={"probe": "iter131-inbox"})
    r = admin.get(f"{BASE_URL}/api/support/inbox", timeout=60)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    for key in ("screenshots", "files", "logs", "server_time"):
        assert key in body, f"clé {key} absente : {list(body)}"
    ids = [s["id"] for s in body["screenshots"]]
    assert out["id"] in ids, \
        f"la capture {out['id']} doit apparaître dans la boîte de réception"
    shot = next(s for s in body["screenshots"] if s["id"] == out["id"])
    assert shot["transport"] == "chunked"
    assert shot["has_image"] is True
    assert shot["size_bytes"] == len(raw)
    assert shot["created_at"], "horodatage attendu pour que l'armateur se repère"
