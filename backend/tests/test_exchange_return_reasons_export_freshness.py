from scripts.export_exchange_return_reasons import OUTPUT_PATH, render
from models.model import ExchangeReturnReason


def test_exchange_return_reasons_export_is_up_to_date():
    committed = OUTPUT_PATH.read_text()
    expected = render(ExchangeReturnReason)
    assert committed == expected, (
        "frontend/lib/exchange-return-reasons.ts is stale relative to ExchangeReturnReason "
        "in models/model.py. Run `uv run python -m scripts.export_exchange_return_reasons` "
        "(from backend/) and commit the result."
    )
