"""Transparent pantry-to-meal matching and ranking."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

DATA_PATH = Path(__file__).with_name("data") / "meal_templates.json"


def load_meals(path: str | Path = DATA_PATH) -> list[dict]:
    with Path(path).open(encoding="utf-8") as file:
        meals = json.load(file)
    if not isinstance(meals, list):
        raise ValueError("Meal data must be a list.")
    return meals


def _words(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", normalized)
    result = set()
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("oes"):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        result.add(word)
    return result


def _matches(product_name: str, recipe_ingredient: dict) -> str | None:
    product_words = _words(product_name)
    for term in (recipe_ingredient["name"], *recipe_ingredient.get("aliases", [])):
        term_words = _words(term)
        if term_words and term_words <= product_words:
            return "name"
    for term in recipe_ingredient.get("substitutions", []):
        term_words = _words(term)
        if term_words and term_words <= product_words:
            return "substitution"
    return None


def ingredient_match(inventory_name: str, desired_name: str) -> bool:
    """Conservative token match used for shopping duplicate warnings."""
    inventory_words = _words(inventory_name)
    desired_words = _words(desired_name)
    return bool(inventory_words and desired_words and (
        inventory_words == desired_words or desired_words <= inventory_words or inventory_words <= desired_words
    ))


def ingredient_tokens(name: str) -> frozenset[str]:
    """Canonical word set for comparing shopping-list ingredient names."""
    return frozenset(_words(name))


def rank_ai_recipes(recipes: list[dict], inventory_items: list[dict]) -> list[dict]:
    """Rank AI-generated recipes from local pantry facts and expose the score inputs."""
    by_id = {int(item["id"]): item for item in inventory_items}
    ranked = []
    for recipe in recipes:
        matched_indices: set[int] = set()
        match_names: dict[int, list[str]] = {}
        use_first_names: list[str] = []
        missing_required: list[dict] = []
        missing_optional = 0
        for index, ingredient in enumerate(recipe.get("ingredients", [])):
            inventory_id = ingredient.get("inventory_id")
            if inventory_id is not None and int(inventory_id) in by_id:
                matches = [by_id[int(inventory_id)]]
            else:
                matches = [item for item in inventory_items if ingredient_match(item["name"], ingredient["name"])]
            if matches:
                matched_indices.add(index)
                match_names[index] = list(dict.fromkeys(item["name"] for item in matches))
                use_first_names.extend(item["name"] for item in matches if item.get("priority") == "Use First")
            elif ingredient.get("required", True):
                missing_required.append(ingredient)
            else:
                missing_optional += 1

        use_first_names = list(dict.fromkeys(use_first_names))
        score = (30 * len(use_first_names) + 6 * len(matched_indices)
                 - 12 * len(missing_required) - 2 * missing_optional
                 - min(int(recipe.get("minutes", 0)), 240) * 0.05)
        reasons = []
        if use_first_names:
            reasons.append("Uses Use First stock: " + ", ".join(use_first_names) + ".")
        else:
            reasons.append("Does not use a currently marked Use First ingredient.")
        reasons.append(f"{len(matched_indices)} recipe ingredient(s) match current kitchen items by ID or name.")
        if missing_required:
            reasons.append("Required items with no pantry name match: " + ", ".join(i["name"] for i in missing_required) + ".")
        else:
            reasons.append("Every required ingredient has a pantry match by ID or name; verify quantities and substitutions.")
        reasons.append(f"Estimated time: {int(recipe.get('minutes', 0))} minutes; shorter recipes receive a small tie-break.")
        ranked.append({"recipe": recipe, "score": round(score, 2), "reasons": reasons,
                       "missing_required": missing_required, "inventory_matches": match_names})
    ranked.sort(key=lambda item: (-item["score"], int(item["recipe"].get("minutes", 0)),
                                  str(item["recipe"].get("title", "")).casefold()))
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    return ranked


def recommend_meals(items: list[dict], *, meal_templates: list[dict] | None = None, limit: int = 5) -> list[dict]:
    """Rank meals with a transparent heuristic; name matching does not verify quantities."""
    meal_templates = meal_templates if meal_templates is not None else load_meals()
    recommendations = []
    for template in meal_templates:
        required = [ingredient for ingredient in template["ingredients"] if ingredient.get("required", True)]
        optional = [ingredient for ingredient in template["ingredients"] if not ingredient.get("required", True)]
        matches = {}
        match_types = {}
        for recipe_ingredient in template["ingredients"]:
            candidates = [(item, _matches(item["name"], recipe_ingredient)) for item in items]
            candidates = [(item, match_type) for item, match_type in candidates if match_type]
            candidates.sort(key=lambda pair: (pair[0].get("priority") != "Use First", pair[1] == "substitution", pair[0]["name"].casefold()))
            matches[recipe_ingredient["name"]] = candidates[0] if candidates else None
            match_types[recipe_ingredient["name"]] = candidates[0][1] if candidates else None
        available_required = [ingredient for ingredient in required if matches[ingredient["name"]]]
        missing_required = [ingredient for ingredient in required if not matches[ingredient["name"]]]
        available_optional = [ingredient for ingredient in optional if matches[ingredient["name"]]]
        use_first = [ingredient for ingredient in template["ingredients"]
                     if matches[ingredient["name"]] and matches[ingredient["name"]][0].get("priority") == "Use First"]
        coverage = len(available_required) / len(required) if required else 1
        urgency = 40 if use_first else 0
        coverage_points = 30 * coverage
        missing_points = 20 / (1 + len(missing_required))
        minutes = int(template["minutes"])
        time_points = 10 if minutes <= 20 else 5 if minutes <= 30 else 0
        score = round(urgency + coverage_points + missing_points + time_points, 1)
        reasons = []
        if use_first:
            names = ", ".join(dict.fromkeys(matches[item["name"]][0]["name"] for item in use_first))
            reasons.append(f"Uses your Use First item: {names}.")
        if required:
            reasons.append(f"{len(available_required)} of {len(required)} required ingredients found by name.")
        if missing_required:
            reasons.append("Still need: " + ", ".join(item["name"] for item in missing_required) + ".")
        elif available_optional:
            reasons.append("All required ingredients are in your inventory; optional ingredients are shown separately.")
        recommendations.append({
            **template, "score": score, "matches": matches,
            "match_types": match_types,
            "available_required": available_required, "missing_required": missing_required,
            "available_optional": available_optional, "use_first": use_first, "reasons": reasons,
        })
    recommendations.sort(key=lambda meal: (-meal["score"], meal["minutes"], meal["name"].casefold()))
    return recommendations[:max(0, limit)]
