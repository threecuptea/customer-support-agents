from dataclasses import dataclass, field

@dataclass
class ReviewResponse:
    refund_request_id: int # We don't have any more than refund_request_id from the Slack payload.  We can retrieve the rest from Redis
    response_url: str
    action: str
    reason: str = ""
    decided_by: str = ""
    decided_ts: float = 0.0# datetime.fromtimestamp(float(decided_ts), tz=ZoneInfo("UTC")) if decided_ts else None need the time zone from original delivery date