"""Diff two LLM-harness usage summaries (CSA-26).

Produce each with the same harness command, before and after a prompt change:
    LLM_MODEL=gpt-4.1-mini LLM_TRIALS=10 LLM_COST_OUT=/path/before.json RUN_LLM_TESTS=1 uv run pytest -m llm -s
Then:
    uv run python scripts/compare_llm_cost.py /path/before.json /path/after.json
"""
from __future__ import annotations

import json
import sys


def _load(path: str) -> dict[tuple[str, str], dict]:
    with open(path) as f:
        data = json.load(f)
    return {(n["node"], n["model"]): n for n in data["nodes"]}


def _fmt(value: float | None, spec: str) -> str:
    return "n/a" if value is None else format(value, spec)


def _change(before: float | None, after: float | None) -> str:
    if before is None or after is None or before == 0:
        return "n/a"
    return f"{(after - before) / before:+.1%}"


def main(before_path: str, after_path: str) -> None:
    before, after = _load(before_path), _load(after_path)
    print(f"{'node':<26} {'model':<22} {'metric':<16} {'before':>10} {'after':>10} {'change':>8}")
    for key in sorted(before.keys() | after.keys()):
        b, a = before.get(key, {}), after.get(key, {})
        node, model = key
        for metric, spec in (("avg_input_tokens", ".0f"), ("avg_cache_read", ".0f"), ("cache_hit_rate", ".0%"),
                             ("cached_share", ".0%"), ("avg_output_tokens", ".0f"), ("avg_cost_usd", ".6f")):
            bv, av = b.get(metric), a.get(metric)
            print(f"{node:<26} {model:<22} {metric:<16} {_fmt(bv, spec):>10} {_fmt(av, spec):>10} {_change(bv, av):>8}")
        print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
