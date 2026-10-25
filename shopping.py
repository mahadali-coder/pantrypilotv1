"""Shopping-list validation, pantry duplicate checks, and meal aggregation."""

from __future__ import annotations

import math
from pathlib import Path

import database
from meal_engine import ingredient_match, ingredient_tokens
from units import convert_quantity


def find_pantry_matches(name: str, items: list[dict]) -> list[dict]:
    return [item for item in items if ingredient_match(item["name"], name)]


def add_item(name: str, quantity: float, unit: str, *, source: str = "Manual",
             db_path: str | Path | None = None) -> int:
    clean_name = str(name or "").strip()
    clean_unit = str(unit or "").strip()
    if not clean_name or len(clean_name) > 120:
        raise ValueError("Enter an item name with 120 characters or fewer.")
    if not clean_unit or len(clean_unit) > 32:
        raise ValueError("Enter a unit with 32 characters or fewer.")
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a number greater than zero.") from None
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Quantity must be a finite number greater than zero.")
    source = str(source or "Manual")[:100]
    tokens = ingredient_tokens(clean_name)
    for existing in database.get_shopping_items(db_path):
        converted = convert_quantity(quantity, clean_unit, existing["unit"])
        if not existing["checked"] and ingredient_tokens(existing["name"]) == tokens and converted is not None:
            database.combine_shopping_item(existing["id"], quantity=converted, source=source, path=db_path)
            return int(existing["id"])
    return database.add_shopping_item({"name": clean_name, "quantity": quantity, "unit": clean_unit,
                                       "source": source}, db_path)


def add_missing_from_meal(meal: dict, *, db_path: str | Path | None = None) -> list[int]:
    ids = []
    for ingredient in meal["missing_required"]:
        ids.append(add_item(ingredient["name"], ingredient["quantity"], ingredient["unit"],
                            source=meal["name"], db_path=db_path))
    return ids


def update_item(item_id: int, quantity: float, unit: str, *, db_path: str | Path | None = None) -> None:
    """Validate and save a user's explicit shopping quantity and unit edit."""
    clean_unit = str(unit or "").strip()
    if not clean_unit or len(clean_unit) > 32:
        raise ValueError("Enter a unit with 32 characters or fewer.")
    try:
        amount = float(quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a number greater than zero.") from None
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Quantity must be a finite number greater than zero.")
    database.update_shopping_item(item_id, quantity=amount, unit=clean_unit, path=db_path)
