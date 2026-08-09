"""Iteration 64 — regression on support upload chunked endpoints.

Endpoints tested:
- POST /api/support/upload/init      (auth required, 401 without)
- POST /api/support/upload/chunk     (accepts base64 chunks)
- POST /api/support/upload/complete  (assembles + persists in Mongo)
- Missing chunk in complete → 422
"""
import base64
import os
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
PHONE = "0760071445"
OTP = "123456"


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text}"
    r = s.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": PHONE, "code": OTP})
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok
    return tok


def test_init_requires_auth():
    r = requests.post(
        f"{BASE_URL}/api/support/upload/init",
        json={"filename": "x.mp4", "mime": "video/mp4", "total_chunks": 1},
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text}"


def test_full_upload_happy_path(token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    # 3 chunks of ~10 bytes each — enough to exercise the assembly loop.
    parts = [b"HELLO_PART", b"SECOND_ONE", b"THIRD_LAST"]
    r = s.post(
        f"{BASE_URL}/api/support/upload/init",
        json={"filename": "test-capture.mp4", "mime": "video/mp4", "total_chunks": len(parts)},
    )
    assert r.status_code == 200, r.text
    upload_id = r.json()["upload_id"]
    assert isinstance(upload_id, str) and len(upload_id) >= 16

    for i, chunk in enumerate(parts):
        r = s.post(
            f"{BASE_URL}/api/support/upload/chunk",
            json={
                "upload_id": upload_id,
                "index": i,
                "data_b64": base64.b64encode(chunk).decode(),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["received"] == i + 1
        assert body["total"] == len(parts)

    r = s.post(f"{BASE_URL}/api/support/upload/complete", json={"upload_id": upload_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["size"] == sum(len(p) for p in parts)
    assert body["filename"].endswith(".mp4")


def test_complete_missing_chunk_returns_422(token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    r = s.post(
        f"{BASE_URL}/api/support/upload/init",
        json={"filename": "partial.bin", "mime": "application/octet-stream", "total_chunks": 3},
    )
    assert r.status_code == 200
    upload_id = r.json()["upload_id"]
    # Send only chunk 0 and chunk 2 — chunk 1 missing.
    for i in (0, 2):
        r = s.post(
            f"{BASE_URL}/api/support/upload/chunk",
            json={"upload_id": upload_id, "index": i, "data_b64": base64.b64encode(b"x").decode()},
        )
        assert r.status_code == 200
    r = s.post(f"{BASE_URL}/api/support/upload/complete", json={"upload_id": upload_id})
    assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
    assert "manquants" in r.text or "chunks" in r.text.lower()


def test_bad_total_chunks_rejected(token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    r = s.post(
        f"{BASE_URL}/api/support/upload/init",
        json={"filename": "x.bin", "mime": "application/octet-stream", "total_chunks": 0},
    )
    assert r.status_code == 422
