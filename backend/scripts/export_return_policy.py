"""Regenerate frontend/lib/return-policy.ts from workflow/customer_support_utils.py's RETURN_POLICY.

Run after editing RETURN_POLICY: `uv run python -m scripts.export_return_policy` (from backend/).
tests/test_return_policy_export_freshness.py fails the build if the committed file drifts
from this generator's output.
"""
from __future__ import annotations

import json
from pathlib import Path

from workflow.customer_support_utils import RETURN_POLICY

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BACKEND_DIR.parent / "frontend" / "lib" / "return-policy.ts"

HEADER = """// GENERATED FILE — do not hand-edit.
// Source of truth: backend/workflow/customer_support_utils.py (RETURN_POLICY).
// Regenerate with: uv run python -m scripts.export_return_policy (from backend/).

"""


def render(return_policy: str) -> str:
    return HEADER + f"export const RETURN_POLICY: string = {json.dumps(return_policy)};\n"


def main() -> None:
    OUTPUT_PATH.write_text(render(RETURN_POLICY))
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
