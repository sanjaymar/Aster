"""One application home, with durable data separated from disposable caches."""

import os
from pathlib import Path


def home():
    return (
        Path(os.getenv("ASTER_HOME") or os.getenv("ASTER_DATA_DIR") or "data")
        .expanduser()
        .resolve()
    )


def folders(root):
    root = Path(root)
    return {
        name: root / name
        for name in (
            "library",
            "models",
            "cache",
            "exports",
            "logs",
            "experiments",
            "archive",
            "config",
        )
    }


def prepare(root):
    for path in folders(root).values():
        path.mkdir(parents=True, exist_ok=True)


def filename(name, limit=72):
    """Readable file names; object identity and revisions belong in the database."""
    import re

    value = Path(name).name
    suffix = Path(value).suffix.lower()[:12]
    stem = re.sub(r"[^\w\u3400-\u9fff.-]+", "-", Path(value).stem).strip(".-_")
    return (stem or "document")[:limit] + suffix
