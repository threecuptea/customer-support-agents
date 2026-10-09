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
    errors: int = 0                           # trials that hit an API/network error even after retries
    error_messages: list[str] = field(default_factory=list)

    @property
    def valid(self) -> int:
        """Trials that actually got an answer from the model (API errors say nothing about the prompt)."""
        return self.trials - self.errors

    @property
    def inconclusive(self) -> bool:
        """Too many API errors to judge the case: more than half the trials never reached the model."""
        return self.valid <= 0 or self.errors * 2 > self.trials

    @property
    def rate(self) -> float:
        return self.passes / self.valid if self.valid > 0 else 0.0

    @property
    def ok(self) -> bool:
        return not self.inconclusive and self.rate >= self.threshold

    @property
    def status(self) -> str:
        if self.inconclusive:
            return "ERROR"
        if self.ok:
            return "ok"
        return "KNOWN ISSUE" if self.known_issue else "FAIL"


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


# Exception class names (anywhere in the MRO) that mean "the API/network misbehaved", not "the prompt failed".
# Matched by name so the harness does not need to import openai/httpx/anthropic.
TRANSIENT_ERROR_NAMES = {
    "APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
    "ServiceUnavailableError", "ConnectError", "ConnectTimeout", "ReadTimeout", "RemoteProtocolError",
}


def is_transient(exc: BaseException) -> bool:
    return any(cls.__name__ in TRANSIENT_ERROR_NAMES for cls in type(exc).__mro__)


async def run_case(node: Node, case: Case, trials: int = 5, concurrency: int | None = None,
                   retries: int = 3, backoff: float = 1.0) -> CaseResult:
    """Call `node` `trials` times and score each answer.

    - At most `concurrency` calls are in flight (LLM_CONCURRENCY, default 4): firing 20 at once opens a burst of
      connections and can trip rate limits; a cap costs the same number of calls.
    - Transient API/network errors are retried `retries` times with exponential backoff; one that still fails
      counts as an *error*, not a prompt failure. If more than half the trials error, the case is inconclusive.
    - Any other exception raised by the node is a real failure of the node and counts as a failed trial.
    """
    if concurrency is None:
        import os
        concurrency = int(os.getenv("LLM_CONCURRENCY", "4"))
    if case.known_issue:
        trials = 20
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one() -> dict:
        async with gate:
            for attempt in range(retries + 1):
                try:
                    return await node(case.build_state())
                except Exception as exc:  # noqa: BLE001 - classified below
                    if is_transient(exc) and attempt < retries:
                        await asyncio.sleep(backoff * (2 ** attempt))
                        continue
                    raise

    outputs = await asyncio.gather(*(one() for _ in range(trials)), return_exceptions=True)
    passes, failures, samples, error_messages = 0, [], [], []
    for out in outputs:
        if isinstance(out, BaseException):
            if is_transient(out):
                error_messages.append(f"{type(out).__name__}: {out}")
            else:
                failures.append(f"node raised {type(out).__name__}: {out}")
            continue
        samples.append(str(out.get("response", ""))[:300])
        problems = check_output(case, out)
        if problems:
            failures.append("; ".join(problems))
        else:
            passes += 1
    return CaseResult(case.id, case.description, trials, passes, case.threshold,
                      case.known_issue, failures, samples[:2], len(error_messages), error_messages)


# Filled by the pytest wrapper and printed by tests/conftest.py's terminal-summary hook.
RESULTS: list[CaseResult] = []

# What the user asked for on the command line (captured by conftest *before* anything imports
# workflow.customer_support, whose `load_dotenv(override=True)` resets LLM_MODEL / LLM_TEMPERATURE
# from .env at import time). None = not given.
REQUESTED_MODEL: str | None = None
REQUESTED_TEMPERATURE: str | None = None
DEFAULT_TEMPERATURE = "0"

# The model/temperature the agent's LLM objects ACTUALLY use, shown in the report header.
RUN_INFO: dict[str, Any] = {}


def effective_llm_settings(llm: Any) -> dict[str, Any]:
    """Read the model name and temperature off a LangChain chat model object."""
    return {
        "model": getattr(llm, "model_name", None) or getattr(llm, "model", None),
        "temperature": getattr(llm, "temperature", None),
    }


def build_agent(model: str | None = None, temperature: str | None = None):
    """Build a CustomerSupportAgent whose LLM really uses the requested model and temperature.

    Importing workflow.customer_support runs load_dotenv(override=True), which clobbers
    LLM_MODEL/LLM_TEMPERATURE from .env, so the environment must be set AFTER that import and
    BEFORE the agent is constructed (get_llm reads the environment at construction). The
    effective values are read back from the model object and checked, so a silently ignored
    override can never again produce results labelled with the wrong model.
    """
    import os

    from workflow.customer_support import CustomerSupportAgent  # triggers load_dotenv(override=True)

    if model:
        # The two chat nodes use CHAT_NODE_MODEL (default gpt-4.1), not LLM_MODEL; the harness exists to
        # test exactly those nodes, so asking for a model on the command line sets both.
        os.environ["LLM_MODEL"] = model
        os.environ["CHAT_NODE_MODEL"] = model
    os.environ["LLM_TEMPERATURE"] = str(temperature if temperature is not None else DEFAULT_TEMPERATURE)
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    info = effective_llm_settings(agent.summarize_llm)
    chat = effective_llm_settings(agent.chat_node_llm)
    info["chat_node_model"] = chat["model"]
    if model:
        for label, actual in (("model", info["model"]), ("chat-node model", chat["model"])):
            if actual and actual != model:
                raise RuntimeError(f"asked for {label} {model!r} but the agent uses {actual!r}")
    wanted_temp = float(os.environ["LLM_TEMPERATURE"])
    if info["temperature"] is not None and float(info["temperature"]) != wanted_temp:
        raise RuntimeError(f"asked for temperature {wanted_temp} but the agent uses {info['temperature']}")
    RUN_INFO.update(info)
    return agent


def format_report(results: list[CaseResult]) -> str:
    lines = []
    if RUN_INFO:
        lines.append(f"chat-node model={RUN_INFO.get('chat_node_model')} (order_continue/return_refund)  "
                     f"other-node model={RUN_INFO.get('model')}  temperature={RUN_INFO.get('temperature')}")
    lines.append(f"{'case':<8} {'rate':<10} {'need':>5}  status       description")
    for r in results:
        shown = f"{r.passes}/{r.valid}"
        if r.errors:
            shown += f" (+{r.errors} err)"
        lines.append(f"{r.case_id:<8} {shown:<10} {r.threshold:>5.0%}  {r.status:<12} {r.description}")
        if r.status in ("FAIL", "KNOWN ISSUE", "ERROR"):
            for reason in sorted(set(r.failures)):
                lines.append(f"{'':<8}   - {reason}")
            for reason in sorted(set(r.error_messages)):
                lines.append(f"{'':<8}   - API error: {reason}")
            if r.status == "KNOWN ISSUE":
                lines.append(f"{'':<8}   known issue: {r.known_issue}")
    return "\n".join(lines)
