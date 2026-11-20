"""Token usage and cost of the chat nodes' LLM calls during a harness run (CSA-26).

Why: prompt caching only pays off if the static prompt prefix is long enough (>= 1,024 tokens for OpenAI) AND stays
byte-identical across calls. The recorder wraps the agent's structured-output LLMs, so every harness call records
`input_tokens`, `cache_read` and `output_tokens` from `result["raw"].usage_metadata` without touching node code.
A run with `LLM_COST_OUT=path.json` writes a per-node summary that `scripts/compare_llm_cost.py` diffs, so the
same harness command measured before and after a prompt change gives the cost/ cache effect of that change.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# USD per 1M tokens: (input, cached input, output). Verify against https://openai.com/api/pricing when it matters.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4o": (2.50, 1.25, 10.00),
}


def price_for(model: str | None) -> tuple[float, float, float] | None:
    """Longest matching key wins, so a dated snapshot (gpt-4.1-mini-2025-04-14) finds its base model."""
    if not model:
        return None
    matches = [key for key in PRICES if model.startswith(key)]
    return PRICES[max(matches, key=len)] if matches else None


@dataclass
class Call:
    node: str
    model: str | None
    input_tokens: int
    cache_read: int
    output_tokens: int

    @property
    def cost(self) -> float | None:
        price = price_for(self.model)
        if price is None:
            return None
        p_in, p_cached, p_out = price
        uncached = self.input_tokens - self.cache_read  # input_tokens includes the cached ones
        return (uncached * p_in + self.cache_read * p_cached + self.output_tokens * p_out) / 1_000_000


@dataclass
class NodeSummary:
    node: str
    model: str | None
    calls: int
    avg_input_tokens: float
    avg_cache_read: float
    cache_hit_rate: float          # share of calls with cache_read > 0
    cached_share: float            # cached input tokens / all input tokens
    avg_output_tokens: float
    avg_cost_usd: float | None
    total_cost_usd: float | None


@dataclass
class UsageLog:
    calls: list[Call] = field(default_factory=list)

    def summaries(self) -> list[NodeSummary]:
        groups: dict[tuple[str, str | None], list[Call]] = {}
        for call in self.calls:
            groups.setdefault((call.node, call.model), []).append(call)
        result = []
        for (node, model), calls in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
            n = len(calls)
            total_in = sum(c.input_tokens for c in calls)
            costs = [c.cost for c in calls]
            total_cost = None if any(c is None for c in costs) else sum(costs)
            result.append(NodeSummary(
                node=node, model=model, calls=n,
                avg_input_tokens=total_in / n,
                avg_cache_read=sum(c.cache_read for c in calls) / n,
                cache_hit_rate=sum(1 for c in calls if c.cache_read > 0) / n,
                cached_share=(sum(c.cache_read for c in calls) / total_in) if total_in else 0.0,
                avg_output_tokens=sum(c.output_tokens for c in calls) / n,
                avg_cost_usd=None if total_cost is None else total_cost / n,
                total_cost_usd=total_cost,
            ))
        return result

    def write_json(self, path: str, run_info: dict[str, Any]) -> None:
        payload = {"run_info": run_info, "nodes": [asdict(s) for s in self.summaries()]}
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    def format_report(self) -> str:
        lines = [f"{'node':<26} {'model':<14} {'calls':>5} {'avg in':>8} {'avg cached':>10} {'hit rate':>8} "
                 f"{'cached %':>8} {'avg out':>7} {'$/call':>10} {'$ total':>9}"]
        for s in self.summaries():
            per_call = f"{s.avg_cost_usd:.6f}" if s.avg_cost_usd is not None else "n/a"
            total = f"{s.total_cost_usd:.4f}" if s.total_cost_usd is not None else "n/a"
            lines.append(f"{s.node:<26} {str(s.model):<14} {s.calls:>5} {s.avg_input_tokens:>8.0f} {s.avg_cache_read:>10.0f} "
                         f"{s.cache_hit_rate:>8.0%} {s.cached_share:>8.0%} {s.avg_output_tokens:>7.0f} {per_call:>10} {total:>9}")
        return "\n".join(lines)


# Filled by every recorded call of the run; printed/ written by tests/conftest.py's terminal-summary hook.
USAGE = UsageLog()


def usage_of(raw: Any) -> tuple[int, int, int]:
    """(input_tokens, cache_read, output_tokens) from an AIMessage's usage_metadata (zeros when absent)."""
    meta = getattr(raw, "usage_metadata", None) or {}
    details = meta.get("input_token_details") or {}
    return int(meta.get("input_tokens", 0)), int(details.get("cache_read", 0) or 0), int(meta.get("output_tokens", 0))


class UsageRecorder:
    """Wraps a `with_structured_output(..., include_raw=True)` runnable; records usage of each `ainvoke`."""

    def __init__(self, inner: Any, node: str, model: str | None, log: UsageLog = USAGE):
        self.inner, self.node, self.model, self.log = inner, node, model, log

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        result = await self.inner.ainvoke(*args, **kwargs)
        raw = result.get("raw") if isinstance(result, dict) else None
        if raw is not None:
            # The response names the model actually served (e.g. a dated snapshot); fall back to the configured one.
            served = (getattr(raw, "response_metadata", None) or {}).get("model_name") or self.model
            self.log.calls.append(Call(self.node, served, *usage_of(raw)))
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
