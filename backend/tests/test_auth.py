from fastapi.testclient import TestClient
import pytest
from main import app
import services.auth_service as auth_service
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import os

load_dotenv(override=True)

threshold_days_auto_approve = int(os.getenv("DAYS_THRESHOLD_AUTO"))
threshold_amount_auto_approve = float(os.getenv("AMOUNT_THRESHOLD_AUTO"))

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
    assert resp.status_code == 200
    data = resp.json()
    assert data['is_auth'] == False
         

# Type hinting alone does not change a field's requirement status and a default value is still required.
# name: str | None = None: Input Value Can Be None? Yes, Field Can Be Omitted entirely? Yes

def test_auto_refundable_order(client):
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
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) < timedelta(days= threshold_days_auto_approve)
    assert datetime.fromisoformat(order['delivery_date']) == datetime.fromisoformat(order['estimated_delivery_date'])

def test_auto_refundable_order_test(client):
    # An order that has been delivered is allowed to return  
    email_addr = "sonya_ling1947@yahoo.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][1]
    assert order['status'] == 'delivered'
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) < timedelta(days= threshold_days_auto_approve)
    assert datetime.fromisoformat(order['delivery_date']) == datetime.fromisoformat(order['estimated_delivery_date'])


def test_human_refundable_order_amount(client):
    # An order that has been delivered is allowed to return  
    email_addr = "pamela.brown@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][0]
    assert order['status'] == 'delivered'
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) < timedelta(days= threshold_days_auto_approve)
    assert float(order["total_amount_incl_tax"]) / (1 + float(order["tax_applied_rate"])) > threshold_amount_auto_approve

def test_human_refundable_order_due_to_item(client):
    # An order that has been delivered is allowed to return  
    email_addr = "dana.bash@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][0]
    item = order['items'][0]
    assert order['status'] == 'delivered'
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) < timedelta(days= threshold_days_auto_approve)
    assert item.get('intimate_item', False) == True

def test_order_delivered_date_borderline(client):
    email_addr = "manu.raju@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][0]
    assert order['status'] == 'delivered'
    assert order['delivery_date'] is not None
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) < timedelta(days= 3)
   
def test_non_refundable_order_exceeding_return_window(client):
    # An order that has been delivered is allowed to return  
    email_addr = "wolf.blitzer@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][0]
    assert order['status'] == 'delivered'
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) > timedelta(days= threshold_days_auto_approve)
    assert datetime.fromisoformat(order['delivery_date']) == datetime.fromisoformat(order['estimated_delivery_date'])

def test_transit_order(client):
    email_addr = "jake.tapper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    assert data['email_addr'] == email_addr
    assert data['is_auth'] == True
    assert data['role'] == 'customer'
    assert data['customer_context'] is not None
    order = data['customer_context']['latest_orders'][0]
    assert order['status'] == 'transit'
    assert datetime.fromisoformat(order['ship_date']) < datetime.now(tz= _zoneinfo) 
    assert datetime.fromisoformat(order['estimated_delivery_date']) > datetime.now(tz = _zoneinfo)
    assert not order['delivery_date'] # an optional field

def test_pending_order(client):
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
    assert order['notes'] # with backorder info
    assert not order['ship_date'] # an optional field
    assert not order['estimated_delivery_date'] # an optional 
    assert not order['delivery_date'] # an optional field

def test_order_missing_required(client):
    # An order that is missing required fields
    email_addr = "harry.enten@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    # missing order date
    assert resp.status_code == 200
    data = resp.json()
    assert data['is_auth'] == False
        
    