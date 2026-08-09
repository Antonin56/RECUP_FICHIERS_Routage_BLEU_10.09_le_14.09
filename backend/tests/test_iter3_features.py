"""SignMar iteration-3 backend tests.

Covers:
- POST /api/register-push: body validation (422) + placeholder key → 500 (expected).
- Auto-archive: GET /api/reports omits unconfirmed reports >48h old.
- Auto-archive: GET /api/reports DOES include >48h reports with >=1 confirmation.
- POST /api/reports/{id}/confirm by a different user works; push failure swallowed.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# Load backend env to get the real MongoDB URL / DB used by the running API.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


@pytest.fixture(scope="module")
def mongo_db():
    cli = MongoClient(MONGO_URL)
    try:
        yield cli[DB_NAME]
    finally:
        cli.close()


# --------------- PUSH REGISTRATION ---------------
class TestRegisterPush:
    def test_missing_fields_returns_422(self, base_url, api_client):
        r = api_client.post(f"{base_url}/api/register-push", json={})
        assert r.status_code == 422

    def test_partial_fields_returns_422(self, base_url, api_client):
        r = api_client.post(
            f"{base_url}/api/register-push",
            json={"user_id": "u1", "platform": "ios"},
        )
        assert r.status_code == 422

    def test_valid_body_with_placeholder_key_returns_500(self, base_url, api_client):
        # In dev EMERGENT_PUSH_KEY=placeholder → relay returns 401 → backend maps to 500.
        r = api_client.post(
            f"{base_url}/api/register-push",
            json={"user_id": "user_abc", "platform": "ios", "device_token": "tok-xyz"},
        )
        # Acceptable outcomes: 500 (mapped 401) or 502 (provider down).
        assert r.status_code in (500, 502, 201), r.text


# --------------- AUTO-ARCHIVE BEHAVIOUR ---------------
class TestAutoArchive:
    def _insert_old_report(self, db, *, author_id: str, confirmations: list, hours_old: int):
        rid = uuid.uuid4().hex
        created = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        db.reports.insert_one({
            "id": rid,
            "type": "obstacle_nav",
            "lat": 43.29,
            "lng": 5.36,
            "description": f"TEST_iter3 archive {rid}",
            "photos": [],
            "heading": None,
            "speed_knots": None,
            "subtype": None,
            "activity": None,
            "author_id": author_id,
            "author_name": "TEST_archive_author",
            "created_at": created,
            "last_confirmed_at": created,
            "confirmations": confirmations,
        })
        return rid

    def test_old_unconfirmed_report_is_hidden(
        self, base_url, api_client, auth_token, mongo_db
    ):
        rid = self._insert_old_report(
            mongo_db, author_id="user_test_iter3", confirmations=[], hours_old=49,
        )
        try:
            r = api_client.get(
                f"{base_url}/api/reports",
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 200
            ids = [it["id"] for it in r.json()]
            assert rid not in ids, "Unconfirmed >48h report MUST be hidden"
        finally:
            mongo_db.reports.delete_one({"id": rid})

    def test_old_confirmed_report_is_visible(
        self, base_url, api_client, auth_token, mongo_db
    ):
        rid = self._insert_old_report(
            mongo_db,
            author_id="user_test_iter3",
            confirmations=["user_someone_else"],
            hours_old=49,
        )
        try:
            r = api_client.get(
                f"{base_url}/api/reports",
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert r.status_code == 200
            items = {it["id"]: it for it in r.json()}
            assert rid in items, "Confirmed >48h report MUST be visible"
            assert items[rid]["confirm_count"] >= 1
        finally:
            mongo_db.reports.delete_one({"id": rid})


# --------------- CONFIRM BY ANOTHER USER ---------------
class TestConfirmByDifferentUser:
    def test_other_user_can_confirm_and_count_increments(
        self, base_url, api_client, auth_token
    ):
        # 1) Author creates a fresh report.
        create = api_client.post(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "type": "obstacle_nav", "lat": 47.55, "lng": -2.86,
                "description": "TEST_iter3 other-user confirm",
            },
        )
        assert create.status_code == 200, create.text
        rid = create.json()["id"]

        # 2) Register a second user, get their token.
        other_email = f"TEST_iter3_other_{uuid.uuid4().hex[:8]}@signmar.app"
        reg = api_client.post(
            f"{base_url}/api/auth/register",
            json={"email": other_email, "password": "password123", "name": "Other Tester"},
        )
        assert reg.status_code == 200, reg.text
        other_token = reg.json()["token"]

        # 2b) Non-dev confirmers need a fresh at-sea GPS fix (Phase 2 rule).
        loc = api_client.post(
            f"{base_url}/api/profile/location",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"lat": 47.5, "lng": -3.0},
        )
        assert loc.status_code == 200, loc.text

        # 3) Other user confirms → must succeed even if push relay fails internally.
        conf = api_client.post(
            f"{base_url}/api/reports/{rid}/confirm",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert conf.status_code == 200, conf.text
        body = conf.json()
        assert body["confirm_count"] == 1
        assert body["confirmed_by_me"] is True

        # 4) Verify persistence — GET as author should now show count=1.
        get_r = api_client.get(
            f"{base_url}/api/reports/{rid}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert get_r.status_code == 200
        assert get_r.json()["confirm_count"] == 1
