import os
from urllib.parse import urlsplit, urlunsplit

import pytest
import redis as redis_sync
from dotenv import dotenv_values, find_dotenv

from tests.llm_harness import harness
from tests.llm_harness.harness import RESULTS, format_report

# Capture what was passed on the command line BEFORE any test module imports workflow.customer_support,
# whose load_dotenv(override=True) resets LLM_MODEL / LLM_TEMPERATURE from .env.
# e.g.  LLM_MODEL=gpt-4.1 RUN_LLM_TESTS=1 uv run pytest -m llm
harness.REQUESTED_MODEL = os.getenv("LLM_MODEL")
harness.REQUESTED_TEMPERATURE = os.getenv("LLM_TEMPERATURE")

# tests/test_main.py does os.environ.setdefault("USE_MOCK_LLM", "true") at import, which would
# silently flip the whole process to the mock model. conftest is imported first, so when real-LLM
# tests are requested, claim the variable now (an explicit USE_MOCK_LLM from the user still wins).
if os.getenv("RUN_LLM_TESTS") == "1":
    os.environ.setdefault("USE_MOCK_LLM", "false")


# --- Redis isolation (CSA-22 review) -------------------------------------------------------------
# The tests used to run against the same Redis DB as the dev server and call flushdb() afterwards,
# wiping real refund requests, the `rr` id counter and every `rr:by_order:*` list. Now every test
# talks to a dedicated DB number (default 15), derived from the REDIS_URL you already configured
# (so host/password are the same); DB 0 - the dev server's default - is refused outright.
TEST_REDIS_DB = int(os.getenv("TEST_REDIS_DB", "15"))
if TEST_REDIS_DB == 0:
    raise RuntimeError("TEST_REDIS_DB must not be 0: that is the dev/default Redis database")


def _redis_url_for_db(base_url: str, db: int) -> str:
    return urlunsplit(urlsplit(base_url)._replace(path=f"/{db}"))


# conftest is imported before any app module, so .env has not been loaded into os.environ yet.
_BASE_REDIS_URL = (
    os.getenv("REDIS_URL")
    or dotenv_values(find_dotenv(usecwd=True)).get("REDIS_URL")
    or "redis://localhost:6379"
)
TEST_REDIS_URL = _redis_url_for_db(_BASE_REDIS_URL, TEST_REDIS_DB)


@pytest.fixture(autouse=True, scope="class")
def _isolated_redis_db():
    # The app lifespans (main.py, slack_webhook.py) read REDIS_URL when they start, and modules that run
    # load_dotenv(override=True) on import (some are imported lazily, mid-run) reset it from .env.
    # Re-assert it before every test; autouse fixtures are set up before the class-scoped `client` fixtures.
    os.environ["REDIS_URL"] = TEST_REDIS_URL
    yield


@pytest.fixture()
def redis_client():
    """Sync client on the dedicated test DB. Flushes only that DB, and only after verifying it is the test DB."""
    client = redis_sync.Redis.from_url(TEST_REDIS_URL)
    assert client.connection_pool.connection_kwargs.get("db") == TEST_REDIS_DB != 0
    client.flushdb()
    yield client
    try:
        client.flushdb()
        client.close()
    except Exception as e:
        print(f"Error cleaning up Redis client: {e}")


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
