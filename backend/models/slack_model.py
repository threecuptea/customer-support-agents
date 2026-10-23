from dataclasses import dataclass, field

@dataclass
class ReviewResponse:
    refund_request_id: int
    origin_order_id: int
    estimated_amount_refund_incl_tax: float
    customer_name: str
    action: str
    reason: str = ""
    decided_by: str = ""
    decided_ts: float # datetime.fromtimestamp(float(decided_ts), tz=ZoneInfo("UTC")) if decided_ts else None need the time zone from original delivery date
    # Refine it later.  timestamp might need a timezone