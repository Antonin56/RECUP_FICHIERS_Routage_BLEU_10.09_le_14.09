"""Iter-5: points + rank tracking for edit propose / vote / apply."""
import uuid
import requests


# ------------- helpers -------------------------------------------------------
def _register(base_url):
    email = f"TEST_iter5_{uuid.uuid4().hex[:8]}@signmar.app"
    r = requests.post(
        f"{base_url}/api/auth/register",
        json={"email": email, "password": "password123", "name": "Iter5 Marin"},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["user"]


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _me(base_url, token):
    r = requests.get(f"{base_url}/api/auth/me", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _create_report(base_url, token, lat=47.5, lng=-3.0):
    r = requests.post(
        f"{base_url}/api/reports",
        json={"type": "obstacle_nav", "lat": lat, "lng": lng, "description": "iter5 obs"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 1. Proposing an edit grants +1 to proposer ----------------------
def test_propose_edit_grants_one_point(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    p_tok, _ = _register(base_url)
    pts_before = _me(base_url, p_tok)["points"]

    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "fake", "comment": "TEST_iter5"},
        headers=_auth(p_tok),
    )
    assert r.status_code == 201, r.text
    pts_after = _me(base_url, p_tok)["points"]
    assert pts_after - pts_before == 1, f"expected +1, got {pts_after - pts_before}"


# ---------- 2. Applied edit gives the proposer +5 extra (1+5 = 6) -----------
def test_applied_edit_gives_proposer_six_points(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    p_tok, p_user = _register(base_url)
    pts_before = _me(base_url, p_tok)["points"]

    propose = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "fake"},
        headers=_auth(p_tok),
    )
    assert propose.status_code == 201
    eid = propose.json()["edits"][0]["id"]

    voter_tok, _ = _register(base_url)
    vr = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "up"},
        headers=_auth(voter_tok),
    )
    assert vr.status_code == 200, vr.text
    # confirm applied
    e = next(x for x in vr.json()["edits"] if x["id"] == eid)
    assert e["applied"] is True

    pts_after = _me(base_url, p_tok)["points"]
    delta = pts_after - pts_before
    assert delta == 6, f"expected proposer delta=+6 (1 propose + 5 applied), got {delta}"


# ---------- 3. Voter (not proposer) gains +1 once ---------------------------
def test_voter_gains_one_point_only_once(base_url, auth_token):
    rid = _create_report(base_url, auth_token)["id"]
    p_tok, _ = _register(base_url)
    propose = requests.post(
        f"{base_url}/api/reports/{rid}/edits",
        json={"kind": "ended"},
        headers=_auth(p_tok),
    )
    eid = propose.json()["edits"][0]["id"]

    v_tok, _ = _register(base_url)
    pts_before = _me(base_url, v_tok)["points"]

    # First up-vote → +1
    r = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "up"},
        headers=_auth(v_tok),
    )
    assert r.status_code == 200
    pts1 = _me(base_url, v_tok)["points"]
    assert pts1 - pts_before == 1, f"expected +1 on first vote, got {pts1 - pts_before}"

    # Toggle to down → no new point
    r2 = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "down"},
        headers=_auth(v_tok),
    )
    assert r2.status_code == 200
    pts2 = _me(base_url, v_tok)["points"]
    assert pts2 == pts1, f"expected no change on toggle, got delta={pts2 - pts1}"

    # Toggle back to up → still no new point
    r3 = requests.post(
        f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
        json={"vote": "up"},
        headers=_auth(v_tok),
    )
    assert r3.status_code == 200
    pts3 = _me(base_url, v_tok)["points"]
    assert pts3 == pts1, f"expected no change on re-toggle, got delta={pts3 - pts1}"


# ---------- 4. points_for_rank → 'Vigie communautaire' at >=1500 ------------
def test_points_for_rank_vigie_communautaire():
    """Direct unit-style import of the rank function from server.py."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path("/app/backend").resolve()))
    from server import points_for_rank  # noqa: E402

    assert points_for_rank(0) == "Mousse"
    assert points_for_rank(20) == "Équipier"
    assert points_for_rank(80) == "Chef de bord"
    assert points_for_rank(200) == "Skipper"
    assert points_for_rank(500) == "Capitaine"
    assert points_for_rank(1499) == "Capitaine"
    assert points_for_rank(1500) == "Vigie communautaire"
    assert points_for_rank(9999) == "Vigie communautaire"


# ---------- 5. /auth/me 'rank' string follows points ------------------------
def test_auth_me_rank_string_present(base_url, auth_token):
    me = _me(base_url, auth_token)
    assert "rank" in me and isinstance(me["rank"], str) and me["rank"]
    assert "points" in me and isinstance(me["points"], int)
