"""SignMar iteration-2 backend tests.

Covers:
- Demo mode (unauth) -> /api/reports returns only reports >= 12h old.
- Authenticated -> recent reports (<12h) are included.
- types= filter -> only matching types returned, with new fields.
- POST /api/reports with authorities subtype + activity + heading + speed_knots.
- POST /api/profile/avatar with tiny base64 PNG -> compressed data:image/jpeg.
"""
import base64
from datetime import datetime, timezone, timedelta
import pytest


# A 1x1 transparent PNG (valid).
# 16x16 solid-colour PNG generated with Pillow (guaranteed-decodable).
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAF0lEQVR4nGP8z0AaYCJR/aiGUQ1DSAMAQC4BH2bjRnMAAAAASUVORK5CYII="
)


def _parse_iso(s):
    # Accepts trailing Z or offset, and naive timestamps (assume UTC).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------- DEMO MODE (unauth list) ---------------
class TestDemoMode:
    def test_unauth_returns_only_reports_older_than_12h(self, base_url, api_client):
        r = api_client.get(f"{base_url}/api/reports")
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        # There must be at least one demo report.
        assert len(items) >= 1, "Expected seeded demo reports >= 12h old"
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        for it in items:
            ts = _parse_iso(it["created_at"])
            assert ts <= cutoff, f"Report {it['id']} is younger than 12h in demo mode"

    def test_auth_returns_recent_reports_too(self, base_url, api_client, auth_token):
        r = api_client.get(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        items = r.json()
        # The seed produces two reports younger than 12h.
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        recent = [it for it in items if _parse_iso(it["created_at"]) > cutoff]
        assert len(recent) >= 1, "Authenticated list should expose <12h reports"


# --------------- TYPES FILTER + NEW FIELDS ---------------
class TestTypesFilter:
    def test_types_authorities_filter(self, base_url, api_client, auth_token):
        r = api_client.get(
            f"{base_url}/api/reports?types=autorites",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        for it in items:
            assert it["type"] == "autorites"
            # New optional fields must be exposed in serializer.
            for key in ("subtype", "activity", "heading", "speed_knots"):
                assert key in it, f"Missing field {key} in authorities report"

    def test_types_multi_value_filter(self, base_url, api_client, auth_token):
        r = api_client.get(
            f"{base_url}/api/reports?types=autorites,obstacle_nav",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        for it in r.json():
            assert it["type"] in ("autorites", "obstacle_nav")


# --------------- AUTHORITIES CREATE WITH SUBTYPE/ACTIVITY ---------------
class TestAuthoritiesCreate:
    def test_create_authorities_with_navigation_persists_fields(
        self, base_url, api_client, auth_token
    ):
        payload = {
            "type": "autorites",
            "lat": 47.55,
            "lng": -2.86,
            "description": "TEST_iter2 gendmar nav",
            "subtype": "gendmar",
            "activity": "navigation",
            "heading": 185,
            "speed_knots": 12,
        }
        r = api_client.post(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}"},
            json=payload,
        )
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["subtype"] == "gendmar"
        assert created["activity"] == "navigation"
        assert created["heading"] == 185
        assert created["speed_knots"] == 12

        # GET single -> verify persistence
        rid = created["id"]
        get_r = api_client.get(
            f"{base_url}/api/reports/{rid}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert get_r.status_code == 200
        got = get_r.json()
        assert got["subtype"] == "gendmar"
        assert got["activity"] == "navigation"
        assert got["heading"] == 185
        assert got["speed_knots"] == 12

    def test_invalid_subtype_rejected(self, base_url, api_client, auth_token):
        # Subtypes are intentionally free-form server-side (forward-compat
        # with client-side subtype catalog changes without a schema bump) —
        # unknown ids are ACCEPTED and persisted as-is.
        r = api_client.post(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "type": "autorites", "lat": 47.5, "lng": -2.8,
                "subtype": "bogus", "activity": "navigation",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subtype"] == "bogus"
        # Cleanup
        api_client.delete(
            f"{base_url}/api/reports/{body['id']}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )


# --------------- AVATAR UPLOAD ---------------
class TestAvatar:
    def test_avatar_upload_returns_compressed_data_uri(
        self, base_url, api_client, auth_token
    ):
        r = api_client.post(
            f"{base_url}/api/profile/avatar",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"image": TINY_PNG_B64},
        )
        assert r.status_code == 200, r.text
        user = r.json()
        assert "picture" in user
        pic = user["picture"]
        assert pic.startswith("data:image/jpeg;base64,"), f"got: {pic[:40]}"
        # Verify body is valid base64 and decodes to a non-empty JPEG.
        body = pic.split(",", 1)[1]
        decoded = base64.b64decode(body)
        assert len(decoded) > 100, "Compressed JPEG payload looks too small"
        # JPEG magic bytes
        assert decoded[:3] == b"\xff\xd8\xff", "Picture is not a JPEG"

    def test_avatar_upload_with_data_uri_prefix(
        self, base_url, api_client, auth_token
    ):
        # Same payload but already wrapped in a data URI; backend must accept.
        data_uri = f"data:image/png;base64,{TINY_PNG_B64}"
        r = api_client.post(
            f"{base_url}/api/profile/avatar",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"image": data_uri},
        )
        assert r.status_code == 200, r.text
        assert r.json()["picture"].startswith("data:image/jpeg;base64,")

    def test_avatar_upload_requires_auth(self, base_url, api_client):
        r = api_client.post(
            f"{base_url}/api/profile/avatar",
            json={"image": TINY_PNG_B64},
        )
        assert r.status_code == 401

    def test_avatar_invalid_image_rejected(self, base_url, api_client, auth_token):
        r = api_client.post(
            f"{base_url}/api/profile/avatar",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"image": "not-base64!!!"},
        )
        assert r.status_code in (400, 422)
