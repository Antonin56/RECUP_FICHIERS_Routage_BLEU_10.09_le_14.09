import os
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load frontend .env to get the public URL + backend .env for the QA
# rate-limit bypass token.
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")

# ── QA rate-limit bypass ────────────────────────────────────────────────
# The P0 SlowAPI limiter throttles /auth/* to 5 req/5min per IP. The test
# suite hammers register/login far beyond that, so every requests.Session
# transparently sends the secret bypass header (matched server-side against
# RATE_LIMIT_BYPASS_TOKEN in backend/.env). Requests without the header —
# i.e. real clients — are still rate-limited normally.
_RL_BYPASS = os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "")
if _RL_BYPASS:
    _orig_session_init = requests.Session.__init__

    def _patched_session_init(self, *args, **kwargs):
        _orig_session_init(self, *args, **kwargs)
        self.headers["X-RateLimit-Bypass"] = _RL_BYPASS

    requests.Session.__init__ = _patched_session_init


@pytest.fixture(scope="session")
def base_url():
    assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set in frontend/.env"
    return BASE_URL


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def test_credentials():
    return {"email": "test@signmar.app", "password": "password123", "name": "Test User"}


@pytest.fixture(scope="session")
def auth_token(base_url, test_credentials):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    # Try login; register if needed
    r = s.post(f"{base_url}/api/auth/login", json={
        "email": test_credentials["email"],
        "password": test_credentials["password"],
    })
    if r.status_code != 200:
        r = s.post(f"{base_url}/api/auth/register", json=test_credentials)
        assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return data["token"]
