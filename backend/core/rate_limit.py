"""SlowAPI-based rate limiter for auth endpoints (P0 security).

Design:
    * Single ``Limiter`` instance shared across the app so all decorators
      share the same in-memory bucket store.
    * Keyed by client IP (``get_remote_address``). Behind a reverse proxy
      (K8s ingress) we prefer the first entry in ``X-Forwarded-For`` when
      present so attackers can't just rotate the pod-internal IP.
    * Storage: in-memory (default). Fine for a single-pod deployment.
      When we horizontally scale to N pods, swap ``storage_uri`` for a
      Redis URL — the API of every decorator stays identical.

Applied to:
    * POST /api/auth/register       → 20 req / 5 min / IP
    * POST /api/auth/login          → 20 req / 5 min / IP
    * POST /api/auth/google/session → 20 req / 5 min / IP (Google flow can
                                       retry on transient session errors)
    * POST /api/auth/logout         → 30 req / min / IP  (mild guard only)
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

# QA/CI bypass — when the env var is set AND the caller sends the matching
# secret header, every request gets a unique bucket key (→ never throttled).
# The token lives ONLY in backend/.env, never shipped to any client, so
# production users cannot discover it. Leave the env var unset to disable.
_BYPASS_TOKEN = os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "")


def _client_ip(request: Request) -> str:
    """Prefer X-Forwarded-For (K8s ingress) → fall back to socket peer.

    Only the FIRST entry is trusted; downstream proxies append their own IP
    so the leftmost address is the client-facing one. Never returns the
    empty string — SlowAPI would then key everything under the same bucket.
    """
    if _BYPASS_TOKEN and request.headers.get("x-ratelimit-bypass") == _BYPASS_TOKEN:
        return f"bypass-{uuid.uuid4().hex}"
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return get_remote_address(request) or "unknown"


# Single global instance. Imported by both server.py (to wire the exception
# handler + expose ``request.app.state.limiter``) and routers/auth.py (to
# decorate individual endpoints).
limiter = Limiter(
    key_func=_client_ip,
    # Global default is intentionally very loose — per-endpoint decorators
    # apply the actual security-critical limits.
    default_limits=["300/minute"],
    # Header injection requires each endpoint to accept a `response:
    # Response` param — disabled here so the auth endpoints stay ergonomic.
    # The 429 status code + Retry-After hint from SlowAPI's exception
    # handler is enough for the client.
    headers_enabled=False,
    strategy="fixed-window",
)


# ---------------------------------------------------------------------------
# Named limits (single source of truth so tests + docs can reference them)
# ---------------------------------------------------------------------------
# 24/07/2026 (armateur bloqué par des 429 en cascade) — 5/5min par IP était
# trop strict derrière l'ingress (IP partagée entre appareils + fautes de
# frappe + testeurs) → verrouillage à tort. 20/5min bloque toujours le
# brute-force (bcrypt lent + 240 essais/h max) sans enfermer les légitimes.
AUTH_LIMIT = "20/5minute"         # login, register  → anti brute-force
GOOGLE_SESSION_LIMIT = "20/5minute"  # tolerates transient session retries
LOGOUT_LIMIT = "30/minute"        # mild abuse guard only
# Phase A — OTP téléphone. La demande de code est déjà bornée côté numéro
# (cooldown 30 s + 5/h) ; la limite IP couvre l'énumération de numéros.
OTP_REQUEST_LIMIT = "8/5minute"
OTP_VERIFY_LIMIT = "15/5minute"
