from collections.abc import Callable
from typing import Literal

from redis.asyncio.client import Redis
from redis.exceptions import WatchError

from models.customer_support_model import RefundRequest

UpdateOutcome = Literal["updated", "not_found", "status_mismatch"]
CAS_MAX_RETRIES = 5


class RefundRequestRedisAdapter:
    def __init__(self, redis_url: str = "redis://localhost:6379"):  
        """Initialize the Redis adapter with a Redis client."""
        self.redis_url = redis_url
        self.redis_client: Redis | None = None

    async def connect(self) -> None:
        """Connect to the Redis server."""
        self.redis_client = await Redis.from_url(self.redis_url, decode_responses=True)

    async def disconnect(self) -> None:
        """Disconnect from the Redis server."""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None

    async def insert_refund_request(self, value: RefundRequest) -> int:
        """Create a new key-value pair in Redis."""
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        # Redis natively supports atomic operations like incr (increment)
        new_value = await self.redis_client.incr('rr')
        value.refund_request_id = new_value  # Assign the new key to the refund request
        await self.redis_client.set(f"rr:{new_value}", value.model_dump_json())
        # add order key pointing to the refund request key. One order can have multiple refund requests.
        await self.redis_client.rpush(f"rr:by_order:{value.returned_order.origin_order_id}", f"rr:{new_value}")
        return new_value  # Return the new key for the retrieval of the refund request later.

    async def retrieve_refund_request(self, refund_request_id: int, csa_only: bool = True) -> RefundRequest | None:    
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        refund_request_json = await self.redis_client.get(f"rr:{refund_request_id}")
        if not refund_request_json:
            return None
        refund_request = RefundRequest.model_validate_json(refund_request_json)
        if csa_only and refund_request.status != "csa":
            return None
        return refund_request

    async def retrieve_refund_requests_by_order(self, origin_order_id: int, csa_only: bool = True)-> list[RefundRequest]:
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        refund_request_keys = await self.redis_client.lrange(f"rr:by_order:{origin_order_id}", 0, -1)
        refund_requests = []
        for refund_request_key in refund_request_keys:
            refund_request_json = await self.redis_client.get(refund_request_key)
            if refund_request_json:
                refund_request = RefundRequest.model_validate_json(refund_request_json)
                if csa_only and refund_request.status != "csa":
                    continue
                refund_requests.append(refund_request)
        return refund_requests

    async def update_refund_request(self, refund_request_id: int, value: RefundRequest) -> None:
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        await self.redis_client.set(f"rr:{refund_request_id}", value.model_dump_json())

    async def update_refund_request_if_status(
        self,
        refund_request_id: int,
        expected_status: str,
        updater: Callable[[RefundRequest], RefundRequest],
    ) -> tuple[UpdateOutcome, RefundRequest | None]:
        """Atomic compare-and-set: apply `updater` only if the stored status is still `expected_status`.

        Uses WATCH/MULTI/EXEC, so if anything else writes the key between our read and our write
        (a double click, a second reviewer, the workflow) Redis aborts the transaction and we re-read
        and re-check instead of silently overwriting. Returns (outcome, request):
          ("updated", the new request) | ("not_found", None) | ("status_mismatch", the current request)
        """
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        key = f"rr:{refund_request_id}"
        for _ in range(CAS_MAX_RETRIES):
            async with self.redis_client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)  # immediate execution while watching
                    if not raw:
                        return "not_found", None
                    current = RefundRequest.model_validate_json(raw)
                    if current.status != expected_status:
                        return "status_mismatch", current
                    updated = updater(current)
                    pipe.multi()
                    pipe.set(key, updated.model_dump_json())
                    await pipe.execute()
                    return "updated", updated
                except WatchError:
                    continue  # someone else wrote the key; re-read and re-check the status
        raise RuntimeError(f"Could not update refund request {refund_request_id}: too much write contention")