"""Backend verification of the PDF regeneration bug fix.

Validates the HTTP contract for the synthese PDF endpoints without
rendering the PDF visually.
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback env var name used by some Expo setups
    BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")

assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL must be set"


# Endpoints under test
NEW_PDF_PATH = "/api/docs/synthese-2026-07-08.pdf"
OLD_PDF_PATH = "/api/docs/synthese-2026-07-07.pdf"

NEW_PDF_FILENAME = "SignalMar_Synthese_2026-07-08.pdf"
OLD_PDF_FILENAME = "SignalMar_Synthese_2026-07-07.pdf"


@pytest.fixture(scope="module")
def new_pdf_response():
    return requests.get(f"{BASE_URL}{NEW_PDF_PATH}", timeout=30, allow_redirects=True)


@pytest.fixture(scope="module")
def old_pdf_response():
    return requests.get(f"{BASE_URL}{OLD_PDF_PATH}", timeout=30, allow_redirects=True)


# ---- New PDF checks (2026-07-08) -------------------------------------------------


class TestNewPdfEndpoint:
    def test_status_and_content_type(self, new_pdf_response):
        assert new_pdf_response.status_code == 200, (
            f"Expected 200 got {new_pdf_response.status_code}"
        )
        ct = new_pdf_response.headers.get("Content-Type", "")
        assert "application/pdf" in ct.lower(), f"Wrong Content-Type: {ct}"

    def test_non_zero_body(self, new_pdf_response):
        # Expect roughly ~21 KB — assert > 5 KB minimum to allow flex
        body = new_pdf_response.content
        assert len(body) > 5_000, f"PDF body too small: {len(body)} bytes"

    def test_content_disposition_attachment_with_filename(self, new_pdf_response):
        cd = new_pdf_response.headers.get("Content-Disposition", "")
        assert cd, "Missing Content-Disposition header"
        assert "attachment" in cd.lower(), f"Not an attachment: {cd}"
        assert NEW_PDF_FILENAME in cd, (
            f"Expected filename '{NEW_PDF_FILENAME}' in Content-Disposition, got: {cd}"
        )

    def test_pdf_magic_signature(self, new_pdf_response):
        body = new_pdf_response.content
        assert body[:5] == b"%PDF-", (
            f"Body does not start with %PDF- magic. First bytes: {body[:16]!r}"
        )

    def test_endpoint_is_public_no_auth_required(self):
        # Explicitly send a fresh session with no auth headers/cookies
        s = requests.Session()
        r = s.get(f"{BASE_URL}{NEW_PDF_PATH}", timeout=30)
        assert r.status_code == 200, (
            f"Endpoint should be public but got {r.status_code}"
        )


# ---- Old PDF regression checks (2026-07-07) --------------------------------------


class TestOldPdfEndpointNoRegression:
    def test_status_and_content_type(self, old_pdf_response):
        assert old_pdf_response.status_code == 200, (
            f"Expected 200 got {old_pdf_response.status_code}"
        )
        ct = old_pdf_response.headers.get("Content-Type", "")
        assert "application/pdf" in ct.lower(), f"Wrong Content-Type: {ct}"

    def test_content_disposition_filename(self, old_pdf_response):
        cd = old_pdf_response.headers.get("Content-Disposition", "")
        assert cd, "Missing Content-Disposition header"
        assert OLD_PDF_FILENAME in cd, (
            f"Expected filename '{OLD_PDF_FILENAME}' in Content-Disposition, got: {cd}"
        )

    def test_pdf_magic_signature(self, old_pdf_response):
        body = old_pdf_response.content
        assert body[:5] == b"%PDF-", (
            f"Body does not start with %PDF- magic. First bytes: {body[:16]!r}"
        )
