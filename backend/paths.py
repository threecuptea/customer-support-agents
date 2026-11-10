"""Filesystem locations shared by main.py and slack_webhook.py.

Lives in its own module so the separate webhook app does not have to import `main` (and with it the whole
customer-support app, routes and workflow) just to find the data directory.
"""
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
# Anchored at the repo root (../data locally, /app/data in the single-container
# image, since Docker's WORKDIR puts main.py at /app/backend). Resolving here
# instead of leaving CHECKPOINT_DB/STORE_DB as bare relative paths means the
# sqlite files always land in the same place regardless of the CWD the process
# happened to be started from.
DATA_DIR = BACKEND_DIR.parent / "data"


def resolve_db_path(value: str | None) -> str | None:
    """Anchor a configured sqlite filename under DATA_DIR. An absolute path is
    used as-is (e.g. an operator-supplied override); a relative one is treated
    as a filename under DATA_DIR, regardless of any directory components given.
    """
    if not value:
        return None
    path = Path(value)
    return str(path if path.is_absolute() else DATA_DIR / path.name)
