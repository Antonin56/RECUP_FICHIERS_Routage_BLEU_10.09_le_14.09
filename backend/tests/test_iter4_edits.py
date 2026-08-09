"""Iter-4 tests: community-driven report edit proposals + voting."""
import uuid
import pytest
import requests


# ---------- helpers ---------------------------------------------------------
def _register_user(base_url):
    email = f"TEST_iter4_{uuid.uuid4().hex[:8]}@signmar.app"
    r = requests.post(
        f"{base_url}/api/auth/register",
        json={"email": email, "password": "password123", "name": "Iter4 Marin"},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["user"]


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _create_report(base_url, token, lat=47.5, lng=-3.0):
    r = requests.post(
        f"{base_url}/api/reports",
        json={"type": "obstacle_nav", "lat": lat, "lng": lng, "description": "TEST_iter4 obstacle"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 1. propose-edit happy path --------------------------------------
def test_propose_edit_creates_edit_with_auto_upvote(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    second_token, _ = _register_user(base_url)

    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "fake", "comment": "rien à signaler"},
        headers=_auth(second_token),
    )
    assert r.status_code == 201, r.text
    rep = r.json()
    assert len(rep["edits"]) == 1
    e = rep["edits"][0]
    assert e["kind"] == "fake"
    assert e["up_count"] == 1
    assert e["down_count"] == 0
    assert e["applied"] is False
    assert e["my_vote"] == "up"  # proposer = auto-upvote


# ---------- 2. shift without coords → 400 -----------------------------------
def test_propose_shift_without_coords_returns_400(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "shift"},
        headers=_auth(auth_token),
    )
    assert r.status_code == 400, r.text


# ---------- 3. second up-vote → auto-apply (fake) ---------------------------
def test_second_upvote_applies_fake_edit(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    proposer_token, _ = _register_user(base_url)

    propose = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "fake"},
        headers=_auth(proposer_token),
    )
    eid = propose.json()["edits"][0]["id"]

    voter_token, _ = _register_user(base_url)
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "up"},
        headers=_auth(voter_token),
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["flagged_fake"] is True
    edit = next(e for e in rep["edits"] if e["id"] == eid)
    assert edit["up_count"] == 2
    assert edit["applied"] is True
    assert edit["applied_at"] is not None


# ---------- 3b. shift auto-apply moves lat/lng ------------------------------
def test_shift_edit_applies_and_moves_position(base_url, auth_token):
    rid = _create_report(base_url, auth_token, lat=47.0, lng=-3.0)["id"]
    proposer_token, _ = _register_user(base_url)
    propose = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "shift", "new_lat": 48.123, "new_lng": -4.456},
        headers=_auth(proposer_token),
    )
    assert propose.status_code == 201, propose.text
    eid = propose.json()["edits"][0]["id"]

    voter_token, _ = _register_user(base_url)
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "up"},
        headers=_auth(voter_token),
    )
    assert r.status_code == 200
    rep = r.json()
    assert abs(rep["lat"] - 48.123) < 1e-6
    assert abs(rep["lng"] - (-4.456)) < 1e-6
    assert next(e for e in rep["edits"] if e["id"] == eid)["applied"] is True


# ---------- 3c. ended auto-apply sets status --------------------------------
def test_ended_edit_applies_and_sets_status(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    proposer_token, _ = _register_user(base_url)
    propose = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "ended"},
        headers=_auth(proposer_token),
    )
    eid = propose.json()["edits"][0]["id"]
    voter_token, _ = _register_user(base_url)
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "up"},
        headers=_auth(voter_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ended"


# ---------- 4. toggle vote: up → down replaces ------------------------------
def test_vote_toggle_replaces_previous(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    proposer_token, _ = _register_user(base_url)
    propose = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "fake"},
        headers=_auth(proposer_token),
    )
    eid = propose.json()["edits"][0]["id"]
    voter_token, _ = _register_user(base_url)

    # First up
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "up"},
        headers=_auth(voter_token),
    )
    edit = next(e for e in r.json()["edits"] if e["id"] == eid)
    assert edit["up_count"] == 2 and edit["down_count"] == 0

    # Now toggle to down
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "down"},
        headers=_auth(voter_token),
    )
    edit = next(e for e in r.json()["edits"] if e["id"] == eid)
    assert edit["up_count"] == 1
    assert edit["down_count"] == 1
    assert edit["my_vote"] == "down"


# ---------- 5. GET /reports/{id} my_vote reflects caller --------------------
def test_get_report_my_vote_reflects_caller(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    proposer_token, _ = _register_user(base_url)
    propose = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "fake"},
        headers=_auth(proposer_token),
    )
    eid = propose.json()["edits"][0]["id"]

    # Proposer sees their own vote as 'up'
    r = requests.get(f"{base_url}/api/reports/{rid}", headers=_auth(proposer_token))
    assert r.status_code == 200
    e = next(x for x in r.json()["edits"] if x["id"] == eid)
    assert e["my_vote"] == "up"

    # Author who hasn't voted sees null
    r2 = requests.get(f"{base_url}/api/reports/{rid}", headers=_auth(auth_token))
    e2 = next(x for x in r2.json()["edits"] if x["id"] == eid)
    assert e2["my_vote"] is None


# ---------- 6. unauth propose-edit rejected --------------------------------
def test_propose_edit_requires_auth(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "fake"},
    )
    assert r.status_code == 401


# ---------- 7. propose on missing report → 404 ------------------------------
def test_propose_edit_on_missing_report_404(base_url, auth_token):
    r = requests.post(
        f"{base_url}/api/reports/does-not-exist/edits",
        json={"kind": "fake"},
        headers=_auth(auth_token),
    )
    assert r.status_code == 404
