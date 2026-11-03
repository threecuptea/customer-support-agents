from redis.asyncio.client import Redis
from models.customer_support_model import RefundRequest


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

    async def retrieve_refund_request(self, refund_request_id: int) -> RefundRequest | None:    
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        refund_request_json = await self.redis_client.get(f"rr:{refund_request_id}")
        if not refund_request_json:
            return None
        return RefundRequest.model_validate_json(refund_request_json)

    async def retrieve_refund_requests_by_order(self, origin_order_id: int) -> list[RefundRequest]:
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        refund_request_keys = await self.redis_client.lrange(f"rr:by_order:{origin_order_id}", 0, -1)
        refund_requests = []
        for refund_request_key in refund_request_keys:
            refund_request_json = await self.redis_client.get(refund_request_key)
            if refund_request_json:
                refund_requests.append(RefundRequest.model_validate_json(refund_request_json))
        return refund_requests

    async def update_refund_request(self, refund_request_id: int, value: RefundRequest) -> None:
        if not self.redis_client:
            raise RuntimeError("Redis client is not connected.")
        await self.redis_client.set(f"rr:{refund_request_id}", value.model_dump_json())