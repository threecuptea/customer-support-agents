"""CSA-30: summarize_node runs in the background, after the response is returned.

These tests use a plain TestClient (not SummaryDrainingTestClient) so they can observe the background task.
The checkpoint is read on the app's own event loop (`client.portal.call`), so a read never races the task's sqlite
connection from a second loop."""
import asyncio
import logging
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from main import app
from models.customer_support_model import CustomerContext
from services.background_summaries import BackgroundSummaries
from tests.background import drain_summaries
from workflow.customer_support import CustomerSupportAgent

RESOLVED_BY_FUZZY_MATCH = "What is your return policy?"  # general_issue_resolved -> mark_summarize_due_node
SUMMARY_TEXT = "The customer asked about the return policy."


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        resp = test_client.post("/api/auth", json={"email_addr": "anderson.cooper@cnn.com"})
        yield test_client, CustomerContext(**resp.json()[1])


class _FakeSummarizeLLM:
    """Records calls; optionally waits for `gate` (an asyncio.Event set on the app's loop) or raises."""

    def __init__(self, gate: asyncio.Event | None = None, fail: bool = False):
        self.gate, self.fail = gate, fail
        self.calls = 0
        self.finished = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("summary LLM down")
        self.finished += 1
        return AIMessage(content=SUMMARY_TEXT)


@pytest.fixture()
def install_summarize_llm(client, monkeypatch):
    test_client, _ = client
    agent = test_client.app.state.support_graph.nodes["summarize_node"].bound.afunc.__self__

    installed: list[_FakeSummarizeLLM] = []

    def install(fake: _FakeSummarizeLLM) -> _FakeSummarizeLLM:
        monkeypatch.setattr(agent, "summarize_llm", fake)
        installed.append(fake)
        return fake

    yield install
    for fake in installed:  # a failed assertion must not leave a task waiting on its gate
        if fake.gate is not None:
            _open(test_client, fake.gate)
    drain_summaries(test_client)  # never leave a task behind for the next test


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def _ask(test_client, customer_context, inquiry=RESOLVED_BY_FUZZY_MATCH, thread_id=None):
    body = {"customer_context": customer_context.model_dump(mode="json"), "general_inquiry": inquiry}
    if thread_id:
        body["thread_id"] = thread_id
    resp = test_client.post("/api/support/general", json=body)
    assert resp.status_code == 200
    return resp.json()


def _state(test_client, thread_id) -> dict:
    graph = test_client.app.state.support_graph
    return test_client.portal.call(graph.aget_state, {"configurable": {"thread_id": thread_id}}).values


def _new_gate(test_client) -> asyncio.Event:
    async def make():
        return asyncio.Event()
    return test_client.portal.call(make)


def _open(test_client, gate: asyncio.Event) -> None:
    async def set_gate():  # asyncio.Event is not thread-safe: set it on the app's loop
        gate.set()
    test_client.portal.call(set_gate)


def test_response_returns_before_the_background_summary(client, install_summarize_llm):
    test_client, customer_context = client
    fake = install_summarize_llm(_FakeSummarizeLLM())

    data = _ask(test_client, customer_context)

    # The customer has the answer while the summary is still waiting on its LLM.
    assert "We accept returns within 35 days" in data["response"]
    assert test_client.app.state.summaries.pending == 1
    # The above two assertions has ensured that the response is returned before the background summary completes without inserting artificial gate delays.
    _wait_for(lambda: fake.calls == 1)  # the background task reached the summary LLM ...
    assert fake.finished == 1           # ... which is still running
    
    values = _state(test_client, data["thread_id"])
    assert values["summary"] == SUMMARY_TEXT
    assert values["summarize_due"] is False
    assert values["last_summarized_message_id"] == values["messages"][-1].id


def test_next_request_on_the_thread_waits_for_the_summary(client, install_summarize_llm):
    test_client, customer_context = client
    gate = _new_gate(test_client)
    fake = install_summarize_llm(_FakeSummarizeLLM(gate=gate))
    thread_id = _ask(test_client, customer_context)["thread_id"]

    second: dict = {}
    worker = threading.Thread(target=lambda: second.update(
        _ask(test_client, customer_context, "How long does delivery take?", thread_id)))
    worker.start()
    time.sleep(0.3)
    assert worker.is_alive(), "the second request must wait on the thread's lock while the summary runs"
    assert test_client.app.state.summaries.pending == 1
    assert second == {} # the second request has not yet executed and is blocked by the summary task

    # Another customer's thread is not blocked by this thread's lock.
    other = _ask(test_client, customer_context, "How long does delivery take?")
    assert other["thread_id"] != thread_id

    _open(test_client, gate)
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert "takes 3 to 5 business days" in second["response"]
    drain_summaries(test_client)
    assert fake.finished == fake.calls == 3 # every summary (first thread twice, other thread once) completed

# caplog is a built-in pytest fixture that captures messages emitted through Python’s standard logging module so that
# we can inspect and assert on them in our tests
def test_failing_summary_is_logged_and_next_turn_routes_normally(client, install_summarize_llm, caplog):
    test_client, customer_context = client
    install_summarize_llm(_FakeSummarizeLLM(fail=True))

    with caplog.at_level(logging.ERROR, logger="services.customer_support_service"):
        data = _ask(test_client, customer_context)
        drain_summaries(test_client)
    assert "We accept returns within 35 days" in data["response"]
    assert any("Background summary failed" in r.getMessage() for r in caplog.records) # the log come from BackgroundSummary.drain
    # The failed run left summarize_due=True in the checkpoint ...
    assert _state(test_client, data["thread_id"])["summarize_due"] is True

    # ... but the next request resets it in its input, so it is answered instead of routed into summarize_node (risk 1).
    fake = install_summarize_llm(_FakeSummarizeLLM())
    data2 = _ask(test_client, customer_context, "How long does delivery take?", data["thread_id"])
    assert "takes 3 to 5 business days" in data2["response"]
    drain_summaries(test_client)
    values = _state(test_client, data["thread_id"])
    assert fake.finished == 1  # the retry summarizes everything since the last successful summary
    assert values["summary"] == SUMMARY_TEXT
    assert values["summarize_due"] is False


def test_exit_right_after_a_background_summary_skips_the_llm(client, install_summarize_llm):
    test_client, customer_context = client
    fake = install_summarize_llm(_FakeSummarizeLLM())
    thread_id = _ask(test_client, customer_context)["thread_id"]
    drain_summaries(test_client)
    assert fake.calls == 1

    resp = test_client.post("/api/support/exit", json={"thread_id": thread_id})
    assert resp.status_code == 200
    assert fake.calls == 1, "nothing new since the background summary: Exit must not call the LLM again"
    values = _state(test_client, thread_id)
    assert values["summarize_on_exit"] is False and values["summarize_due"] is False
    assert test_client.app.state.summaries.pending == 0  # Exit never schedules a background summary


def test_exit_while_the_summary_runs_waits_for_it(client, install_summarize_llm):
    test_client, customer_context = client
    gate = _new_gate(test_client)
    fake = install_summarize_llm(_FakeSummarizeLLM(gate=gate))
    thread_id = _ask(test_client, customer_context)["thread_id"]

    result: dict = {}
    worker = threading.Thread(target=lambda: result.update(
        status=test_client.post("/api/support/exit", json={"thread_id": thread_id}).status_code))
    worker.start()
    time.sleep(0.3)
    assert worker.is_alive()
    assert test_client.app.state.summaries.pending == 1
    assert result== {} # the 'execute' request has not yet executed and is blocked by the summary task
    
    _open(test_client, gate)
    worker.join(timeout=10)
    assert result["status"] == 200
    assert fake.calls == 1  # Exit found the summary already done


def test_shutdown_drains_pending_summaries(install_summarize_llm_shutdown):
    fake = install_summarize_llm_shutdown
    assert fake.finished == 1


@pytest.fixture()
def install_summarize_llm_shutdown():
    """Its own app lifespan: start a slow summary, then leave the TestClient (shutdown) without draining."""

    class _Slow(_FakeSummarizeLLM):
        async def ainvoke(self, messages):
            await asyncio.sleep(0.3)
            return await super().ainvoke(messages)

    fake = _Slow()
    with TestClient(app) as test_client:
        resp = test_client.post("/api/auth", json={"email_addr": "anderson.cooper@cnn.com"})
        agent = test_client.app.state.support_graph.nodes["summarize_node"].bound.afunc.__self__
        agent.summarize_llm = fake  # a fresh agent per lifespan, so no monkeypatch restore is needed
        _ask(test_client, CustomerContext(**resp.json()[1]))
        assert test_client.app.state.summaries.pending == 1
    return fake


# --- Units -------------------------------------------------------------------------------------------------------

def test_thread_lock_serializes_a_thread_and_cleans_up():
    async def scenario():
        summaries = BackgroundSummaries()
        order = []

        async def hold(thread_id, name, delay):
            async with summaries.thread_lock(thread_id):
                order.append(f"{name}-in")
                await asyncio.sleep(delay)
                order.append(f"{name}-out")

        await asyncio.gather(hold("t1", "a", 0.05), hold("t1", "b", 0), hold("t2", "c", 0))
        return summaries, order

    summaries, order = asyncio.run(scenario())
    assert order.index("a-out") < order.index("b-in")  # same thread: one after the other
    assert order.index("c-in") < order.index("a-out")  # other thread: not blocked
    assert summaries._locks == {}  # no lock left behind


def test_drain_waits_for_scheduled_tasks():
    async def scenario():
        summaries = BackgroundSummaries()
        done = []

        async def work():
            await asyncio.sleep(0.05)
            done.append(True)

        summaries.schedule(work())
        assert summaries.pending == 1
        await summaries.drain(timeout=5)
        return summaries, done

    summaries, done = asyncio.run(scenario())
    assert done == [True] and summaries.pending == 0


def test_route_branch_summarize_due_goes_to_summarize_node():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    assert agent.route_branch({"summarize_due": True, "support_category": "general_others"}) == "summarize_node"
    assert agent.route_branch({"summarize_due": False, "support_category": "general_others"}) == "general_faq"


def test_mark_summarize_due_node_only_sets_the_flag():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    assert asyncio.run(agent.mark_summarize_due_node({})) == {"summarize_due": True}


def test_summarize_node_skips_when_nothing_new(test_customer_context):
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    fake = _FakeSummarizeLLM()
    agent.summarize_llm = fake
    state = {
        "messages": [HumanMessage(content="q", id="1"), AIMessage(content="a", id="2")],
        "customer_context": test_customer_context,
        "last_summarized_message_id": "2",
        "summarize_on_exit": True,
    }
    result = asyncio.run(agent.summarize_node(state, config={"configurable": {"thread_id": str(uuid.uuid4())}}))
    assert result == {"summarize_due": False, "summarize_on_exit": False}
    assert fake.calls == 0


@pytest.fixture()
def test_customer_context():
    from models.demo_data import get_demo_customer
    return CustomerContext(**get_demo_customer("anderson.cooper@cnn.com"))
