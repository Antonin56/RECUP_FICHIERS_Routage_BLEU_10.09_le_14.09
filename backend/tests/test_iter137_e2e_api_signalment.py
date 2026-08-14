"""
E2E API test for iter137 armateur bug + mark-report feature (SignalMar).

Flow:
1. Login (email/password) → JWT
2. POST /api/routes/compute/async (engine_f, Arradon → La Trinité approach)
3. Poll GET /api/routes/job/{id} until done
4. Assertions on route: distance_m < 23100, at least one waypoint in the chenal box,
   wrong_side_marks empty, no "⚠ La route passe à ~" warning
5. POST /api/routes/mark-report with the route_id + mark "Truie d'Arradon"
6. GET /api/routes/mark-reports → the report is listed with joined data
"""
import os
import time
import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
BYPASS = "qa-bypass-signalmar-2026"

EMAIL = "antoninlepinay@gmail.com"
PWD = "123454321"

CHENAL_BOX = {"lat_lo": 47.604, "lat_hi": 47.6094, "lng_lo": -2.841, "lng_hi": -2.831}


@pytest.fixture(scope="module")
def session():
    assert BASE_URL, "Missing EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL"
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "X-RateLimit-Bypass": BYPASS,
    })
    return s


@pytest.fixture(scope="module")
def token(session):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PWD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("token") or body.get("access_token")
    assert tok, f"no token in login response: {body}"
    session.headers.update({"Authorization": f"Bearer {tok}"})
    return tok


@pytest.fixture(scope="module")
def route_result(session, token):
    payload = {
        "start": {"lat": 47.61417599274132, "lng": -2.828185517975284},
        "end": {"lat": 47.58565138724609, "lng": -3.023353153422526},
        "draft_m": 1.0,
        "depth_margin_m": 0.5,
        "use_tide": False,
        "engine_id": "engine_f",
    }
    r = session.post(f"{BASE_URL}/api/routes/compute/async", json=payload, timeout=60)
    assert r.status_code == 200, f"compute/async failed: {r.status_code} {r.text}"
    job = r.json()
    job_id = job.get("job_id") or job.get("id")
    assert job_id, f"no job_id: {job}"

    deadline = time.time() + 300
    last = None
    while time.time() < deadline:
        rr = session.get(f"{BASE_URL}/api/routes/job/{job_id}", timeout=30)
        assert rr.status_code == 200, f"job poll failed: {rr.status_code} {rr.text}"
        last = rr.json()
        status = last.get("status")
        if status in ("done", "success", "completed"):
            break
        if status in ("error", "failed"):
            pytest.fail(f"job failed: {last}")
        time.sleep(2)
    assert last, "no polling response"
    assert last.get("status") in ("done", "success", "completed"), f"job did not complete in time: {last}"
    result = last.get("result") or last
    return result


class TestArradonChenal:
    def test_distance_reduced(self, route_result):
        dist = route_result.get("distance_m") or route_result.get("route", {}).get("distance_m")
        assert dist is not None, f"no distance_m: keys={list(route_result.keys())}"
        assert dist < 23100, f"distance_m={dist} still >= 23100 (before fix was 23602)"

    def test_waypoint_in_chenal_box(self, route_result):
        wps = (
            route_result.get("waypoints")
            or route_result.get("route", {}).get("waypoints")
            or []
        )
        assert wps, "no waypoints"
        in_box = [
            w for w in wps
            if CHENAL_BOX["lat_lo"] <= w.get("lat", 0) <= CHENAL_BOX["lat_hi"]
            and CHENAL_BOX["lng_lo"] <= w.get("lng", 0) <= CHENAL_BOX["lng_hi"]
        ]
        assert in_box, (
            f"no waypoint inside chenal box {CHENAL_BOX}. "
            f"waypoint count={len(wps)} first={wps[0]} last={wps[-1]}"
        )

    def test_no_wrong_side_marks(self, route_result):
        wsm = (
            route_result.get("wrong_side_marks")
            or route_result.get("route", {}).get("wrong_side_marks")
            or []
        )
        assert wsm == [], f"wrong_side_marks not empty: {wsm}"

    def test_no_grazing_warning(self, route_result):
        warns = (
            route_result.get("warnings")
            or route_result.get("route", {}).get("warnings")
            or []
        )
        grazing = [w for w in warns if "La route passe à ~" in (w if isinstance(w, str) else w.get("message", ""))]
        assert grazing == [], f"grazing warnings still present: {grazing}"


class TestMarkReport:
    def test_mark_report_send_and_list(self, session, token, route_result):
        route_id = route_result.get("route_id") or route_result.get("id") or route_result.get("route", {}).get("route_id")
        assert route_id, f"no route_id in result: keys={list(route_result.keys())}"

        payload = {
            "route_id": route_id,
            "mark_name": "Truie d'Arradon",
            "comment": "test QA iter137",
        }
        r = session.post(f"{BASE_URL}/api/routes/mark-report", json=payload, timeout=30)
        assert r.status_code == 200, f"mark-report POST failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True, f"ok not true: {body}"
        report_id = body.get("report_id")
        assert report_id and report_id.startswith("BR-"), f"unexpected report_id: {report_id}"
        assert body.get("route_found") is True, f"route_found not true: {body}"

        # Now list
        r2 = session.get(f"{BASE_URL}/api/routes/mark-reports", timeout=30)
        assert r2.status_code == 200, f"mark-reports GET failed: {r2.status_code} {r2.text}"
        listing = r2.json()
        items = listing if isinstance(listing, list) else listing.get("items") or listing.get("reports") or []
        assert items, f"no reports listed: {listing}"
        match = [it for it in items if it.get("report_id") == report_id or it.get("id") == report_id]
        assert match, f"created report {report_id} not found in listing (count={len(items)})"
        it = match[0]
        assert it.get("mark_name") == "Truie d'Arradon", f"mark_name mismatch: {it}"
        # engine_id joined from route
        assert it.get("engine_id") == "engine_f", f"engine_id not joined: {it}"
