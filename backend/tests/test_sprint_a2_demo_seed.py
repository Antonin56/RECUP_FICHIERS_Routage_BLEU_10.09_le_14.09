"""Sprint A.2 — Maintainer auth/me title + 30 demo reports w/ Nano Banana photos.

Validates B1..B4 from the testing brief.
B5 (dev-bypass regression) is covered by `test_dev_bypass.py`.
"""
import re
import requests
import pytest
from datetime import datetime, timezone, timedelta


MAINTAINER = {"email": "antoninlepinay@gmail.com", "password": "123454321"}
DEMO_DISCLAIMER_FRAGMENT = "démonstration"


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@pytest.fixture(scope="module")
def maintainer_token(base_url):
    r = requests.post(f"{base_url}/api/auth/login", json=MAINTAINER, timeout=15)
    assert r.status_code == 200, f"maintainer login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def all_reports(base_url, maintainer_token):
    """Fetch the full set ONCE so we don't hammer the API."""
    r = requests.get(
        f"{base_url}/api/reports",
        headers={"Authorization": f"Bearer {maintainer_token}"},
        timeout=20,
    )
    assert r.status_code == 200, f"GET /api/reports failed: {r.status_code} {r.text}"
    return r.json()


# ----------------- B4: /api/auth/me for maintainer ------------------
class TestB4MaintainerMe:
    def test_me_returns_title_pseudo_is_dev(self, base_url, maintainer_token):
        r = requests.get(
            f"{base_url}/api/auth/me",
            headers={"Authorization": f"Bearer {maintainer_token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        u = r.json()
        assert u["pseudo"] == "SignalMar", f"pseudo={u.get('pseudo')!r}"
        assert u["title"] == "Amiral Modérateur", f"title={u.get('title')!r}"
        assert u["is_dev"] is True


# ----------------- B1: 30+ demo reports w/ disclaimer ---------------
class TestB1DemoReportsCollection:
    def test_at_least_30_reports_returned(self, all_reports):
        assert len(all_reports) >= 30, f"expected >=30 reports, got {len(all_reports)}"

    def test_all_demo_reports_meet_spec(self, all_reports):
        """Every is_demo report must carry the disclaimer, SignalMar author,
        and expires_at ~30 days in the future."""
        demo = [r for r in all_reports if r.get("is_demo") is True]
        assert len(demo) >= 30, f"expected >=30 is_demo reports, got {len(demo)}"

        now = datetime.now(timezone.utc)
        bad_disclaimer = []
        bad_author = []
        bad_ttl = []
        for r in demo:
            desc = (r.get("description") or "").lower()
            if DEMO_DISCLAIMER_FRAGMENT not in desc:
                bad_disclaimer.append(r["id"])
            author = r.get("author") or {}
            if author.get("pseudo") != "SignalMar":
                bad_author.append((r["id"], author.get("pseudo")))
            exp_str = r.get("expires_at")
            if not exp_str:
                bad_ttl.append((r["id"], "no expires_at"))
                continue
            exp = _parse_iso(exp_str)
            days = (exp - now).total_seconds() / 86400.0
            # tolerate 28..31 (script runs slightly in the past + jitter)
            if not (27 <= days <= 31):
                bad_ttl.append((r["id"], f"{days:.1f}d"))
        assert not bad_disclaimer, f"demo reports missing disclaimer: {bad_disclaimer[:5]}"
        assert not bad_author, f"demo reports with non-SignalMar author: {bad_author[:5]}"
        assert not bad_ttl, f"demo reports with bad TTL: {bad_ttl[:5]}"


# ----------------- B2: filter by type=animal_marin ------------------
class TestB2AnimalFilter:
    def test_filter_animal_marin_returns_subset(self, base_url, maintainer_token, all_reports):
        r = requests.get(
            f"{base_url}/api/reports",
            params={"types": "animal_marin"},
            headers={"Authorization": f"Bearer {maintainer_token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        filtered = r.json()
        # All filtered rows must be animal_marin
        assert all(x["type"] == "animal_marin" for x in filtered), \
            f"filter leaked non-animal types: {[x['type'] for x in filtered if x['type']!='animal_marin'][:3]}"
        assert len(filtered) >= 5, f"expected >=5 animal_marin demo reports, got {len(filtered)}"
        # Subset of full list
        all_ids = {x["id"] for x in all_reports if x["type"] == "animal_marin"}
        filt_ids = {x["id"] for x in filtered}
        assert filt_ids <= all_ids or filt_ids >= all_ids, "filter result not consistent with full list"

    def test_animal_marin_subtype_and_health_shape(self, all_reports):
        animals = [r for r in all_reports if r["type"] == "animal_marin" and r.get("is_demo")]
        assert len(animals) >= 5, f"expected >=5 demo animal_marin reports, got {len(animals)}"
        allowed_subtypes = {"mammifere", "oiseau", "autre_animal"}
        for a in animals:
            assert a["subtype"] in allowed_subtypes, \
                f"unexpected subtype {a['subtype']!r} on {a['id']}"
            extras = a.get("extras") or {}
            assert "health" in extras, f"animal report {a['id']} missing extras.health"
            if a["subtype"] == "mammifere":
                assert "species" in extras, \
                    f"mammal report {a['id']} missing extras.species"


# ----------------- B3 (post-hotfix): list returns empty photos; detail returns compressed JPEGs -----------
class TestB3PhotosListVsDetail:
    """Hotfix: GET /api/reports list endpoint MUST NOT return base64 photos
    (caused 36 MB JSON → Android JS-heap OOM). photo_count must reflect the real
    count, while GET /api/reports/{rid} still returns the full compressed payload."""

    def test_list_returns_empty_photos_but_photo_count_set(self, all_reports):
        demo = [r for r in all_reports if r.get("is_demo")]
        assert demo, "no demo reports found"
        # Every list entry must have photos == [] (no payload shipped)
        with_payload = [r["id"] for r in demo if r.get("photos")]
        assert not with_payload, (
            f"list endpoint leaked photo payloads on {len(with_payload)} reports "
            f"(first: {with_payload[:3]}) — this is the OOM regression"
        )
        # photo_count must be present and >= 0
        for r in demo[:5]:
            assert "photo_count" in r, f"report {r['id']} missing photo_count"
            assert isinstance(r["photo_count"], int) and r["photo_count"] >= 0
        # At least *some* demo reports should declare photo_count >= 1
        with_count = [r for r in demo if r.get("photo_count", 0) >= 1]
        assert with_count, "no demo report has photo_count >= 1"

    def test_detail_endpoint_returns_compressed_jpeg(self, base_url, maintainer_token, all_reports):
        target = next((r for r in all_reports if r.get("is_demo") and r.get("photo_count", 0) >= 1), None)
        assert target, "no demo report with photos to dereference"
        r = requests.get(
            f"{base_url}/api/reports/{target['id']}",
            headers={"Authorization": f"Bearer {maintainer_token}"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        photos = detail.get("photos") or []
        assert photos, f"detail endpoint returned no photos for {target['id']}"
        p0 = photos[0]
        assert isinstance(p0, str)
        # After compression: JPEG payload, < 200 KB
        assert p0.startswith("data:image/jpeg;base64,"), (
            f"expected JPEG after compression, got prefix={p0[:40]!r}"
        )
        assert len(p0) < 200_000, f"photo too large after compression: {len(p0)} bytes"
        # Decode and ensure it's a valid JPEG
        import base64
        import io
        from PIL import Image
        raw = base64.b64decode(p0.split(",", 1)[1])
        img = Image.open(io.BytesIO(raw))
        assert img.format == "JPEG", f"decoded image format = {img.format}"
        # Resized to <=800 long side
        assert max(img.size) <= 800, f"image not resized: {img.size}"
        print(f"\n  ✓ {target['id']} detail photo: {len(p0)} bytes JPEG, {img.size}")

    def test_total_list_response_size_under_200kb(self, base_url, maintainer_token):
        """Catch a regression: the full list response must stay under 200 KB."""
        r = requests.get(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {maintainer_token}"},
            timeout=20,
        )
        assert r.status_code == 200
        size = len(r.content)
        assert size < 200_000, f"list response too large: {size} bytes (OOM regression)"
        print(f"\n  ✓ /api/reports total size: {size} bytes ({size/1024:.1f} KB)")


# ----------------- TTL / Demo flag distribution audit ---------------
class TestDemoAuditExtra:
    def test_demo_distribution_coordinates_in_morbihan_bbox(self, all_reports):
        """All demo reports must fall in the Morbihan→Belle-Île bbox."""
        # bbox: lat 47.15..47.65, lng -3.65..-2.80 (generous)
        out = []
        for r in all_reports:
            if not r.get("is_demo"):
                continue
            lat, lng = r["lat"], r["lng"]
            if not (47.15 <= lat <= 47.65 and -3.65 <= lng <= -2.80):
                out.append((r["id"], lat, lng))
        assert not out, f"demo reports out of Morbihan bbox: {out[:5]}"

    def test_demo_type_diversity(self, all_reports):
        types = {r["type"] for r in all_reports if r.get("is_demo")}
        # We expect a healthy spread (≥4 of the 5 v2 types in the seed).
        assert len(types) >= 4, f"low demo type diversity: {types}"
