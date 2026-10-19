import json

import pytest
from fastapi.testclient import TestClient

from main import app
from scripts.export_auth_fixture import OUTPUT_PATH, render


def test_auth_fixture_is_up_to_date():
    assert OUTPUT_PATH.read_text() == render(), (
        "frontend/lib/fixtures/auth-responses.json is stale relative to the auth models. "
        "Run `uv run python -m scripts.export_auth_fixture` (from backend/) and commit the result."
    )


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_live_auth_endpoint_matches_fixture_shape(client):
    """The real /api/auth response must have the same [AuthResponse, CustomerContext|null] shape."""
    fixture = json.loads(OUTPUT_PATH.read_text())

    csr_auth, csr_ctx = client.post("/api/auth", json={"email_addr": "threecuptea@gmail.com"}).json()
    assert set(csr_auth) == set(fixture["csr"][0])
    assert csr_ctx is None

    cust_auth, cust_ctx = client.post("/api/auth", json={"email_addr": "anderson.cooper@cnn.com"}).json()
    want_auth, want_ctx = fixture["customer"]
    assert set(cust_auth) == set(want_auth)
    assert set(cust_ctx) == set(want_ctx)
    assert set(cust_ctx["latest_orders"][0]) == set(want_ctx["latest_orders"][0])
    assert set(cust_ctx["latest_orders"][0]["items"][0]) == set(want_ctx["latest_orders"][0]["items"][0])
