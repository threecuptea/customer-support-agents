
from __future__ import annotations
from fastapi.responses import StreamingResponse
import json


def parse_interrupt_info(result) -> tuple[bool, str | None]:
    """Extract interrupt status and message from an ainvoke result."""
    if isinstance(result, dict) and result.get("__interrupt__"):
        return True, result.get("__interrupt__")[0].value
    return False, None


def sse_wrapper(generator) -> StreamingResponse:
    async def body():
        async for chunk in generator:
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
