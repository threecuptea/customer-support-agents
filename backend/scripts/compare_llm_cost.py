"""Diff two LLM-harness usage summaries: tokens, cost (CSA-26) and latency (CSA-27).

Produce each with the same harness command, before and after a prompt change:
    LLM_MODEL=gpt-4.1-mini LLM_TRIALS=10 LLM_COST_OUT=/path/before.json RUN_LLM_TESTS=1 uv run pytest -m llm -s
or once per model to compare models (LLM_MODEL=gpt-4o-mini ... vs. LLM_MODEL=gpt-4.1-mini ...). Then:
    uv run python scripts/compare_llm_cost.py /path/before.json /path/after.json

Rows are matched by node, so two different models line up; the `model` row shows which model each side used.
Files written before CSA-27 have no latency and show `n/a` there.
"""
from __future__ import annotations

import json
import sys

METRICS = (
    ("avg_input_tokens", ".0f"), ("avg_cache_read", ".0f"), ("cache_hit_rate", ".0%"), ("cached_share", ".0%"),
    ("avg_output_tokens", ".0f"), ("avg_cost_usd", ".6f"),
    ("p50_latency_s", ".2f"), ("p90_latency_s", ".2f"), ("max_latency_s", ".2f"),
)


def _load(path: str) -> dict[str, dict]:
    with open(path) as f:
        data = json.load(f)
    nodes: dict[str, dict] = {}
    for n in data["nodes"]:
        if n["node"] in nodes:
            sys.exit(f"{path}: node {n['node']!r} appears with more than one model; compare files from single-model runs")
        nodes[n["node"]] = n
    return nodes


def _fmt(value: float | None, spec: str) -> str:
    return "n/a" if value is None else format(value, spec)


def _change(before: float | None, after: float | None) -> str:
    if before is None or after is None or before == 0:
        return "n/a"
    return f"{(after - before) / before:+.1%}"


def main(before_path: str, after_path: str) -> None:
    before, after = _load(before_path), _load(after_path)
    print(f"{'node':<26} {'metric':<18} {'before':>24} {'after':>24} {'change':>8}")
    for node in sorted(before.keys() | after.keys()):
        b, a = before.get(node, {}), after.get(node, {})
        print(f"{node:<26} {'model':<18} {str(b.get('model', 'n/a')):>24} {str(a.get('model', 'n/a')):>24}")
        for metric, spec in METRICS:
            bv, av = b.get(metric), a.get(metric)
            print(f"{node:<26} {metric:<18} {_fmt(bv, spec):>24} {_fmt(av, spec):>24} {_change(bv, av):>8}")
        print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
