"""Consent-based AI recipe suggestions built from user-selected pantry items."""

from __future__ import annotations

import json
import math
from pathlib import Path

import api_resilience


class RecipeGenerationError(RuntimeError):
    """A recipe request could not be completed or validated."""


_INGREDIENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "quantity": {"type": "number"},
        "unit": {"type": "string"},
        "inventory_id": {"type": ["integer", "null"]},
        "required": {"type": "boolean"},
    },
    "required": ["name", "quantity", "unit", "inventory_id", "required"],
    "additionalProperties": False,
}

_RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "recipes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "minutes": {"type": "integer"},
                    "servings": {"type": "integer"},
                    "ingredients": {"type": "array", "items": _INGREDIENT_SCHEMA},
                    "steps": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "summary", "minutes", "servings", "ingredients", "steps"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["recipes"],
    "additionalProperties": False,
}


def validate_recipes(payload: object, selected_items: list[dict], *, limit: int = 4,
                     max_minutes: int = 240, preferences: list[str] | None = None) -> list[dict]:
    """Normalize model output, preventing claims that unselected pantry items exist."""
    if not isinstance(payload, dict) or not isinstance(payload.get("recipes"), list):
        raise RecipeGenerationError("The recipe response did not contain a recipe list. Try again.")
    selected_by_id = {int(item["id"]): item for item in selected_items}
    recipes = []
    for raw in payload["recipes"][:limit]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()[:100]
        summary = str(raw.get("summary") or "").strip()[:300]
        try:
            minutes, servings = int(raw.get("minutes")), int(raw.get("servings"))
        except (TypeError, ValueError):
            continue
        if not title or not 1 <= minutes <= min(240, int(max_minutes)) or not 1 <= servings <= 20:
            continue
        ingredients = []
        for entry in raw.get("ingredients", [])[:30]:
            if not isinstance(entry, dict):
                continue
            name, unit = str(entry.get("name") or "").strip()[:120], str(entry.get("unit") or "").strip()[:32]
            try:
                quantity = float(entry.get("quantity"))
            except (TypeError, ValueError):
                continue
            if not name or not unit or not math.isfinite(quantity) or quantity <= 0:
                continue
            inventory_id = entry.get("inventory_id")
            if inventory_id is not None:
                try:
                    inventory_id = int(inventory_id)
                except (TypeError, ValueError):
                    raise RecipeGenerationError("A recipe referred to an item that was not in your selection. Generate ideas again.") from None
                selected = selected_by_id.get(inventory_id)
                if selected is None:
                    raise RecipeGenerationError("A recipe referred to an item that was not in your selection. Generate ideas again.")
                # Keep a stable link to the user's selected stock record.
                name = selected["name"]
            ingredients.append({"name": name, "quantity": quantity, "unit": unit,
                                "inventory_id": inventory_id, "required": bool(entry.get("required", True))})
        steps = [str(step).strip()[:500] for step in raw.get("steps", []) if str(step).strip()][:12]
        if not _dietary_constraints_hold(ingredients, preferences or []):
            continue
        selected_ids = list(dict.fromkeys(ingredient["inventory_id"] for ingredient in ingredients
                                          if ingredient["inventory_id"] is not None))
        if ingredients and steps and selected_ids:
            recipes.append({"title": title, "summary": summary, "minutes": minutes, "servings": servings,
                            "ingredients": ingredients, "steps": steps, "selected_ids": selected_ids})
    if not recipes:
        raise RecipeGenerationError("No usable recipes came back for those ingredients. Try selecting a few different items.")
    return recipes


def _dietary_constraints_hold(ingredients: list[dict], preferences: list[str]) -> bool:
    """Reject clear ingredient-level conflicts with selected dietary constraints.

    This is a conservative text check, not a certification of a recipe,
    ingredient label, cross-contamination status, or nutritional suitability.
    """
    import re

    names = [re.sub(r"[^a-z0-9]+", " ", str(item.get("name") or "").casefold()).strip()
             for item in ingredients]
    for preference in preferences:
        preference = str(preference).casefold().strip()
        for name in names:
            words = set(name.split())
            if preference == "vegan":
                plant_milk = any(value in name for value in ("coconut milk", "oat milk", "almond milk", "soy milk"))
                vegan_conflicts = {"beef", "chicken", "pork", "bacon", "lamb", "turkey", "duck", "meat", "fish", "salmon", "tuna", "seafood", "shrimp", "prawn", "crab", "lobster", "oyster", "mussel", "gelatin", "gelatine", "egg", "eggs", "cream", "butter", "cheese", "yogurt", "yoghurt", "honey", "whey", "casein"}
                if not plant_milk:
                    vegan_conflicts.add("milk")
                if words & vegan_conflicts:
                    return False
            elif preference == "vegetarian":
                if words & {"beef", "chicken", "pork", "bacon", "lamb", "turkey", "duck", "meat", "fish", "salmon", "tuna", "seafood", "shrimp", "prawn", "crab", "lobster", "oyster", "mussel", "gelatin", "gelatine"}:
                    return False
            elif preference == "pescatarian":
                if words & {"beef", "chicken", "pork", "bacon", "lamb", "turkey", "duck", "meat", "gelatin", "gelatine"}:
                    return False
            elif preference == "dairy-free":
                if words & {"milk", "cream", "butter", "cheese", "yogurt", "yoghurt", "whey", "casein"}:
                    if not any(plant_milk in name for plant_milk in ("coconut milk", "oat milk", "almond milk", "soy milk")):
                        return False
            elif preference == "gluten-free":
                if words & {"wheat", "barley", "rye", "malt", "seitan", "couscous"}:
                    return False
                if "flour" in words and not ("gluten free" in name or "glutenfree" in name):
                    return False
                if "pasta" in words and not ("gluten free" in name or "glutenfree" in name):
                    return False
    return True


def scale_servings(recipe: dict, target_servings: int) -> dict:
    """Scale listed recipe amounts proportionally while preserving its original."""
    target = int(target_servings)
    source = int(recipe["servings"])
    if not 1 <= target <= 20 or source < 1:
        raise ValueError("Servings must be between 1 and 20.")
    scaled = {**recipe, "servings": target,
              "ingredients": [{**entry, "quantity": round(float(entry["quantity"]) * target / source, 2)}
                              for entry in recipe["ingredients"]]}
    return scaled


def generate_recipes(selected_items: list[dict], *, preferences: list[str] | None = None,
                     meal_style: str = "", max_minutes: int = 30, limit: int = 3,
                     servings: int | None = None) -> list[dict]:
    """Send only user-selected ingredients and preferences to OpenAI after consent."""
    if not selected_items:
        raise RecipeGenerationError("Select at least one ingredient to generate recipe ideas.")
    if len(selected_items) > 15:
        raise RecipeGenerationError("Choose 15 ingredients or fewer for one recipe request.")
    if servings is not None and (isinstance(servings, bool) or int(servings) < 1 or int(servings) > 20):
        raise RecipeGenerationError("Choose between 1 and 20 servings.")
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise RecipeGenerationError("AI recipes need the project dependencies. Run `python -m pip install -r requirements.txt`, then restart PantryPilot.") from exc

    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=False)
    try:
        # Keep retries in api_resilience so the outer request has one known,
        # bounded retry budget instead of multiplying SDK and app retries.
        client = OpenAI(max_retries=0, timeout=45.0)
    except Exception as exc:
        raise RecipeGenerationError("OpenAI could not be initialized. Check that OPENAI_API_KEY is set in `.env` and restart PantryPilot.") from exc

    ingredients = [{
        "inventory_id": int(item["id"]), "name": str(item["name"]),
        "quantity": float(item["quantity"]), "unit": str(item["unit"]),
        "priority": str(item.get("priority") or "Normal"),
    } for item in selected_items]
    serving_instruction = (f"Target {int(servings)} servings per recipe when a target is provided. "
                          if servings is not None else "Choose a sensible serving count for each recipe. ")
    prompt = (
        "Create practical, varied home-cooking recipe ideas using the user's selected kitchen ingredients. "
        "Return only the requested structured data. Each recipe must use at least one selected ingredient, and each use "
        "must reference its exact inventory_id from the input. Do not claim the user has any ingredient not selected: "
        "mark every additional ingredient with inventory_id null. Prioritize items marked Use First when suitable. "
        "Treat the supplied stock quantities as context only; do not claim there is enough stock because recipe units may "
        "not match inventory units. Give realistic ingredient quantities, units, clear numbered cooking steps, approximate "
        f"time no longer than {int(max_minutes)} minutes, and servings. "
        f"{serving_instruction}Return up to {max(1, min(int(limit), 4))} distinct ideas. "
        "Treat each requested dietary preference as a hard constraint: do not include ingredients that conflict with it; "
        "if you cannot provide a compliant idea, return no recipe instead of relaxing the constraint. Do not provide food-safety verdicts or "
        "infer safety from dates, condition, or appearance."
    )
    request = {
        "selected_ingredients": ingredients,
        "dietary_preferences": [str(value)[:60] for value in (preferences or [])[:8]],
        "meal_style": str(meal_style or "Any")[:80],
        "max_minutes": int(max_minutes),
        "target_servings": int(servings) if servings is not None else None,
    }
    try:
        response = api_resilience.call_with_retries(lambda: client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt + "\n\nUser request:\n" + json.dumps(request, ensure_ascii=False)}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "pantry_recipe_ideas", "strict": True, "schema": _RECIPE_SCHEMA,
            }},
        ))
        choice = response.choices[0]
        if choice.message.refusal or choice.finish_reason != "stop" or not choice.message.content:
            raise RecipeGenerationError("The recipe request could not be completed. Try different ingredients or preferences.")
        recipes = validate_recipes(json.loads(choice.message.content), selected_items,
                                   limit=limit, max_minutes=max_minutes, preferences=preferences)
        return [scale_servings(recipe, int(servings)) for recipe in recipes] if servings is not None else recipes
    except RecipeGenerationError:
        raise
    except Exception as exc:
        raise RecipeGenerationError(api_resilience.safe_api_error("AI recipe generation", exc)) from exc
