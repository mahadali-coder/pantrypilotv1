"""Portable, round-trippable exports for local PantryPilot records."""

from __future__ import annotations

import csv
from io import StringIO


INVENTORY_CSV_FIELDS = (
    "id", "name", "quantity", "unit", "location", "purchase_date", "use_by_date",
    "best_before_date", "priority", "category", "purchase_price", "reorder_threshold",
    "status", "created_at", "updated_at",
)


def inventory_csv(records: list[dict]) -> bytes:
    """Serialize current inventory as UTF-8 CSV with a stable header and quoting."""
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=INVENTORY_CSV_FIELDS, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode("utf-8")
