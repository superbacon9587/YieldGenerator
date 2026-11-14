"""Shared helpers for the data scripts: project paths, .env loading, CSV writing."""

from __future__ import annotations

import csv
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICES_DIR = PROJECT_ROOT / "data" / "reference" / "prices"
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def load_env(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding existing values."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    load_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}. Add it to {PROJECT_ROOT / '.env'}.")
    return value


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {path.relative_to(PROJECT_ROOT)}")
