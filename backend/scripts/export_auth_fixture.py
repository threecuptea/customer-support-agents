"""Regenerate frontend/lib/fixtures/auth-responses.json: the shape of POST /api/auth.

/api/auth returns a 2-element array `[AuthResponse, CustomerContext | null]` (CSA-21).
The frontend unit tests mock `fetch`, so a hand-written mock can silently keep the old
contract after the backend changes. This fixture is built from the real pydantic models
with fixed values, so a model change changes the file, and the freshness test
(tests/test_auth_fixture_freshness.py) fails until it is regenerated; the frontend login
tests consume the file instead of an inline literal.

Run after changing AuthResponse / CustomerContext / Order / OrderItem:
`uv run python -m scripts.export_auth_fixture` (from backend/).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from models.auth_model import AuthResponse
from models.customer_support_model import CustomerContext, Order, OrderItem

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BACKEND_DIR.parent / "frontend" / "lib" / "fixtures" / "auth-responses.json"

# Fixed values only (no "now"), so the output is deterministic.
_DATE = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def build() -> dict:
    context = CustomerContext(
        customer_id=1,
        title="Ms.",
        first_name="Ada",
        last_name="Lovelace",
        email="customer@example.com",
        latest_orders=[
            Order(
                order_id=1001,
                order_date=_DATE,
                total_amount_incl_tax=108.0,
                tax_applied_rate=0.08,
                status="delivered",
                delivery_date=_DATE,
                items=[OrderItem(product_id="P-1", product_name="Widget", supplier_name="Acme", unit_price=50.0, number_units=2)],
            )
        ],
    )
    customer = AuthResponse(email_addr="customer@example.com", is_auth=True, role="customer")
    csr = AuthResponse(email_addr="csr@example.com", is_auth=True, role="csr")
    return {
        "customer": [customer.model_dump(mode="json"), context.model_dump(mode="json")],
        "csr": [csr.model_dump(mode="json"), None],
    }


def render() -> str:
    return json.dumps(build(), indent=2) + "\n"


def main() -> None:
    OUTPUT_PATH.write_text(render())
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
