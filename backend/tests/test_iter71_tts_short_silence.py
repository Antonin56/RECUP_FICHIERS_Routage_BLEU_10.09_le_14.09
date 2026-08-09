"""Iter 71 — Verify TTS alert MP3 is prefixed with the SHORT 350 ms silence
(1536 bytes) instead of the previous 2000 ms silence (8492 bytes).

Fix under test: /app/backend/routers/tts.py — `_SILENCE_PATH` now points to
`silence_350ms.mp3`. The bug caused a ~2 s pre-voice silence even on cache
hits, breaking the "sound-simultaneous-with-popup" UX.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import requests


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://maritime-routing-v3.preview.emergentagent.com").rstrip("/")
SILENCE_350_PATH = Path("/app/backend/tts_samples/silence_350ms.mp3")
SILENCE_2000_PATH = Path("/app/backend/tts_samples/silence_2000ms.mp3")

# 5 catalog phrases across both voices — cache hits guaranteed (pregen iter69/70)
CATALOG_PHRASES = [
    "Attention, gendarmerie maritime signalée dans votre périmètre d'alerte.",
    "Attention, affaires maritimes signalées dans votre périmètre d'alerte.",
    "Attention, autorité maritime signalée dans votre périmètre d'alerte.",
    "Soyez vigilant, mammifère marin signalé dans votre périmètre d'alerte.",
    "Attention ! Soyez très vigilant : pollution importante signalée dans votre périmètre d'alerte.",
]

QA_HEADERS = {
    "Content-Type": "application/json",
    "X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60",
}


@pytest.fixture(scope="module")
def silence_350_bytes() -> bytes:
    assert SILENCE_350_PATH.exists(), f"silence file missing: {SILENCE_350_PATH}"
    b = SILENCE_350_PATH.read_bytes()
    assert len(b) == 1536, f"expected 350ms silence = 1536 B, got {len(b)}"
    return b


@pytest.fixture(scope="module")
def silence_2000_bytes() -> bytes:
    assert SILENCE_2000_PATH.exists(), f"old silence file missing: {SILENCE_2000_PATH}"
    b = SILENCE_2000_PATH.read_bytes()
    assert len(b) == 8492
    return b


class TestSilenceFileStructure:
    """The silence_350ms.mp3 file must be a valid MP3 (frame sync at offset 0)."""

    def test_350ms_starts_with_mp3_frame_sync(self, silence_350_bytes):
        # MP3 frame sync = 11 bits set: 0xFF 0xEx-0xFx. Our file: 0xFF 0xF3 …
        assert silence_350_bytes[0] == 0xFF
        assert (silence_350_bytes[1] & 0xE0) == 0xE0, (
            f"byte[1]=0x{silence_350_bytes[1]:02x} — top 3 bits must be 111 (frame sync)"
        )
        # MPEG-2 Layer III, sample rate 24 kHz, 32 kbps mono (0xFFF3 0x84C0)
        assert silence_350_bytes[:2] == b"\xff\xf3"

    def test_350ms_not_id3_tagged(self, silence_350_bytes):
        # 2000ms file starts with "ID3" — 350ms must NOT (would introduce a
        # decode-time header offset).
        assert not silence_350_bytes.startswith(b"ID3")

    def test_350ms_is_not_prefix_of_2000ms(self, silence_350_bytes, silence_2000_bytes):
        # Just a sanity check: they are structurally different files (2000ms
        # has an ID3 header, 350ms is raw frames).
        assert not silence_2000_bytes.startswith(silence_350_bytes)


class TestTtsAlertPrefixShortSilence:
    """POST /api/tts/alert response MUST start with silence_350ms.mp3 bytes."""

    @pytest.mark.parametrize("phrase", CATALOG_PHRASES)
    @pytest.mark.parametrize("voice", ["alloy", "echo"])
    def test_response_starts_with_350ms_silence(self, phrase, voice, silence_350_bytes, silence_2000_bytes):
        r = requests.post(
            f"{BASE_URL}/api/tts/alert",
            headers=QA_HEADERS,
            json={"text": phrase, "voice": voice},
            timeout=15,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("audio/mpeg")

        body = r.content
        assert len(body) > 1536, f"response too short: {len(body)} B"

        # PRIMARY assertion: prefix must be the 350 ms silence.
        assert body[:1536] == silence_350_bytes, (
            "response body does NOT start with silence_350ms.mp3 bytes — "
            "the old 2000 ms silence may still be prepended!"
        )
        # NEGATIVE: must NOT start with the 2000 ms file (its ID3 header
        # would show up as bytes 'I','D','3' at offset 0).
        assert not body.startswith(b"ID3"), (
            "response body starts with 'ID3' — the OLD 2000 ms silence is still prepended!"
        )
        assert not body.startswith(silence_2000_bytes[:16])

    def test_frame_sync_after_silence_prefix(self, silence_350_bytes):
        """Byte 1536 (right after the silence prefix) should be an MP3 frame
        header start (0xFF 0xEx…) — proves the OpenAI-generated voice MP3
        is correctly concatenated behind the silence."""
        r = requests.post(
            f"{BASE_URL}/api/tts/alert",
            headers=QA_HEADERS,
            json={
                "text": CATALOG_PHRASES[0],
                "voice": "alloy",
            },
            timeout=15,
        )
        assert r.status_code == 200
        body = r.content
        assert body[:1536] == silence_350_bytes
        # OpenAI TTS-1-HD MP3 output = 24 kHz mono → frame sync 0xFFF3…
        assert body[1536] == 0xFF, f"offset 1536 = 0x{body[1536]:02x} (expected 0xFF frame sync)"
        assert (body[1537] & 0xE0) == 0xE0, (
            f"offset 1537 = 0x{body[1537]:02x} — top 3 bits must be 111 (MP3 frame sync)"
        )


class TestTtsAlertPerformance:
    """Cache-hit latency must remain < 1.5 s (no regression from iter70)."""

    @pytest.mark.parametrize("phrase", CATALOG_PHRASES)
    @pytest.mark.parametrize("voice", ["alloy", "echo"])
    def test_cache_hit_under_1500ms(self, phrase, voice):
        t0 = time.perf_counter()
        r = requests.post(
            f"{BASE_URL}/api/tts/alert",
            headers=QA_HEADERS,
            json={"text": phrase, "voice": voice},
            timeout=10,
        )
        dt = time.perf_counter() - t0
        assert r.status_code == 200
        assert dt < 1.5, f"cache-hit took {dt*1000:.0f} ms for ({voice}) « {phrase[:40]}… » — must be < 1500 ms"


class TestGendarmerieExact:
    """The exact gendarmerie phrase from the review request must return
    a MP3 that starts with the short silence."""

    def test_gendarmerie_alloy_shape(self, silence_350_bytes):
        r = requests.post(
            f"{BASE_URL}/api/tts/alert",
            headers=QA_HEADERS,
            json={
                "text": "Attention, gendarmerie maritime signalée dans votre périmètre d'alerte.",
                "voice": "alloy",
            },
            timeout=15,
        )
        assert r.status_code == 200
        body = r.content
        # main-agent notes: total size ~97056 B for this phrase (350 ms + voice)
        assert 50_000 < len(body) < 200_000, f"unexpected size {len(body)} B"
        assert body[:1536] == silence_350_bytes
