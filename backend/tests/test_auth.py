from fastapi.testclient import TestClient
import pytest
from models.customer_support_model import CustomerContext
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
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'csr'
    assert customer_context is None


def test_csr_role_domain(client, monkeypatch: pytest.MonkeyPatch):
    # It is only effective in this test
    monkeypatch.setattr(auth_service, "__csr_whitelist", "")
    monkeypatch.setattr(auth_service, "__csr_domains", "threecuptea.com")
    email_addr = "sonya.ling@threecuptea.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'csr'
    assert customer_context is None

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
    auth_resp = data[0]
    assert auth_resp['is_auth'] == False
         

# Type hinting alone does not change a field's requirement status and a default value is still required.
# name: str | None = None: Input Value Can Be None? Yes, Field Can Be Omitted entirely? Yes

def test_auto_refundable_order(client):
    # An order that has been delivered is allowed to return  
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][0]
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
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][1]
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
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][0]
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
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][0]
    item = order['items'][0]
    assert order['status'] == 'delivered'
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) < timedelta(days= threshold_days_auto_approve)
    assert item.get('nonrefundable_item', False) == True

def test_order_delivered_date_borderline(client):
    email_addr = "manu.raju@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][0]
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
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][0]
    assert order['status'] == 'delivered'
    # This is an auto approve return/ refund order
    assert datetime.now(tz= _zoneinfo) - datetime.fromisoformat(order['delivery_date']) > timedelta(days= threshold_days_auto_approve)
    assert datetime.fromisoformat(order['delivery_date']) == datetime.fromisoformat(order['estimated_delivery_date'])

def test_transit_order(client):
    email_addr = "jake.tapper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][0]
    assert order['status'] == 'transit'
    assert datetime.fromisoformat(order['ship_date']) < datetime.now(tz= _zoneinfo) 
    assert datetime.fromisoformat(order['estimated_delivery_date']) > datetime.now(tz = _zoneinfo)
    assert not order['delivery_date'] # an optional field

def test_pending_order(client):
    email_addr = "john.king@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['email_addr'] == email_addr
    assert auth_resp['is_auth'] == True
    assert auth_resp['role'] == 'customer'
    assert customer_context is not None
    order = customer_context['latest_orders'][0]
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
    auth_resp = data[0]
    assert auth_resp['is_auth'] == False

def test_app_state_role_customer_end_to_end(client): 
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    data = resp.json()
    auth_resp = data[0]
    customer_context = data[1]
    assert auth_resp['role'] == 'customer'
    customer_context = CustomerContext.model_validate(customer_context)
    assert customer_context is not None

    # Ensure RoleCheck is functioning correctly and we start general inquiry with a customer role
    resp = client.post(
        "/api/support/general",
        json={"customer_context": customer_context.model_dump(mode="json"), "general_inquiry": "What is your return policy?"},
    )
    assert resp.status_code == 200

    # Ensure RoleCheck is functioning correctly and we start order inquiry/ return for refund with a customer role
    order_id = customer_context.latest_orders[0].order_id
    payload = {"customer_context": customer_context.model_dump(mode="json"), "order_number_provided": order_id}
    resp = client.post(
        "/api/support/order/init",
        json=payload,
    )
    assert resp.status_code == 200

    # Ensure RoleCheck is functioning correctly and we cannot start approval tasks with a customer role
    resp = client.post("/api/approval/start", json={"task": "Write a welcome email"})
    assert resp.status_code == 403


def test_app_state_role_csr_end_to_end(client):
    # An order that has been delivered is allowed to return  
    email_addr = "threecuptea@gmail.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    data = resp.json()
    auth_resp = data[0]
    assert auth_resp['role'] == 'csr'

    # Ensure RoleCheck is functioning correctly and we can start approval tasks with a csr role
    resp = client.post("/api/approval/start", json={"task": "Write a welcome email"})
    assert resp.status_code == 200

    # Ensure RoleCheck is functioning correctly and we cannot start general inquiry with a csr role
    resp = client.post(
        "/api/support/general",
        json={"customer_context": {}, "general_inquiry": "What is your return policy?"},
    )
    assert resp.status_code == 403

    # Ensure RoleCheck is functioning correctly and we cannot start order inquiry/ return for refund with a csr role
    payload = {"customer_context": {}, "order_number_provided": 101}
    resp = client.post(
        "/api/support/order/init",
        json=payload,
    )
    assert resp.status_code == 403


def test_no_session_role_gets_401_not_500(client):
    # Never signed in (or the session cookie expired/was cleared): no role in request.session.
    resp = client.post("/api/approval/start", json={"task": "Write a welcome email"})
    assert resp.status_code == 401
    resp = client.post(
        "/api/support/general",
        json={"customer_context": {}, "general_inquiry": "What is your return policy?"},
    )
    assert resp.status_code == 401


def test_failed_login_grants_no_role(client):
    resp = client.post("/api/auth", json={"email_addr": "nobody@nowhere.example"})
    assert resp.status_code == 200
    assert resp.json()[0]["is_auth"] is False
    # An unknown email must not pass RoleChecker("customer").
    resp = client.post(
        "/api/support/general",
        json={"customer_context": {}, "general_inquiry": "What is your return policy?"},
    )
    assert resp.status_code == 401


def test_failed_login_clears_previous_csr_role(client):
    assert client.post("/api/auth", json={"email_addr": "threecuptea@gmail.com"}).json()[0]["role"] == "csr"
    assert client.post("/api/approval/start", json={"task": "Write a welcome email"}).status_code == 200
    client.post("/api/auth", json={"email_addr": "nobody@nowhere.example"})
    assert client.post("/api/approval/start", json={"task": "Write a welcome email"}).status_code == 401


def test_logout_clears_session_role(client):
    client.post("/api/auth", json={"email_addr": "threecuptea@gmail.com"})
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/approval/start", json={"task": "Write a welcome email"}).status_code == 401


def test_approval_decide_rejects_invalid_action(client):
    client.post("/api/auth", json={"email_addr": "threecuptea@gmail.com"})
    resp = client.post("/api/approval/decide", json={"thread_id": "t", "action": "bogus"})
    assert resp.status_code == 422


# --- Identity binding (services/ownership.py): role alone is not enough ---
def _customer_context(client, email):
    return client.post("/api/auth", json={"email_addr": email}).json()[1]


def test_customer_cannot_use_another_customers_context(client):
    victim_ctx = _customer_context(client, "anderson.cooper@cnn.com")
    other_email = "sonya_ling1947@yahoo.com"
    assert client.post("/api/auth", json={"email_addr": other_email}).json()[0]["is_auth"] is True
    # signed in as sonya, posting anderson's context
    resp = client.post("/api/support/general", json={"customer_context": victim_ctx, "general_inquiry": "hi"})
    assert resp.status_code == 403
    resp = client.post(
        "/api/support/order/init",
        json={"customer_context": victim_ctx, "order_number_provided": victim_ctx["latest_orders"][0]["order_id"]},
    )
    assert resp.status_code == 403


def test_customer_cannot_reuse_another_customers_thread(client):
    ctx = _customer_context(client, "anderson.cooper@cnn.com")
    r = client.post("/api/support/general", json={"customer_context": ctx, "general_inquiry": "What is your return policy?"})
    assert r.status_code == 200
    thread_id = r.json()["thread_id"]

    # a different customer signs in (same browser session cookie is replaced) and targets that thread
    other_ctx = _customer_context(client, "sonya_ling1947@yahoo.com")
    r = client.post("/api/support/general", json={"thread_id": thread_id, "customer_context": other_ctx, "general_inquiry": "hi"})
    assert r.status_code == 403
    assert client.post("/api/support/exit", json={"thread_id": thread_id}).status_code == 403
    assert client.post("/api/support/order/continue", json={"thread_id": thread_id, "user_conversation": "hi"}).status_code == 403

    # the owner can still use it
    client.post("/api/auth", json={"email_addr": "anderson.cooper@cnn.com"})
    r = client.post("/api/support/general", json={"thread_id": thread_id, "customer_context": ctx, "general_inquiry": "Again?"})
    assert r.status_code == 200
