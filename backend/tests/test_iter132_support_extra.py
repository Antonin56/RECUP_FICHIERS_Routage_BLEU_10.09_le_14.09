"""SignalMar — Itér. 132 (jan/2026) : couverture COMPLÉMENTAIRE des 3 canaux
support demandée par l'armateur.

Non couvert par iter131 :
- multiple tailles (60 Ko = 1 chunk / 250 Ko / 1,5 Mo)
- 413 pour image > 4 Mo
- 403 pour non-admin sur /commit et /inbox
- durabilité : redémarrage du backend au milieu d'un envoi chunké
- non-régression du POST /screenshot single-shot avec data URL
- GET /support/screenshots (liste admin) reste opérationnel
"""
from __future__ import annotations

import base64
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
ADMIN_PHONE = "0760071445"
STD_PHONE = "0699887766"
OTP_CODE = "123456"
CHUNK_B64 = (96 * 1024 // 3) * 4


def _login(phone: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text[:200]
    r = s.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": phone, "code": OTP_CODE,
              "pseudo": f"QAiter132_{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, r.text[:200]
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


@pytest.fixture(scope="module")
def admin() -> requests.Session:
    return _login(ADMIN_PHONE)


@pytest.fixture(scope="module")
def std_user() -> requests.Session:
    return _login(STD_PHONE)


def _fake_jpeg(kbytes: int) -> bytes:
    return b"\xff\xd8\xff\xe0" + os.urandom(kbytes * 1024)


def _init_upload(session: requests.Session, total_chunks: int) -> str:
    r = session.post(
        f"{BASE_URL}/api/support/upload/init",
        json={"filename": "c.jpg", "mime": "image/jpeg",
              "total_chunks": total_chunks},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:200]
    return r.json()["upload_id"]


def _send_chunks(session, upload_id, parts, start=0):
    for i in range(start, len(parts)):
        rr = session.post(
            f"{BASE_URL}/api/support/upload/chunk",
            json={"upload_id": upload_id, "index": i, "data_b64": parts[i]},
            timeout=30,
        )
        assert rr.status_code == 200, f"chunk {i}: {rr.status_code} {rr.text[:200]}"


def _split(raw: bytes) -> list[str]:
    b64 = base64.b64encode(raw).decode("ascii")
    return [b64[i:i + CHUNK_B64] for i in range(0, len(b64), CHUNK_B64)]


# ── Multi-tailles ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("kbytes", [60, 250, 1500])
def test_chunked_various_sizes_roundtrip(admin, kbytes):
    raw = _fake_jpeg(kbytes)
    parts = _split(raw)
    if kbytes == 60:
        # 60 Ko binaire → ~80 Ko base64 → 1 seul morceau
        assert len(parts) == 1, f"60 Ko doit tenir en 1 chunk, got {len(parts)}"
    else:
        assert len(parts) >= 2, f"{kbytes} Ko doit être découpé"
    upload_id = _init_upload(admin, len(parts))
    _send_chunks(admin, upload_id, parts)
    r = admin.post(
        f"{BASE_URL}/api/support/screenshot/commit",
        json={"upload_id": upload_id, "mime": "image/jpeg",
              "lat": 47.5, "lng": -2.8,
              "context": {"probe": f"iter132-{kbytes}"}},
        timeout=90,
    )
    assert r.status_code == 200, r.text[:300]
    sid = r.json()["id"]
    assert r.json()["size"] == len(raw)
    img = admin.get(f"{BASE_URL}/api/support/screenshot/{sid}/image", timeout=60)
    assert img.status_code == 200
    assert img.content == raw, f"octets identiques attendus pour {kbytes} Ko"


# ── Taille max : > 4 Mo → 413 ─────────────────────────────────────────────
def test_over_size_limit_returns_413(admin):
    # 4200 Ko de données → 5 Mo base64. On envoie les chunks, le 413 tombera
    # au commit (contrôle de la taille reconstituée).
    raw = _fake_jpeg(4200)
    parts = _split(raw)
    upload_id = _init_upload(admin, len(parts))
    _send_chunks(admin, upload_id, parts)
    r = admin.post(
        f"{BASE_URL}/api/support/screenshot/commit",
        json={"upload_id": upload_id, "mime": "image/jpeg"},
        timeout=90,
    )
    assert r.status_code == 413, f"413 attendu, got {r.status_code} : {r.text[:200]}"


# ── 403 pour non-admin ────────────────────────────────────────────────────
def test_non_admin_forbidden_on_commit(std_user):
    r = std_user.post(
        f"{BASE_URL}/api/support/screenshot/commit",
        json={"upload_id": "0" * 32, "mime": "image/jpeg"},
        timeout=30,
    )
    assert r.status_code == 403, f"403 attendu, got {r.status_code}"


def test_non_admin_forbidden_on_inbox(std_user):
    r = std_user.get(f"{BASE_URL}/api/support/inbox", timeout=30)
    assert r.status_code == 403


def test_non_admin_forbidden_on_screenshot_post(std_user):
    r = std_user.post(
        f"{BASE_URL}/api/support/screenshot",
        json={"image_b64": None, "lat": 47.5, "lng": -2.8, "context": {"x": 1}},
        timeout=30,
    )
    assert r.status_code == 403


def test_non_admin_forbidden_on_screenshots_list(std_user):
    r = std_user.get(f"{BASE_URL}/api/support/screenshots", timeout=30)
    assert r.status_code == 403


# ── Non-régression : POST single-shot data URL ────────────────────────────
def test_single_shot_data_url_still_works(admin):
    raw = _fake_jpeg(30)
    data_url = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    r = admin.post(
        f"{BASE_URL}/api/support/screenshot",
        json={"image_b64": data_url, "lat": 47.60, "lng": -2.85,
              "comment": "single-shot iter132"},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:200]
    sid = r.json()["id"]
    img = admin.get(f"{BASE_URL}/api/support/screenshot/{sid}/image", timeout=30)
    assert img.status_code == 200
    assert img.content == raw


def test_admin_list_screenshots_still_operational(admin):
    r = admin.get(f"{BASE_URL}/api/support/screenshots?limit=5", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "screenshots" in body and "count" in body
    assert isinstance(body["screenshots"], list)


# ── Durabilité : redémarrage du backend AU MILIEU de l'envoi ──────────────
def test_upload_survives_backend_restart(admin):
    """L'itér. 131 rend les sessions persistantes en base. On envoie le
    morceau 0, on redémarre le backend, puis on envoie le reste + commit."""
    raw = _fake_jpeg(250)
    parts = _split(raw)
    assert len(parts) >= 3
    upload_id = _init_upload(admin, len(parts))
    _send_chunks(admin, upload_id, parts, start=0)  # send all
    # Correction : on veut envoyer partiel, restart, puis reste
    # Reprends le pattern demandé :
    upload_id = _init_upload(admin, len(parts))
    # morceau 0 uniquement
    rr = admin.post(
        f"{BASE_URL}/api/support/upload/chunk",
        json={"upload_id": upload_id, "index": 0, "data_b64": parts[0]},
        timeout=30,
    )
    assert rr.status_code == 200

    # restart backend
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=True)
    # attendre que backend redémarre
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/api/diagnostics/ping", timeout=5)
            if r.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        pytest.fail("backend n'a pas redémarré")

    # envoyer le reste des morceaux et commit
    for i in range(1, len(parts)):
        rr = admin.post(
            f"{BASE_URL}/api/support/upload/chunk",
            json={"upload_id": upload_id, "index": i, "data_b64": parts[i]},
            timeout=30,
        )
        assert rr.status_code == 200, f"post-restart chunk {i}: {rr.status_code} {rr.text[:200]}"

    r = admin.post(
        f"{BASE_URL}/api/support/screenshot/commit",
        json={"upload_id": upload_id, "mime": "image/jpeg",
              "lat": 47.5827118, "lng": -2.7951316,
              "context": {"probe": "iter132-restart"}},
        timeout=60,
    )
    assert r.status_code == 200, r.text[:300]
    sid = r.json()["id"]
    assert r.json()["size"] == len(raw)
    img = admin.get(f"{BASE_URL}/api/support/screenshot/{sid}/image", timeout=60)
    assert img.status_code == 200
    assert img.content == raw, "image identique à l'octet après restart"
