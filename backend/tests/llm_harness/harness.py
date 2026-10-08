"""A tiny harness for measuring how reliably a chat node behaves against a real LLM.

Why it exists: LLM output varies run to run, so one pass/fail says little about a prompt.
A `Case` seeds the state a node reads, sends one customer message, and states what the
reply must/must not contain and which structured fields it must return. `run_case` calls
the node N times and reports a pass *rate*; the pytest wrapper compares it to a threshold.

The runner is deliberately LLM-agnostic: `node` is any `async (state) -> dict`, so the
runner itself is unit-tested offline with a fake node (tests/test_llm_harness.py).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

Node = Callable[[dict], Awaitable[dict]]

# A phrase is either a str (must appear) or a tuple of strs (any one of them must appear).
Phrase = str | tuple[str, ...]


@dataclass
class Case:
    id: str
    description: str
    build_state: Callable[[], dict]          # fresh state per trial (nodes must not share mutable state)
    must_contain: list[Phrase] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    # Expected values of fields in the node's returned dict. A missing key counts as False,
    # because nodes only return e.g. `order_issue_escalated` when they set it.
    expect: dict[str, Any] = field(default_factory=dict)
    threshold: float = 0.8                    # required pass rate over `trials`
    known_issue: str | None = None            # below threshold is reported, not failed


@dataclass
class CaseResult:
    case_id: str
    description: str
    trials: int
    passes: int
    threshold: float
    known_issue: str | None
    failures: list[str]                       # one line per failed trial: why
    samples: list[str]                        # a few raw responses, for eyeballing

    @property
    def rate(self) -> float:
        return self.passes / self.trials if self.trials else 0.0

    @property
    def ok(self) -> bool:
        return self.rate >= self.threshold


def check_output(case: Case, out: dict) -> list[str]:
    """Return the reasons this single output fails the case (empty list = pass)."""
    problems: list[str] = []
    response = str(out.get("response", "")).lower()
    for phrase in case.must_contain:
        options = (phrase,) if isinstance(phrase, str) else phrase
        if not any(opt.lower() in response for opt in options):
            problems.append("missing " + " | ".join(repr(o) for o in options))
    for phrase in case.must_not_contain:
        if phrase.lower() in response:
            problems.append(f"should not contain {phrase!r}")
    for key, expected in case.expect.items():
        actual = out.get(key, False)
        if actual != expected:
            problems.append(f"{key}={actual!r}, expected {expected!r}")
    return problems


async def run_case(node: Node, case: Case, trials: int = 5) -> CaseResult:
    async def one() -> dict:
        return await node(case.build_state())

    outputs = await asyncio.gather(*(one() for _ in range(trials)), return_exceptions=True)
    passes, failures, samples = 0, [], []
    for out in outputs:
        if isinstance(out, BaseException):
            failures.append(f"node raised {type(out).__name__}: {out}")
            continue
        samples.append(str(out.get("response", ""))[:300])
        problems = check_output(case, out)
        if problems:
            failures.append("; ".join(problems))
        else:
            passes += 1
    return CaseResult(case.id, case.description, trials, passes, case.threshold,
                      case.known_issue, failures, samples[:2])


# Filled by the pytest wrapper and printed by tests/conftest.py's terminal-summary hook.
RESULTS: list[CaseResult] = []


def format_report(results: list[CaseResult]) -> str:
    lines = [f"{'case':<8} {'rate':>6}  {'need':>5}  status       description"]
    for r in results:
        if r.ok:
            status = "ok"
        elif r.known_issue:
            status = "KNOWN ISSUE"
        else:
            status = "FAIL"
        lines.append(f"{r.case_id:<8} {r.passes}/{r.trials:<4} {r.threshold:>5.0%}  {status:<12} {r.description}")
        if not r.ok:
            for reason in sorted(set(r.failures)):
                lines.append(f"{'':<8}   - {reason}")
            if r.known_issue:
                lines.append(f"{'':<8}   known issue: {r.known_issue}")
    return "\n".join(lines)
