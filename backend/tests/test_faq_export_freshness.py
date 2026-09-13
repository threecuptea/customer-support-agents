from scripts.export_faq import OUTPUT_PATH, render
from workflow.customer_support_tools import FAQs


def test_faq_export_is_up_to_date():
    committed = OUTPUT_PATH.read_text()
    expected = render(FAQs)
    assert committed == expected, (
        "frontend/lib/faq.ts is stale relative to FAQs in "
        "workflow/customer_support_tools.py. Run "
        "`uv run python -m scripts.export_faq` (from backend/) and commit the result."
    )
