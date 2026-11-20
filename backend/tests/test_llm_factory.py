"""get_llm() override handling, tested without any network call by faking init_chat_model."""
import pytest

import workflow.llm as llm_module


@pytest.fixture()
def captured(monkeypatch):
    calls = []

    def fake_init_chat_model(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(llm_module, "init_chat_model", fake_init_chat_model)
    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    return calls


def test_model_override_is_passed_once_not_twice(captured):
    # Regression: model used to be passed positionally AND inside **params -> TypeError -> silent mock fallback.
    result = llm_module.get_llm(model="gpt-4.1")
    assert not isinstance(result, llm_module.MockChatModel)
    (args, kwargs), = captured
    assert args == ("gpt-4.1",)
    assert "model" not in kwargs and "provider" not in kwargs


def test_defaults_come_from_environment_and_other_overrides_pass_through(captured):
    llm_module.get_llm(temperature=0.0)
    (args, kwargs), = captured
    assert args == ("env-model",)
    assert kwargs["temperature"] == 0.0


def test_provider_override(captured):
    llm_module.get_llm(provider="anthropic", model="claude-x")
    (args, kwargs), = captured
    assert args == ("claude-x",)
    assert kwargs["model_provider"] == "anthropic"


# --- timeout/ retries (CSA-27) -------------------------------------------------------------------
def test_timeout_and_retries_default_to_bounded_values(captured, monkeypatch):
    # Without them the OpenAI SDK waits up to 600 s per attempt, 3 attempts.
    monkeypatch.delenv("LLM_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)
    llm_module.get_llm()
    (_, kwargs), = captured
    assert kwargs["timeout"] == llm_module.DEFAULT_LLM_TIMEOUT == 30.0
    assert kwargs["max_retries"] == llm_module.DEFAULT_LLM_MAX_RETRIES == 2


def test_timeout_and_retries_come_from_environment(captured, monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "12.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    llm_module.get_llm()
    (_, kwargs), = captured
    assert (kwargs["timeout"], kwargs["max_retries"]) == (12.5, 0)


def test_explicit_timeout_and_retries_override_environment(captured, monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "12.5")
    llm_module.get_llm(timeout=5, max_retries=1)
    (_, kwargs), = captured
    assert (kwargs["timeout"], kwargs["max_retries"]) == (5, 1)


def test_chat_openai_really_receives_timeout_and_retries(monkeypatch):
    # Real init_chat_model (no network call): a misspelled param would either be dropped or make get_llm fall back
    # to the mock silently, so check the values land on ChatOpenAI and its OpenAI client.
    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_TIMEOUT", "20")
    monkeypatch.setenv("LLM_MAX_RETRIES", "3")
    llm = llm_module.get_llm(model="gpt-4o-mini", provider="openai")
    assert not isinstance(llm, llm_module.MockChatModel)
    assert (llm.request_timeout, llm.max_retries) == (20.0, 3)
    assert (llm.root_async_client.timeout, llm.root_async_client.max_retries) == (20.0, 3)
