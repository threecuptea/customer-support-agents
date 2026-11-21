"""CSA-30 test helpers: request flows now return before `summarize_node` runs (it runs in a background task on the
TestClient's event loop). Tests that read or update the checkpoint/ store right after a request, from their own
`asyncio.run` loop, must wait for that task first: otherwise they race it, and AsyncSqliteSaver's internal lock,
bound to the app's loop, raises "bound to a different event loop"."""
from fastapi.testclient import TestClient


def drain_summaries(client: TestClient, timeout: float = 30) -> None:
    """Wait, on the app's own event loop, for every pending background summary of `client`'s app."""
    summaries = getattr(client.app.state, "summaries", None)
    if summaries is not None and client.portal is not None:
        client.portal.call(summaries.drain, timeout)


class SummaryDrainingTestClient(TestClient):
    """A TestClient that waits for pending background summaries after every request, like a customer who takes
    longer than the ~2 s summary to act next. Tests of the background behaviour itself use a plain TestClient."""

    def request(self, *args, **kwargs):
        response = super().request(*args, **kwargs)
        drain_summaries(self)
        return response
