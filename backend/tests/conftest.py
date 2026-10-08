import os

import pytest

from tests.llm_harness.harness import RESULTS, format_report

# tests/test_main.py does os.environ.setdefault("USE_MOCK_LLM", "true") at import, which would
# silently flip the whole process to the mock model. conftest is imported first, so when real-LLM
# tests are requested, claim the variable now (an explicit USE_MOCK_LLM from the user still wins).
if os.getenv("RUN_LLM_TESTS") == "1":
    os.environ.setdefault("USE_MOCK_LLM", "false")


def _llm_tests_enabled() -> tuple[bool, str]:
    if os.getenv("RUN_LLM_TESTS") != "1":
        return False, "real-LLM tests are opt-in: set RUN_LLM_TESTS=1"
    # The API key/model live in .env, which workflow modules load only on import.
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    from workflow.llm import using_mock_llm
    if using_mock_llm():
        return False, "RUN_LLM_TESTS=1 but no real LLM is configured (unset USE_MOCK_LLM, set LLM_MODEL/API key)"
    return True, ""


def pytest_collection_modifyitems(config, items):
    enabled, reason = _llm_tests_enabled()
    if enabled:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


def pytest_terminal_summary(terminalreporter):
    if RESULTS:
        terminalreporter.section("real-LLM harness report")
        terminalreporter.write_line(format_report(RESULTS))
