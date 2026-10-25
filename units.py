"""Small, explicit unit vocabulary for safe pantry and shopping arithmetic."""

from __future__ import annotations

import math
import re
import unicodedata


_UNITS: dict[str, tuple[str, float, str]] = {}


def _register(dimension: str, canonical: str, factor: float, *aliases: str) -> None:
    for alias in (canonical, *aliases):
        _UNITS[alias] = (dimension, factor, canonical)


_register("mass", "mg", 0.001, "milligram", "milligrams")
_register("mass", "g", 1, "gram", "grams")
_register("mass", "kg", 1000, "kilogram", "kilograms", "kilo", "kilos")
_register("mass", "oz", 28.349523125, "ounce", "ounces")
_register("mass", "lb", 453.59237, "lbs", "pound", "pounds")
_register("volume", "ml", 1, "millilitre", "millilitres", "milliliter", "milliliters")
_register("volume", "l", 1000, "litre", "litres", "liter", "liters")
_register("volume", "tsp", 4.92892159375, "teaspoon", "teaspoons")
_register("volume", "tbsp", 14.78676478125, "tablespoon", "tablespoons")
_register("volume", "cup", 236.5882365, "cups")
_register("volume", "fl oz", 29.5735295625, "fluid ounce", "fluid ounces")
_register("count:item", "item", 1, "items", "each", "ea", "piece", "pieces", "pc", "pcs")
_register("count:pack", "pack", 1, "packs", "packet", "packets")
_register("count:can", "can", 1, "cans", "tin", "tins")
_register("count:bag", "bag", 1, "bags")
_register("count:bottle", "bottle", 1, "bottles")
_register("count:loaf", "loaf", 1, "loaves")
_register("count:bunch", "bunch", 1, "bunches")
_register("count:clove", "clove", 1, "cloves")
_register("count:slice", "slice", 1, "slices")
_register("count:serve", "serve", 1, "serves", "serving", "servings")


def _key(unit: str) -> str:
    text = unicodedata.normalize("NFKC", str(unit or "")).casefold().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_unit(unit: str) -> str:
    """Return a known canonical unit, or a conservative normalized custom unit."""
    key = _key(unit)
    known = _UNITS.get(key)
    if known:
        return known[2]
    # Unknown units are deliberately exact; generic plural stripping can turn
    # unrelated words (e.g. "glass") into a false conversion match.
    return key


def compatible(from_unit: str, to_unit: str) -> bool:
    source, target = _UNITS.get(_key(from_unit)), _UNITS.get(_key(to_unit))
    if source and target:
        return source[0] == target[0]
    return normalize_unit(from_unit) == normalize_unit(to_unit)


def convert_quantity(quantity: float, from_unit: str, to_unit: str) -> float | None:
    """Convert compatible quantities; return None instead of guessing otherwise."""
    try:
        amount = float(quantity)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount):
        return None
    source, target = _UNITS.get(_key(from_unit)), _UNITS.get(_key(to_unit))
    if source and target:
        if source[0] != target[0]:
            return None
        return amount * source[1] / target[1]
    if normalize_unit(from_unit) == normalize_unit(to_unit):
        return amount
    return None
