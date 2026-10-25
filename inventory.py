"""Validation and use cases for PantryPilot inventory records."""

from __future__ import annotations

from datetime import date
import math
from pathlib import Path
import re

import database
from units import convert_quantity

LOCATIONS = ("Refrigerator", "Freezer", "Pantry")
PRIORITIES = ("Normal", "Use First", "Check Condition")
CATEGORIES = ("Other", "Produce", "Dairy", "Meat", "Bakery", "Pantry", "Frozen", "Beverages", "Household")
DATE_FIELDS = ("purchase_date", "use_by_date", "best_before_date")


def suggest_storage_location(name: str) -> str:
    """Suggest a typical home storage place from product wording; users can override it."""
    text = re.sub(r"[^a-z0-9]+", " ", str(name or "").casefold()).strip()
    if not text:
        return "Refrigerator"

    freezer_terms = (
        "frozen", "freezer", "ice cream", "ice pop", "popsicle", "frozen fruit",
        "frozen berries", "frozen vegetables", "frozen veg", "frozen peas", "frozen corn",
        "frozen fish", "frozen chicken", "frozen meat", "frozen pizza", "frozen chips",
    )
    if any(term in text for term in freezer_terms):
        return "Freezer"

    pantry_terms = (
        "canned", "tinned", "can of", "dry pasta", "pasta", "rice", "flour", "sugar",
        "oats", "cereal", "lentil", "dried bean", "dry bean", "chickpea", "spice", "herb",
        "olive oil", "cooking oil", "vinegar", "peanut butter", "jam", "honey", "coffee",
        "tea", "cracker", "crisp", "chips", "bread", "wrap", "tortilla", "noodle",
        "stock cube", "stock powder", "nuts", "dried fruit", "milk powder", "shelf stable",
    )
    if any(term in text for term in pantry_terms):
        return "Pantry"
    return "Refrigerator"


def validate_ingredient(data: dict) -> dict:
    """Return normalized data or raise ValueError with a user-readable message."""
    name = str(data.get("name", "")).strip()
    unit = str(data.get("unit", "")).strip()
    if not name:
        raise ValueError("Enter an ingredient name.")
    if len(name) > 120:
        raise ValueError("Ingredient names must be 120 characters or fewer.")
    if not unit:
        raise ValueError("Enter a quantity unit (for example, g, items or cups).")
    if len(unit) > 32:
        raise ValueError("Units must be 32 characters or fewer.")
    try:
        quantity = float(data.get("quantity"))
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a number greater than zero.") from None
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Quantity must be a finite number greater than zero.")
    raw_threshold = data.get("reorder_threshold")
    try:
        reorder_threshold = None if raw_threshold in (None, "") else float(raw_threshold)
    except (TypeError, ValueError):
        raise ValueError("Restock threshold must be a number greater than or equal to zero.") from None
    if reorder_threshold is not None and (not math.isfinite(reorder_threshold) or reorder_threshold < 0):
        raise ValueError("Restock threshold must be a finite number greater than or equal to zero.")
    location = data.get("location")
    priority = data.get("priority")
    if location not in LOCATIONS:
        raise ValueError("Choose Refrigerator, Freezer or Pantry.")
    if priority not in PRIORITIES:
        raise ValueError("Choose Normal, Use First or Check Condition.")
    category = str(data.get("category") or "Other").strip() or "Other"
    if len(category) > 40:
        raise ValueError("Categories must be 40 characters or fewer.")
    raw_price = data.get("purchase_price")
    price_text = "" if raw_price is None else str(raw_price).strip()
    if not price_text:
        purchase_price = None
    else:
        price_text = price_text.replace(",", "")
        price_text = re.sub(r"^(?:AUD\s*|AU\$\s*|\$\s*)", "", price_text, flags=re.IGNORECASE)
        price_text = re.sub(r"\s*(?:AUD|\$)$", "", price_text, flags=re.IGNORECASE).strip()
        try:
            purchase_price = float(price_text)
        except (TypeError, ValueError):
            raise ValueError("Purchase price must be a number greater than or equal to zero.") from None
        # Pandas represents an empty receipt price cell as NaN; treat that as an
        # omitted optional price while still rejecting infinities and negatives.
        if math.isnan(purchase_price):
            purchase_price = None
        elif not math.isfinite(purchase_price) or purchase_price < 0:
            raise ValueError("Purchase price must be a finite number greater than or equal to zero.")
    normalized = {"name": name, "quantity": quantity, "unit": unit, "location": location, "priority": priority,
                  "category": category, "purchase_price": purchase_price,
                  "reorder_threshold": reorder_threshold if reorder_threshold else None}
    for field in DATE_FIELDS:
        value = data.get(field) or None
        if value is not None:
            if isinstance(value, date):
                value = value.isoformat()
            else:
                try:
                    value = date.fromisoformat(str(value)).isoformat()
                except ValueError:
                    raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a valid date.") from None
        normalized[field] = value
    return normalized


def add(data: dict, db_path: str | Path | None = None) -> int:
    return database.add_ingredient(validate_ingredient(data), db_path)


def add_many(records: list[dict], db_path: str | Path | None = None, *, receipt: dict | None = None) -> list[int]:
    """Validate the whole batch before writing any item."""
    if not records:
        raise ValueError("Enter at least one ingredient.")
    validated = []
    for line_number, record in enumerate(records, start=1):
        try:
            validated.append(validate_ingredient(record))
        except ValueError as exc:
            raise ValueError(f"Item {line_number}: {exc}") from None
    return database.add_ingredients(validated, db_path, receipt=receipt)


def parse_quick_entries(text: str, *, location: str | None, priority: str) -> list[dict]:
    """Parse lines as `name | quantity | unit`, optionally suggesting location per item."""
    records = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        separator = "|" if "|" in line else ","
        parts = [part.strip() for part in line.split(separator)]
        if len(parts) != 3:
            raise ValueError(f"Line {line_number}: use `name | quantity | unit`, for example `Milk | 2 | litres`.")
        name, quantity_text, unit = parts
        try:
            quantity = float(quantity_text)
        except ValueError:
            raise ValueError(f"Line {line_number}: quantity must be a number.") from None
        item_location = location or suggest_storage_location(name)
        records.append({"name": name, "quantity": quantity, "unit": unit, "location": item_location,
                        "priority": priority, "purchase_date": None, "use_by_date": None, "best_before_date": None})
    if not records:
        raise ValueError("Enter at least one ingredient.")
    return records


def update(ingredient_id: int, data: dict, db_path: str | Path | None = None) -> None:
    normalized = validate_ingredient(data)
    current = next((item for item in database.get_ingredients(db_path) if item["id"] == ingredient_id), None)
    if current is None:
        raise LookupError(f"Active ingredient {ingredient_id} was not found")
    current_cost = current.get("purchase_price")
    if current_cost is not None and abs(normalized["quantity"] - float(current["quantity"])) > 1e-9:
        try:
            submitted_cost = float(data.get("purchase_price")) if data.get("purchase_price") not in (None, "") else None
        except (TypeError, ValueError):
            submitted_cost = None
        # Keep the recorded value proportional to physical quantity, not the
        # displayed number (e.g. 1000 g -> 1 kg is not a 99.9% stock loss).
        if submitted_cost is not None and abs(submitted_cost - float(current_cost)) < 1e-9:
            converted_new_quantity = convert_quantity(normalized["quantity"], normalized["unit"], current["unit"])
            if converted_new_quantity is not None:
                normalized["purchase_price"] = float(current_cost) * converted_new_quantity / float(current["quantity"])
    database.update_ingredient(ingredient_id, normalized, db_path)


def list_current(db_path: str | Path | None = None) -> list[dict]:
    return database.get_ingredients(db_path)


def remove(ingredient_id: int, db_path: str | Path | None = None) -> None:
    database.remove_ingredient(ingredient_id, db_path)


def mark(ingredient_id: int, action: str, db_path: str | Path | None = None, *, reason: str | None = None) -> None:
    if action not in ("used", "discarded"):
        raise ValueError("Action must be used or discarded.")
    items = database.get_ingredients(db_path)
    ingredient = next((item for item in items if item["id"] == ingredient_id), None)
    if ingredient is None:
        raise LookupError(f"Active ingredient {ingredient_id} was not found")
    database.record_event(ingredient, action, db_path, reason=reason)


def consume(ingredient_id: int, quantity: float, action: str = "used", *,
           reason: str | None = None, db_path: str | Path | None = None) -> bool:
    """Record a partial or complete used/discarded amount from active stock."""
    if action not in ("used", "discarded"):
        raise ValueError("Action must be used or discarded.")
    try:
        amount = float(quantity)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number greater than zero.") from None
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Amount must be a finite number greater than zero.")
    items = database.get_ingredients(db_path)
    ingredient = next((item for item in items if item["id"] == ingredient_id), None)
    if ingredient is None:
        raise LookupError(f"Active ingredient {ingredient_id} was not found")
    if amount > float(ingredient["quantity"]):
        raise ValueError(f"Amount cannot exceed the current quantity ({ingredient['quantity']:g} {ingredient['unit']}).")
    return database.record_event(ingredient, action, db_path, reason=reason, quantity=amount)


def record_cooked_meal(meal_name: str, consumed: list[dict], db_path: str | Path | None = None,
                       *, recommended: bool = False, operation_id: str | None = None) -> int:
    """Record meal preparation with user-entered amounts consumed from stock."""
    clean_name = str(meal_name or "").strip()
    if not clean_name:
        raise ValueError("Choose a meal to record.")
    normalized = []
    for index, row in enumerate(consumed, start=1):
        try:
            quantity = float(row.get("quantity"))
        except (TypeError, ValueError):
            raise ValueError(f"Ingredient {index}: amount used must be a number greater than zero.") from None
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError(f"Ingredient {index}: amount used must be a finite number greater than zero.")
        normalized.append({"id": int(row["id"]), "quantity": quantity})
    return database.record_cooked_meal(clean_name, normalized, db_path, recommended=recommended,
                                       operation_id=operation_id)
