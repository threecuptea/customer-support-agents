"""Regenerate frontend/lib/faq.ts from workflow/customer_support_tools.py's FAQs dict.

Run after editing FAQs: `uv run python -m scripts.export_faq` (from backend/).
tests/test_faq_export_freshness.py fails the build if the committed file drifts
from this generator's output.
"""
from __future__ import annotations

import json
from pathlib import Path

from workflow.customer_support_tools import FAQs

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BACKEND_DIR.parent / "frontend" / "lib" / "faq.ts"

HEADER = """// GENERATED FILE — do not hand-edit.
// Source of truth: backend/workflow/customer_support_tools.py (FAQs dict).
// Regenerate with: uv run python -m scripts.export_faq (from backend/).

export interface FaqEntry {
  question: string;
  answer: string;
}

export interface FaqSection {
  title: string;
  entries: FaqEntry[];
}

"""


def render(faqs: dict[str, dict[str, str]]) -> str:
    sections = [
        {
            "title": title,
            "entries": [{"question": q, "answer": a} for q, a in qa.items()],
        }
        for title, qa in faqs.items()
    ]
    body = json.dumps(sections, indent=2)
    return HEADER + f"export const FAQ_SECTIONS: FaqSection[] = {body};\n"


def main() -> None:
    OUTPUT_PATH.write_text(render(FAQs))
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
