"""Offline tests of the harness itself (fake nodes, no LLM): the default suite runs these."""
import asyncio

from tests.llm_harness.cases import ORDER_CONTINUE_CASES, RETURN_REFUND_CASES, REVISIT_CASES
from tests.llm_harness import harness
from tests.llm_harness.harness import Case, check_output, effective_llm_settings, format_report, run_case


def make_case(**kwargs) -> Case:
    return Case(id="T-1", description="t", build_state=lambda: {}, **kwargs)


def test_must_contain_is_case_insensitive_and_supports_any_of():
    case = make_case(must_contain=["email", ("alpha", "beta")])
    assert check_output(case, {"response": "Check your EMAIL. Beta!"}) == []
    assert check_output(case, {"response": "Check your email."}) == ["missing 'alpha' | 'beta'"]


def test_must_not_contain():
    case = make_case(must_not_contain=["human review"])
    assert check_output(case, {"response": "A Human Review is possible"}) == ["should not contain 'human review'"]


def test_expect_treats_missing_key_as_false():
    case = make_case(expect={"order_issue_escalated": False})
    assert check_output(case, {"response": "x"}) == []
    assert check_output(case, {"response": "x", "order_issue_escalated": True}) == [
        "order_issue_escalated=True, expected False"]
    escalate = make_case(expect={"order_issue_escalated": True})
    assert check_output(escalate, {"response": "x"}) == ["order_issue_escalated=False, expected True"]


def test_run_case_counts_pass_rate_and_exceptions():
    calls = {"n": 0}

    async def flaky(state):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("boom")
        return {"response": "good" if calls["n"] % 2 else "bad"}

    result = asyncio.run(run_case(flaky, make_case(must_contain=["good"], threshold=0.5), trials=4))
    assert result.trials == 4
    assert result.passes == 2           # calls 1 and 3
    assert any("RuntimeError" in f for f in result.failures)
    assert result.ok                    # 50% >= 50%


def test_each_trial_gets_a_fresh_state():
    seen = []

    async def node(state):
        seen.append(id(state))
        return {"response": "ok"}

    case = Case(id="T", description="t", build_state=dict)
    asyncio.run(run_case(node, case, trials=3))
    assert len(set(seen)) == 3


def test_report_marks_known_issue_and_failure():
    async def bad(state):
        return {"response": "nope"}

    known = Case(id="K", description="k", build_state=dict, must_contain=["yes"], known_issue="flaky")
    hard = Case(id="H", description="h", build_state=dict, must_contain=["yes"])
    results = [asyncio.run(run_case(bad, known, 2)), asyncio.run(run_case(bad, hard, 2))]
    report = format_report(results)
    assert "KNOWN ISSUE" in report and "FAIL" in report and "missing 'yes'" in report


def test_case_tables_build_valid_state():
    ids = [c.id for c in RETURN_REFUND_CASES + ORDER_CONTINUE_CASES + REVISIT_CASES]
    assert len(ids) == len(set(ids))
    for case in RETURN_REFUND_CASES + ORDER_CONTINUE_CASES + REVISIT_CASES:
        state = case.build_state()
        assert state["messages"] and state["order_number_provided"]
        assert case.build_state() is not state


def test_effective_llm_settings_reads_model_and_temperature():
    class Fake:
        model_name = "gpt-4.1"
        temperature = 0.0

    class FakeOther:  # some providers expose `model` instead of `model_name`
        model = "claude-x"

    assert effective_llm_settings(Fake()) == {"model": "gpt-4.1", "temperature": 0.0}
    assert effective_llm_settings(FakeOther()) == {"model": "claude-x", "temperature": None}
    assert effective_llm_settings(object()) == {"model": None, "temperature": None}


def test_report_header_shows_model_and_temperature():
    old = dict(harness.RUN_INFO)
    harness.RUN_INFO.update({"model": "gpt-4o-mini", "chat_node_model": "gpt-4.1", "temperature": 0.0})
    try:
        assert format_report([]).splitlines()[0] == (
            "chat-node model=gpt-4.1 (order_continue/return_refund)  other-node model=gpt-4o-mini  temperature=0.0")
    finally:
        harness.RUN_INFO.clear()
        harness.RUN_INFO.update(old)


# ---- concurrency cap, retries, and API errors vs failures --------------------------------------
class APIConnectionError(Exception):
    """Stand-in for openai.APIConnectionError (the harness matches transient errors by class name)."""


def _case(**kw) -> Case:
    return Case(id="T", description="t", build_state=dict, **kw)


def test_concurrency_is_capped():
    state = {"now": 0, "peak": 0}

    async def node(_):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return {"response": "ok"}

    asyncio.run(run_case(node, _case(), trials=12, concurrency=3))
    assert state["peak"] == 3


def test_transient_error_is_retried_then_succeeds():
    calls = {"n": 0}

    async def node(_):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise APIConnectionError("Connection error.")
        return {"response": "ok"}

    result = asyncio.run(run_case(node, _case(), trials=1, retries=3, backoff=0))
    assert (result.passes, result.errors, calls["n"]) == (1, 0, 3)


def test_exhausted_transient_errors_are_errors_not_failures_and_make_the_case_inconclusive():
    async def node(_):
        raise APIConnectionError("Connection error.")

    result = asyncio.run(run_case(node, _case(must_contain=["x"]), trials=4, retries=1, backoff=0))
    assert result.errors == 4 and result.failures == []
    assert result.inconclusive and not result.ok and result.status == "ERROR"
    report = format_report([result])
    assert "ERROR" in report and "(+4 err)" in report and "API error: APIConnectionError" in report


def test_a_few_errors_do_not_hide_the_verdict():
    calls = {"n": 0}

    async def node(_):
        calls["n"] += 1
        if calls["n"] == 1:
            raise APIConnectionError("blip")
        return {"response": "good"}

    result = asyncio.run(run_case(node, _case(must_contain=["good"]), trials=5, retries=0, backoff=0, concurrency=1))
    assert (result.errors, result.valid, result.passes) == (1, 4, 4)
    assert result.rate == 1.0 and result.status == "ok"


def test_non_transient_exception_is_a_failure_not_an_error_and_is_not_retried():
    calls = {"n": 0}

    async def node(_):
        calls["n"] += 1
        raise KeyError("target_order")

    result = asyncio.run(run_case(node, _case(), trials=2, retries=3, backoff=0))
    assert calls["n"] == 2                   # no retries for a real node bug
    assert result.errors == 0 and len(result.failures) == 2 and result.status == "FAIL"


def test_known_issue_cases_run_twenty_trials():
    async def node(_):
        return {"response": "ok"}

    result = asyncio.run(run_case(node, _case(known_issue="x"), trials=5))
    assert result.trials == 20
