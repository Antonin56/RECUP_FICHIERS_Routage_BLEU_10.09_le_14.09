"""Iter 69 — TTS /api/tts/alert latency + regression.

Verifies:
  1. POST /api/tts/alert with a NOVEL short text (generation path): status 200,
     content-type audio/mpeg, non-empty body, wall time is measured.
  2. Second call with same text (cache hit): status 200, non-empty, wall time
     should be well under 1.5 s.
  3. GET /api/tts/sample/femme-alloy still serves an MP3 (regression for the
     "Écouter" voice sample button in profile settings).
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/") if os.environ.get("EXPO_BACKEND_URL") else \
    "https://signalmar-optimize.preview.emergentagent.com"
API = f"{BASE}/api"
BYPASS = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}


@pytest.fixture(scope="module")
def novel_text() -> str:
    return f"Test latence SignalMar {uuid.uuid4().hex[:8]}"


def test_tts_alert_first_call_generates(novel_text):
    s = requests.Session(); s.headers.update(BYPASS)
    t0 = time.perf_counter()
    r = s.post(f"{API}/tts/alert", json={"text": novel_text, "voice": "alloy"}, timeout=30)
    dt = time.perf_counter() - t0
    print(f"[iter69] first-call (generation) took {dt*1000:.0f} ms")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("audio/mpeg"), r.headers
    assert len(r.content) > 1000, f"body too small: {len(r.content)} bytes"


def test_tts_alert_second_call_cache_hit(novel_text):
    s = requests.Session(); s.headers.update(BYPASS)
    # ensure the entry exists (first call above ran); do a second call
    t0 = time.perf_counter()
    r = s.post(f"{API}/tts/alert", json={"text": novel_text, "voice": "alloy"}, timeout=10)
    dt = time.perf_counter() - t0
    print(f"[iter69] second-call (cache hit) took {dt*1000:.0f} ms")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("audio/mpeg")
    assert len(r.content) > 1000
    # cache hit should be well under 1.5s
    assert dt < 1.5, f"cache hit too slow: {dt:.2f}s"


def test_tts_sample_regression():
    """Regression: 'Écouter' voice sample button endpoint still returns MP3."""
    s = requests.Session(); s.headers.update(BYPASS)
    r = s.get(f"{API}/tts/sample/femme-alloy", timeout=10)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("audio/mpeg")
    assert len(r.content) > 1000

    # also test the male echo sample used elsewhere in UI
    r2 = s.get(f"{API}/tts/sample/homme-echo", timeout=10)
    assert r2.status_code == 200
    assert r2.headers.get("content-type", "").startswith("audio/mpeg")
    assert len(r2.content) > 1000
