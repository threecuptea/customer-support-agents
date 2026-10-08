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
