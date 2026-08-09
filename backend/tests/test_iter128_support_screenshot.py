"""ITER128 — Validation de la chaîne support (captures d'écran + diagnostics).

Périmètre du review_request (31/07 → 03/08 2026) :
 1. POST /api/support/screenshot :
    - 200 + id S-YYYYMMDD-HHMMSS-XXX pour l'admin (0760071445)
    - 403 pour un compte NON admin
    - 401/403 sans token
    - Persistance du document (image_b64, lat/lng, depth_zh_m, route_id,
      context complet avec engine/route/boat).
    - 413 si image > 4 Mo.
 2. GET /api/support/screenshots (list, admin only, no image_b64)
 3. GET /api/support/screenshot/{id} (doc complet)
 4. GET /api/support/screenshot/{id}/image (image/jpeg décodée)
 5. POST /api/diagnostics : 201 + id, persistance ; auth optionnelle.
 6. Non-régression : GET /api/diagnostics/ping, upload chunké /support/upload/*
"""
from __future__ import annotations

import base64
import os
import re
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

# Ensure backend on PYTHONPATH so `import server` works from make_jwt fallback.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
ADMIN_PHONE = "0760071445"
NONADMIN_PHONE = "0699887766"
OTP = "123456"

# 1×1 pixel JPEG (base64) — ~130 bytes decoded (well under 4 MB limit).
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkI"
    "CQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQ"
    "EBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEB"
    "AAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AL+AH//Z"
)


@pytest.fixture(scope="module")
def base_url() -> str:
    assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be configured"
    return BASE_URL


def _login_otp(base_url: str, phone: str, pseudo: str | None = None) -> dict:
    """Return {token,user} via OTP mock (SMS code always 123456)."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    # request OTP
    r = s.post(f"{base_url}/api/auth/otp/request", json={"phone": phone})
    assert r.status_code in (200, 429), f"otp/request: {r.status_code} {r.text}"
    payload = {"phone": phone, "code": OTP}
    if pseudo:
        payload["pseudo"] = pseudo
    r = s.post(f"{base_url}/api/auth/otp/verify", json=payload)
    assert r.status_code == 200, f"otp/verify {phone}: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data and "user" in data
    return data


@pytest.fixture(scope="module")
def admin_token(base_url) -> str:
    data = _login_otp(base_url, ADMIN_PHONE)
    return data["token"]


@pytest.fixture(scope="module")
def nonadmin_token(base_url) -> str:
    # This account may already exist (see /app/memory/test_credentials.md).
    try:
        data = _login_otp(base_url, NONADMIN_PHONE)
    except AssertionError:
        # Create it with a random pseudo if it doesn't exist yet.
        data = _login_otp(base_url, NONADMIN_PHONE, pseudo=f"QA{uuid.uuid4().hex[:6]}")
    return data["token"]


# ─── 1) POST /api/support/screenshot ─────────────────────────────────────────
class TestSupportScreenshotUpload:
    def test_admin_upload_ok_and_id_format(self, base_url, admin_token):
        payload = {
            "image_b64": TINY_JPEG_B64,
            "lat": 47.658,
            "lng": -2.760,
            "depth_zh_m": 3.4,
            "comment": "TEST_iter128 automated",
            "route_id": "R-TEST-iter128",
            "context": {
                "engine": {"id": "engine_b", "label": "Moteur B"},
                "route": {"route_id": "R-TEST-iter128", "distance_m": 1234.0},
                "boat": {"draft_m": 1.2, "depth_margin_m": 0.5},
                "map": {"zoom": 13, "mode": "auto"},
            },
        }
        r = requests.post(
            f"{base_url}/api/support/screenshot",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        j = r.json()
        assert j.get("ok") is True
        sid = j.get("id", "")
        assert re.match(r"^S-\d{8}-\d{6}-[A-Z0-9]{3}$", sid), f"bad id format: {sid}"
        # Save for downstream tests
        pytest.iter128_sid = sid

    def test_admin_upload_persistence_via_get(self, base_url, admin_token):
        sid = getattr(pytest, "iter128_sid", None)
        assert sid, "no sid available (upload test must succeed first)"
        r = requests.get(
            f"{base_url}/api/support/screenshot/{sid}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["id"] == sid
        assert doc.get("image_b64", "").startswith(TINY_JPEG_B64[:20])
        assert doc.get("lat") == 47.658
        assert doc.get("lng") == -2.760
        assert doc.get("depth_zh_m") == 3.4
        assert doc.get("route_id") == "R-TEST-iter128"
        ctx = doc.get("context") or {}
        assert ctx.get("engine", {}).get("id") == "engine_b"
        assert ctx.get("route", {}).get("route_id") == "R-TEST-iter128"
        assert ctx.get("boat", {}).get("draft_m") == 1.2

    def test_upload_without_token_forbidden(self, base_url):
        r = requests.post(
            f"{base_url}/api/support/screenshot",
            json={"image_b64": TINY_JPEG_B64},
        )
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text}"

    def test_upload_as_nonadmin_forbidden(self, base_url, nonadmin_token):
        r = requests.post(
            f"{base_url}/api/support/screenshot",
            json={"image_b64": TINY_JPEG_B64, "lat": 0.0, "lng": 0.0},
            headers={"Authorization": f"Bearer {nonadmin_token}"},
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    def test_upload_over_4mb_rejected(self, base_url, admin_token):
        # Base64 payload > 4 MB decoded (~4.5 MB decoded).
        big_raw = b"X" * (4 * 1024 * 1024 + 200_000)
        big_b64 = base64.b64encode(big_raw).decode("ascii")
        r = requests.post(
            f"{base_url}/api/support/screenshot",
            json={"image_b64": big_b64, "lat": 0.0, "lng": 0.0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 413, f"expected 413 got {r.status_code}: {r.text[:200]}"


# ─── 2) GET /api/support/screenshots (list) ──────────────────────────────────
class TestSupportScreenshotList:
    def test_list_admin(self, base_url, admin_token):
        r = requests.get(
            f"{base_url}/api/support/screenshots?limit=5",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("screenshots"), list)
        assert j.get("count") == len(j["screenshots"])
        for doc in j["screenshots"]:
            # image_b64 must be stripped from list responses
            assert "image_b64" not in doc, "image_b64 should NOT be in list response"
            assert "_id" not in doc, "raw Mongo _id must never leak"

    def test_list_nonadmin_forbidden(self, base_url, nonadmin_token):
        r = requests.get(
            f"{base_url}/api/support/screenshots",
            headers={"Authorization": f"Bearer {nonadmin_token}"},
        )
        assert r.status_code == 403


# ─── 3) GET /api/support/screenshot/{id} & /image ────────────────────────────
class TestSupportScreenshotFetch:
    def test_fetch_doc_nonadmin_forbidden(self, base_url, nonadmin_token):
        sid = getattr(pytest, "iter128_sid", None)
        assert sid
        r = requests.get(
            f"{base_url}/api/support/screenshot/{sid}",
            headers={"Authorization": f"Bearer {nonadmin_token}"},
        )
        assert r.status_code == 403

    def test_fetch_image_admin_returns_jpeg(self, base_url, admin_token):
        sid = getattr(pytest, "iter128_sid", None)
        assert sid
        r = requests.get(
            f"{base_url}/api/support/screenshot/{sid}/image",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert ct.startswith("image/"), f"content-type={ct}"
        # First bytes of a JPEG are FF D8 FF
        assert r.content[:3] == b"\xff\xd8\xff", f"not a JPEG: {r.content[:10]!r}"

    def test_fetch_image_nonadmin_forbidden(self, base_url, nonadmin_token):
        sid = getattr(pytest, "iter128_sid", None)
        assert sid
        r = requests.get(
            f"{base_url}/api/support/screenshot/{sid}/image",
            headers={"Authorization": f"Bearer {nonadmin_token}"},
        )
        assert r.status_code == 403


# ─── 4) POST /api/diagnostics ─────────────────────────────────────────────────
class TestDiagnosticsPost:
    def test_diagnostics_public_no_token(self, base_url):
        r = requests.post(
            f"{base_url}/api/diagnostics",
            json={
                "logs_text": "TEST_iter128 sans token\nline2",
                "snapshot": {"net": "ok", "gps": "ok"},
                "user_email": "anon@test",
            },
        )
        assert r.status_code == 201, f"{r.status_code} {r.text}"
        j = r.json()
        assert j.get("ok") is True
        assert isinstance(j.get("id"), str) and len(j["id"]) >= 16

    def test_diagnostics_with_admin_token(self, base_url, admin_token):
        r = requests.post(
            f"{base_url}/api/diagnostics",
            json={
                "logs_text": "TEST_iter128 avec token admin",
                "snapshot": {"net": "ok"},
                "user_id": "admin-iter128",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 201, r.text
        assert r.json().get("ok") is True


# ─── 5) Non-régression ────────────────────────────────────────────────────────
class TestNonRegression:
    def test_diagnostics_ping(self, base_url):
        r = requests.get(f"{base_url}/api/diagnostics/ping")
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_support_upload_chunked_full_flow(self, base_url, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        # init
        r = requests.post(
            f"{base_url}/api/support/upload/init",
            json={"filename": "TEST_iter128.bin", "mime": "application/octet-stream", "total_chunks": 2},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        upload_id = r.json()["upload_id"]

        # 2 small chunks
        data = base64.b64encode(b"hello-").decode()
        for i in range(2):
            rc = requests.post(
                f"{base_url}/api/support/upload/chunk",
                json={"upload_id": upload_id, "index": i, "data_b64": data},
                headers=headers,
            )
            assert rc.status_code == 200, rc.text

        # complete
        rf = requests.post(
            f"{base_url}/api/support/upload/complete",
            json={"upload_id": upload_id, "note": "TEST_iter128"},
            headers=headers,
        )
        assert rf.status_code == 200, rf.text
        assert rf.json().get("ok") is True
        assert rf.json().get("size", 0) > 0

    def test_support_upload_init_requires_auth(self, base_url):
        r = requests.post(
            f"{base_url}/api/support/upload/init",
            json={"filename": "x.bin", "mime": "application/octet-stream", "total_chunks": 1},
        )
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"
