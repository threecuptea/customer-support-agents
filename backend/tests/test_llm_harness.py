"""Offline tests of the harness itself (fake nodes, no LLM): the default suite runs these."""
import asyncio

from tests.llm_harness.cases import ORDER_CONTINUE_CASES, RETURN_REFUND_CASES
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
    ids = [c.id for c in RETURN_REFUND_CASES + ORDER_CONTINUE_CASES]
    assert len(ids) == len(set(ids))
    for case in RETURN_REFUND_CASES + ORDER_CONTINUE_CASES:
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
    harness.RUN_INFO.update({"model": "gpt-4.1", "temperature": 0.0})
    try:
        assert format_report([]).splitlines()[0] == "model=gpt-4.1  temperature=0.0"
    finally:
        harness.RUN_INFO.clear()
        harness.RUN_INFO.update(old)
