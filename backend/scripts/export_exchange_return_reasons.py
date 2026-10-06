"""Regenerate frontend/lib/exchange-return-reasons.ts from models/model.py's ExchangeReturnReason enum.

The survey UI (CSA-14) needs a 1-to-1 mapping between each radio option and an
ExchangeReturnReason member: it submits the member's *value* (a full sentence,
not a short code) as `reason_option` in ExchangeOrReturnInput. Generating this
from the enum keeps that mapping from drifting if a member is ever renamed or
reworded.

Run after editing ExchangeReturnReason: `uv run python -m scripts.export_exchange_return_reasons`
(from backend/). tests/test_exchange_return_reasons_export_freshness.py fails the
build if the committed file drifts from this generator's output.
"""
from __future__ import annotations

import json
from pathlib import Path

from models.model import ExchangeReturnReason

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BACKEND_DIR.parent / "frontend" / "lib" / "exchange-return-reasons.ts"

HEADER = """// GENERATED FILE — do not hand-edit.
// Source of truth: backend/models/model.py (ExchangeReturnReason enum).
// Regenerate with: uv run python -m scripts.export_exchange_return_reasons (from backend/).
//
// `value` is submitted as `reason_option` in ExchangeOrReturnInput — it must
// match the backend enum's value exactly, which is why this file is generated
// rather than hand-maintained.

export interface ExchangeReturnReasonOption {
  key: string;
  value: string;
}

"""


def render(reasons: type[ExchangeReturnReason]) -> str:
    options = [{"key": member.name, "value": member.value} for member in reasons]
    body = json.dumps(options, indent=2)
    return HEADER + f"export const EXCHANGE_RETURN_REASONS: ExchangeReturnReasonOption[] = {body};\n"


def main() -> None:
    OUTPUT_PATH.write_text(render(ExchangeReturnReason))
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
