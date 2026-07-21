"""Tests for the LangGraph interrupt workflow API.

Run with: USE_MOCK_LLM=true python -m pytest -v
The mock model keeps these tests fast and offline (no API keys required).
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("USE_MOCK_LLM", "true")

from main import app


@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.graph is built.
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

# Need to add tests for static_export frontend serving, but that requires a built frontend in the right place.
# if __name__ == "__main__":
#    pytest.main([__file__, "-v"])
