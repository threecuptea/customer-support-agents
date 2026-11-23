"""CSA-25: `_ainvoke_graph` adds LangFuse tracing only when `app.state.langfuse` is set, never flushes per request,
and does not leak the per-request callback into the caller's config."""
import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ChatMessage, HumanMessage
from langfuse.langchain import CallbackHandler

import services.customer_support_service as svc
from services.background_summaries import BackgroundSummaries
from models.customer_support_model import OrderStructuredOutput
from tests.llm_harness.cases import build_order_continue_state
from workflow.customer_support import CustomerSupportAgent


class _FakeGraph:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, graph_input, config):
        self.calls.append((graph_input, config))
        return {"response": "ok"}


class _FakeLangfuse:
    def __init__(self):
        self.flushed = 0

    def flush(self):
        self.flushed += 1


def _request(langfuse):
    graph = _FakeGraph()
    state = SimpleNamespace(support_graph=graph, langfuse=langfuse, summaries=BackgroundSummaries())
    # CSA-25, it will return app.state.support_graph with _FakeGraph instance and app.state.langfuse with the provided langfuse instance.
    # CSA-30: app.state.summaries holds the background summaries instance. I also return request.session of email attribute.
    return SimpleNamespace(app=SimpleNamespace(state=state), session={"email": "a@b.com"}), graph


def test_ainvoke_graph_without_langfuse_passes_config_through():
    request, graph = _request(None)
    config = {"configurable": {"thread_id": "t1"}}
    result = asyncio.run(svc._ainvoke_graph(request, {"x": 1}, config, run_name="r", tags=["t"], invoke_from="f"))
    assert result == {"response": "ok"}
    # CSA-30: a request flow's input always resets both summary flags
    assert graph.calls == [({"x": 1, "summarize_due": False, "summarize_on_exit": False}, {"configurable": {"thread_id": "t1"}})]


def test_ainvoke_graph_with_langfuse_adds_callback_and_attributes(monkeypatch):
    seen = {}

    class _Propagate:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(svc, "propagate_attributes", _Propagate)
    langfuse = _FakeLangfuse()
    request, graph = _request(langfuse)
    config = {"configurable": {"thread_id": "t1"}}

    asyncio.run(svc._ainvoke_graph(request, {"x": 1}, config, run_name="order_inquery",
                                   tags=["order_inquery", "chat"], invoke_from="order_continue"))

    _, used_config = graph.calls[0]
    assert used_config["run_name"] == "order_inquery"
    assert len(used_config["callbacks"]) == 1 and isinstance(used_config["callbacks"][0], CallbackHandler)
    assert seen == {
        "trace_name": svc.LANGFUSE_CSA_TRACE_NAME, "user_id": "a@b.com", "session_id": "t1",
        "tags": ["order_inquery", "chat"],
        "metadata": {"graph": "customer_support", "invoke_from": "order_continue"},
    }
    # The caller's config is untouched, and nothing blocks the request on a flush.
    assert config == {"configurable": {"thread_id": "t1"}}
    assert langfuse.flushed == 0


def test_order_continue_chat_sends_latest_human_message_even_if_not_last():
    """The latest customer message is found by type: a trailing non-human message must not be sent in its place."""
    sent = []

    class FakeLLM:
        async def ainvoke(self, messages):
            sent.append(messages)
            return {"parsed": OrderStructuredOutput(response="hi")}

    agent = CustomerSupportAgent(checkpointer=None, store=None)
    agent.order_llm_for_inquiry_chat = FakeLLM()
    state = build_order_continue_state(status="delivered", revisit=False, question="where is my receipt?")
    state["messages"] = [*state["messages"], ChatMessage(content="function note", role="function"),
                         AIMessage(content="agent note")]

    asyncio.run(agent.order_continue_chat_node(state))

    static_msg, system_msg, human_msg = sent[0]  # static (cacheable) prefix, per-call context, latest message (CSA-26)
    assert isinstance(human_msg, HumanMessage) and human_msg.content == "where is my receipt?"
    assert "function note" in system_msg.content and "agent note" in system_msg.content
    assert "- where is my receipt?" not in system_msg.content and "where is my receipt?" not in static_msg.content
