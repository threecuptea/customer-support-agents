from scripts.export_return_policy import OUTPUT_PATH, render
from workflow.customer_support_utils import RETURN_POLICY


def test_return_policy_export_is_up_to_date():
    committed = OUTPUT_PATH.read_text()
    expected = render(RETURN_POLICY)
    assert committed == expected, (
        "frontend/lib/return-policy.ts is stale relative to RETURN_POLICY in "
        "workflow/customer_support_utils.py. Run "
        "`uv run python -m scripts.export_return_policy` (from backend/) and commit the result."
    )
