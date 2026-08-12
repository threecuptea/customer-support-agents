from fastapi.testclient import TestClient
import pytest
from main import app
import services.auth_service as auth_service
from datetime import datetime
from zoneinfo import ZoneInfo


_zoneinfo = ZoneInfo("America/New_York")

@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.approval_graph is built. app instead of router should be the entry point.
    with TestClient(app) as test_client:
        yield test_client


def test_csr_role_whitelist(client):
    email_addr = "threecuptea@gmail.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'csr'
    assert data['customer_context'] is None


def test_csr_role_domain(client, monkeypatch: pytest.MonkeyPatch):
    # It is only effective in this test
    monkeypatch.setattr(auth_service, "__csr_whitelist", "")
    monkeypatch.setattr(auth_service, "__csr_domains", "threecuptea.com")
    email_addr = "sonya.ling@threecuptea.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'csr'
    assert data['customer_context'] is None

def test_csr_role_no_whitelist_no_domain(client, monkeypatch: pytest.MonkeyPatch):
    # It is only effective in this test
    monkeypatch.setattr(auth_service, "__csr_whitelist", "")
    monkeypatch.setattr(auth_service, "__csr_domains", "")
    email_addr = "sonya.ling@threecuptea.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 500
    
def test_email_not_found(client):
    # without monkeypatch to set __csr_domains, it should return not found
    email_addr = "sonya.ling@threecuptea.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 404    

# Type hinting alone does not change a field's requirement status and a default value is still required.
# name: str | None = None: Input Value Can Be None? Yes, Field Can Be Omitted entirely? Yes

def test_a_normal_order(client):
    # An order that has been delivered is allowed to return  
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][0]
    assert order['status'] == 'delivered'
    # what I got is a text of datetime.fromisoformat
    assert datetime.fromisoformat(order['estimated_delivery_date']) < datetime.now(tz= _zoneinfo)

def test_a_pending_order(client):
    # An order that is at 
    email_addr = "john.king@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][0]
    assert order['status'] == 'pending'
    assert order['order_date'] # a required field 
    assert not order['ship_date'] # an optional field
    assert not order['estimated_delivery_date'] # an optional field

def test_an_order_missing_required(client):
    # An order that is at 
    email_addr = "harry.enten@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 401
    

        

