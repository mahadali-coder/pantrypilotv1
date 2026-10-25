"""Streamlit views for meal planning, shopping, waste and meal history."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from datetime import date

import pandas as pd
import streamlit as st

import database
import ai_recipes
import inventory
import meal_engine
import shopping
import waste_tracker


def _flash_and_reset_inputs() -> None:
    message = st.session_state.pop("pantry_flash_message", None)
    if message:
        st.success(message)
    receipt_message = st.session_state.pop("receipt_import_success", None)
    if receipt_message:
        st.success(receipt_message)
    if st.session_state.pop("clear_shopping_inputs", False):
        for key, value in (("shopping_name", ""), ("shopping_unit", "items"), ("shopping_qty", 1.0),
                           ("shopping_allow_existing", False)):
            st.session_state[key] = value


def _render_meals(items: list[dict]) -> None:
    st.markdown("# AI Meal Ideas")
    st.caption("Choose the ingredients you want to use. PantryPilot sends only your selection and preferences to OpenAI after you agree.")
    if not items:
        st.info("Add or import ingredients to your kitchen before generating recipe ideas.")
        return

    items_by_id = {int(item["id"]): item for item in items}
    first_ids = [int(item["id"]) for item in items if item.get("priority") == "Use First"][:5]
    if not first_ids:
        first_ids = [int(item["id"]) for item in items[:5]]
    if "ai_selected_ingredients" not in st.session_state:
        st.session_state["ai_selected_ingredients"] = first_ids
    else:
        st.session_state["ai_selected_ingredients"] = [int(item_id) for item_id in st.session_state["ai_selected_ingredients"]
                                                        if int(item_id) in items_by_id]
    selected_ids = st.multiselect(
        "What would you like to use?",
        options=list(items_by_id),
        format_func=lambda item_id: (f"{items_by_id[item_id]['name']} · {items_by_id[item_id]['quantity']:g} "
                                     f"{items_by_id[item_id]['unit']} · {items_by_id[item_id]['location']}"),
        key="ai_selected_ingredients",
        help="Use First items are selected for you when available. Change the selection any time.",
    )
    prefs_col1, prefs_col2 = st.columns(2)
    with prefs_col1:
        dietary_preferences = st.multiselect(
            "Dietary preferences", ["Vegetarian", "Vegan", "Gluten-free", "Dairy-free", "Pescatarian"],
            key="ai_dietary_preferences",
        )
    with prefs_col2:
        max_minutes = st.selectbox("Time available", [15, 30, 45, 60], index=1,
                                   format_func=lambda value: f"Up to {value} minutes", key="ai_max_minutes")
    servings = st.selectbox("Recipe size", list(range(1, 9)), index=1,
                            format_func=lambda value: f"{value} serving{'s' if value != 1 else ''}",
                            key="ai_target_servings")
    meal_style = st.text_input("Anything else? (optional)", placeholder="e.g. quick lunch, mild flavours, one-pan meal",
                               max_chars=80, key="ai_meal_style")
    st.caption("AI-generated ideas can contain mistakes. Check ingredients, amounts, dietary needs and food-handling guidance yourself.")
    if any(items_by_id[int(item_id)].get("priority") == "Check Condition" for item_id in selected_ids):
        st.warning("You selected an item marked Check Condition. PantryPilot and its AI do not assess whether food is safe to use.")
    st.warning("This sends selected ingredient names, quantities, units, priority labels and preferences to OpenAI. No receipt or package photo is included.")
    request_fingerprint = hashlib.sha256(json.dumps({
        "ids": sorted(int(item_id) for item_id in selected_ids),
        "preferences": dietary_preferences, "max_minutes": max_minutes, "style": meal_style, "servings": servings,
    }, sort_keys=True).encode()).hexdigest()[:16]
    consent = st.checkbox("I agree to send my selected ingredients and preferences to OpenAI to generate recipe ideas.",
                          key=f"ai_recipe_consent_{request_fingerprint}")
    if st.button("Generate recipe ideas", type="primary", disabled=not selected_ids or not consent,
                 key="generate_ai_recipes"):
        try:
            recipes = ai_recipes.generate_recipes(
                [items_by_id[int(item_id)] for item_id in selected_ids],
                preferences=dietary_preferences, meal_style=meal_style, max_minutes=max_minutes, limit=3,
                servings=servings,
            )
            st.session_state["ai_generated_recipes"] = recipes
            st.session_state["ai_recipe_request_fingerprint"] = request_fingerprint
            st.success(f"Generated {len(recipes)} ideas from the ingredients you selected.")
        except ai_recipes.RecipeGenerationError as exc:
            st.error(str(exc))

    recipes = st.session_state.get("ai_generated_recipes", [])
    if recipes and st.session_state.get("ai_recipe_request_fingerprint") != request_fingerprint:
        st.info("Your selection has changed. Generate again to get ideas for the new ingredients and preferences.")
    elif recipes:
        st.markdown("## Your generated recipes")
        st.caption("Ranked locally by Use First items used, pantry ingredient matches, required items still missing, and estimated time. The ranking is a planning aid, not a nutrition or safety assessment.")
        saved_titles = {row["title"] for row in database.get_saved_recipes()}
        ranked_recipes = meal_engine.rank_ai_recipes(recipes, items)
        for index, ranked in enumerate(ranked_recipes):
            recipe = ranked["recipe"]
            with st.container(border=True):
                st.subheader(f"#{ranked['rank']} · {recipe['title']}")
                st.caption(f"About {recipe['minutes']} minutes · serves {recipe['servings']}")
                st.caption("Why this ranks here: " + " ".join(ranked["reasons"]))
                st.write(recipe["summary"])
                if recipe["title"] in saved_titles:
                    st.caption("★ Saved to your recipe box")
                elif st.button("☆ Save recipe", key=f"save_recipe_{index}"):
                    database.save_recipe(recipe)
                    st.session_state["pantry_flash_message"] = f"Saved {recipe['title']} to your recipe box."
                    st.rerun()
                for ingredient_index, ingredient in enumerate(recipe["ingredients"]):
                    if ingredient["inventory_id"] is not None:
                        st.write(f"• **From your kitchen:** {ingredient['name']} — {ingredient['quantity']:g} {ingredient['unit']}")
                    elif ingredient_index in ranked["inventory_matches"]:
                        names = ", ".join(ranked["inventory_matches"][ingredient_index])
                        st.write(f"• **Possible pantry match — verify quantity:** {ingredient['name']} (your inventory: {names})")
                    else:
                        qualifier = "Optional" if not ingredient["required"] else "Needed"
                        st.write(f"• {qualifier}: {ingredient['name']} — {ingredient['quantity']:g} {ingredient['unit']}")
                st.markdown("**Method**")
                for step_index, step in enumerate(recipe["steps"], start=1):
                    st.write(f"{step_index}. {step}")

                missing = ranked["missing_required"]
                actions = st.columns(2)
                with actions[0]:
                    if missing and st.button("Add needed ingredients to shopping list", key=f"ai_shop_{index}"):
                        added = [shopping.add_item(entry["name"], entry["quantity"], entry["unit"],
                                                   source=f"AI recipe: {recipe['title']}") for entry in missing]
                        st.session_state["pantry_flash_message"] = f"Added or combined {len(added)} ingredients from {recipe['title']}."
                        st.rerun()
                matched_items = [items_by_id[item_id] for item_id in recipe["selected_ids"] if item_id in items_by_id]
                with actions[1]:
                    if matched_items:
                        with st.expander("Log cooking and update stock", expanded=False):
                            cook_operation_key = f"ai_cook_operation_{index}"
                            st.session_state.setdefault(cook_operation_key, uuid.uuid4().hex)
                            st.caption("Choose what you actually used. Enter amounts in the inventory units shown; recipe amounts may use different units.")
                            rows = [{"Use": False, "Ingredient": item["name"],
                                     "Amount used": min(1.0, float(item["quantity"])), "Unit": item["unit"],
                                     "In stock": f"{item['quantity']:g} {item['unit']}"} for item in matched_items]
                            with st.form(f"ai_cook_form_{index}"):
                                edited = st.data_editor(pd.DataFrame(rows), hide_index=True, width="stretch",
                                    disabled=["Ingredient", "Unit", "In stock"],
                                    column_config={
                                        "Use": st.column_config.CheckboxColumn("Used", default=False),
                                        "Ingredient": st.column_config.TextColumn("Ingredient"),
                                        "Amount used": st.column_config.NumberColumn("Amount used", min_value=0.01, step=0.1),
                                        "Unit": st.column_config.TextColumn("Unit"),
                                        "In stock": st.column_config.TextColumn("In stock"),
                                    }, key=f"ai_cook_editor_{index}")
                                cooked = st.form_submit_button("Log meal and selected amounts", type="primary")
                            if cooked:
                                consumed = [{"id": matched_items[row_index]["id"], "quantity": row["Amount used"]}
                                            for row_index, row in edited.iterrows() if bool(row["Use"])]
                                try:
                                    inventory.record_cooked_meal(
                                        recipe["title"], consumed, recommended=True,
                                        operation_id=st.session_state[cook_operation_key],
                                    )
                                    st.session_state.pop(cook_operation_key, None)
                                    st.session_state["pantry_flash_message"] = f"Logged {recipe['title']} and updated {len(consumed)} item(s)."
                                    st.rerun()
                                except (ValueError, LookupError) as exc:
                                    st.error(str(exc))
                                except sqlite3.Error:
                                    st.error("PantryPilot couldn't save the cooking log, stock changes and restock items. No changes were saved; check the database and try again.")


def _render_shopping(items: list[dict]) -> None:
    st.markdown("# Shopping List")
    st.caption("PantryPilot checks similar names against your current inventory before you add a manual purchase.")
    st.info("When you record the last of an item as used or log cooking that empties it, PantryPilot adds the amount used to this list. Discarded items are not automatically reordered; you can remove or edit any suggested amount.")
    st.session_state.setdefault("shopping_qty", 1.0)
    st.session_state.setdefault("shopping_unit", "items")
    left, middle, right = st.columns([3, 1, 1])
    with left:
        name = st.text_input("Item to buy", placeholder="e.g. brown rice", key="shopping_name")
    with middle:
        quantity = st.number_input("Quantity", min_value=0.01, step=1.0, key="shopping_qty")
    with right:
        unit = st.text_input("Unit", key="shopping_unit")
    matches = shopping.find_pantry_matches(name, items) if name.strip() else []
    allow_duplicate = False
    if matches:
        st.warning("Similar item already in your kitchen: " + ", ".join(f"{row['name']} ({row['quantity']:g} {row['unit']})" for row in matches))
        allow_duplicate = st.checkbox("Add to the list anyway", key="shopping_allow_existing")
    if st.button("Add to shopping list", type="primary", disabled=not name.strip() or (bool(matches) and not allow_duplicate)):
        try:
            shopping.add_item(name, quantity, unit)
            st.session_state["pantry_flash_message"] = f"Added {name.strip()} to your shopping list."
            st.session_state["clear_shopping_inputs"] = True
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    rows = database.get_shopping_items()
    if not rows:
        st.info("Your shopping list is empty. Add items here or from a meal suggestion.")
        return
    pending = sum(not bool(row["checked"]) for row in rows)
    st.markdown(f"**{pending} item(s) to buy**")
    checked_count = sum(bool(row["checked"]) for row in rows)
    if checked_count:
        with st.container(border=True):
            st.markdown(f"**{checked_count} checked item(s) marked as purchased**")
            purchase_location = st.selectbox("Put these items in", inventory.LOCATIONS, key="shopping_purchase_location")
            if st.button("Add purchased items to my kitchen", type="primary", key="shopping_add_to_inventory"):
                try:
                    added = database.purchase_checked_items(location=purchase_location, purchase_date=date.today().isoformat())
                    st.session_state["pantry_flash_message"] = f"Added {added} purchased item(s) to your kitchen."
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    for row in rows:
        col_check, col_edit, col_source, col_remove = st.columns([2.4, 3, 1.7, 0.7])
        with col_check:
            checked = st.checkbox(
                f"{row['name']} · {row['quantity']:g} {row['unit']}",
                value=bool(row["checked"]), key=f"shopping_checked_{row['id']}",
            )
            if checked != bool(row["checked"]):
                database.update_shopping_item(row["id"], checked=checked)
                st.rerun()
        with col_edit:
            with st.form(f"shopping_edit_{row['id']}", clear_on_submit=False):
                edit_qty, edit_unit = st.columns([1, 1.2])
                with edit_qty:
                    edited_quantity = st.number_input("Quantity", min_value=0.01, value=float(row["quantity"]),
                                                       step=1.0, key=f"shopping_quantity_{row['id']}")
                with edit_unit:
                    edited_unit = st.text_input("Unit", value=row["unit"], key=f"shopping_unit_{row['id']}")
                save_shopping_edit = st.form_submit_button("Save", type="secondary")
            if save_shopping_edit:
                try:
                    shopping.update_item(row["id"], edited_quantity, edited_unit)
                    st.session_state["pantry_flash_message"] = f"Updated {row['name']} on your shopping list."
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with col_source:
            st.caption("From " + row["source"])
        with col_remove:
            if st.button("Remove", key=f"shopping_remove_{row['id']}"):
                database.remove_shopping_item(row["id"])
                st.rerun()


def _render_waste() -> None:
    st.markdown("# My Impact")
    st.markdown("## Is PantryPilot useful? · private local measures")
    usage = database.get_app_usage_summary()
    proof = waste_tracker.compare_recorded_waste(database.get_inventory_events(action="discarded"), days=30)
    value_cols = st.columns(4)
    with value_cols[0]:
        st.metric("App sessions on this device", usage["sessions"])
    with value_cols[1]:
        st.metric("Distinct days opened", usage["active_days"])
    with value_cols[2]:
        st.metric("Recommended meals logged cooked", usage["recommended_meals_cooked"])
    with value_cols[3]:
        st.metric("Meals logged cooked", usage["meals_cooked"])
    current_discard = proof["current"]
    previous_discard = proof["previous"]
    delta_text = f"{current_discard['event_count'] - previous_discard['event_count']:+d} vs previous 30 days"
    st.metric("Recorded discard events · last 30 days", current_discard["event_count"], delta=delta_text, delta_color="off")
    unit_rows = []
    for unit in sorted(set(current_discard["quantity_by_unit"]) | set(previous_discard["quantity_by_unit"])):
        unit_rows.append({"Unit": unit, "Last 30 days": current_discard["quantity_by_unit"].get(unit, 0),
                          "Previous 30 days": previous_discard["quantity_by_unit"].get(unit, 0)})
    if unit_rows:
        st.dataframe(pd.DataFrame(unit_rows), hide_index=True, width="stretch")
    if current_discard["products"]:
        frequent = current_discard["products"].most_common(5)
        st.caption("Most frequently recorded as discarded in the last 30 days: "
                   + ", ".join(f"{name} ({count})" for name, count in frequent))
    st.caption("These measurements stay in the local SQLite file and use only events recorded in PantryPilot. Fewer recorded discards do not prove less household waste; incomplete logging and changing usage can affect the comparison. Session counts are local browser sessions, not identified people.")

    period = st.segmented_control("Reporting period", ["Daily", "Weekly", "Monthly"], default="Monthly", key="impact_period")
    days = {"Daily": 1, "Weekly": 7, "Monthly": 30}[period or "Monthly"]
    summary = waste_tracker.summarize_waste(waste_tracker.get_waste_events(), days=days)
    used_summary = waste_tracker.summarize_usage(database.get_inventory_events(action="used"), days=days)
    stat_cols = st.columns(4)
    with stat_cols[0]:
        st.metric(f"Discard events · {period.casefold()}", summary["event_count"])
    with stat_cols[1]:
        st.metric("Different foods discarded", summary["product_count"])
    with stat_cols[2]:
        value = summary["recorded_value"]
        st.metric("Recorded value discarded", f"${value:.2f}" if value is not None else "Not recorded")
    with stat_cols[3]:
        value_used = used_summary["recorded_value"]
        st.metric("Recorded value used", f"${value_used:.2f}" if value_used is not None else "Not recorded")
    st.caption("Recorded values are estimates allocated from purchase prices you entered. They are not savings or waste-reduction claims.")
    if summary["reasons"]:
        chart = pd.DataFrame([{"Reason": reason, "Discard events": count}
                              for reason, count in summary["reasons"].most_common()])
        st.bar_chart(chart, x="Reason", y="Discard events")
        if summary["quantity_by_unit"]:
            st.markdown("**Recorded quantities by unit**")
            st.write(" · ".join(f"{amount:g} {unit}" for unit, amount in summary["quantity_by_unit"].items()))
    else:
        st.info("No discarded food has been recorded in the last 30 days. When you discard an item, choose a reason in inventory management to make this report more useful.")

    st.markdown("**Weekly discard-event trend · last 8 weeks**")
    weekly = pd.DataFrame(waste_tracker.weekly_waste_trend(waste_tracker.get_waste_events(), weeks=8))
    st.bar_chart(weekly, x="Week of", y="Discard events")
    st.caption("This chart counts recorded discard actions. It is not a measured weight or proof of food waste prevented.")

    events = summary["events"]
    if events:
        st.dataframe(pd.DataFrame([{
            "Food": event["ingredient_name"], "Quantity": f"{event['quantity']:g} {event['unit']}",
            "Reason": event.get("reason") or "Not recorded", "Recorded": event["created_at"],
            "Recorded value": f"${event['purchase_price']:.2f}" if event.get("purchase_price") is not None else "—",
        } for event in events]), hide_index=True, width="stretch")
    meals = database.get_meal_cook_events()
    st.markdown(f"**Meals cooked and logged:** {len(meals)}")
    if meals:
        with st.expander("Recently cooked meals"):
            st.dataframe(pd.DataFrame([{
                "Meal": event["meal_name"],
                "Ingredients updated": ", ".join(f"{ingredient['name']} {ingredient['quantity']:g} {ingredient['unit']}"
                                                   for ingredient in json.loads(event["ingredients_json"])) or "No stock amounts recorded",
                "Recorded": event["created_at"],
            } for event in meals[:30]]), hide_index=True, width="stretch")

    receipts = database.get_receipt_purchases()
    st.markdown(f"**Receipts imported:** {len(receipts)}")
    priced_receipts = [float(row["total_cost"]) for row in receipts if row.get("total_cost") is not None]
    if priced_receipts:
        st.caption(f"Recorded total across imported receipts: ${sum(priced_receipts):.2f}. This is the total visible in imported receipt photos, not a complete household spending total.")
    if receipts:
        with st.expander("Purchase history"):
            st.dataframe(pd.DataFrame([{
                "Purchase date": row.get("purchase_date") or "Date not read",
                "Receipt total": f"${row['total_cost']:.2f}" if row.get("total_cost") is not None else "Not read",
                "Discount": f"${row['discount_total']:.2f}" if row.get("discount_total") is not None else "Not recorded",
                "Items imported": row["item_count"], "Saved": row["created_at"],
            } for row in receipts[:100]]), hide_index=True, width="stretch")
            reviewed_history = [{
                "Receipt date": receipt.get("purchase_date") or "Undated",
                "Item": line.get("name"), "Printed line": line.get("receipt_line") or "—",
                "Quantity": f"{line.get('quantity'):g} {line.get('unit')}" if line.get("quantity") is not None else "Unknown",
                "Line amount": f"${line['price']:.2f}" if line.get("price") is not None else "Unknown",
                "Storage": line.get("location") or "—",
            } for receipt in receipts[:20] for line in receipt.get("reviewed_lines", [])]
            if reviewed_history:
                st.markdown("**Reviewed receipt lines**")
                st.dataframe(pd.DataFrame(reviewed_history), hide_index=True, width="stretch")


def render_planning_and_waste(items: list[dict]) -> None:
    _flash_and_reset_inputs()
    st.markdown('<div class="pp-section-label">Plan, shop, and learn</div>', unsafe_allow_html=True)
    meals_tab, shopping_tab, waste_tab = st.tabs(["Meal ideas", "Shopping list", "Waste & history"])
    with meals_tab:
        _render_meals(items)
    with shopping_tab:
        _render_shopping(items)
    with waste_tab:
        _render_waste()


def render_flash_messages() -> None:
    _flash_and_reset_inputs()


def render_discover_meals(items: list[dict]) -> None:
    _render_meals(items)
    saved = database.get_saved_recipes()
    if saved:
        st.markdown("## Your saved recipe box")
        for row in saved:
            recipe = row["recipe"]
            with st.expander(f"★ {recipe['title']} · {recipe['servings']} servings · {recipe['minutes']} min"):
                st.write(recipe["summary"])
                st.markdown("**Ingredients**")
                for entry in recipe["ingredients"]:
                    st.write(f"• {entry['name']} — {entry['quantity']:g} {entry['unit']}")
                st.markdown("**Method**")
                for step_index, step in enumerate(recipe["steps"], start=1):
                    st.write(f"{step_index}. {step}")
                if st.button("Remove saved recipe", key=f"remove_saved_recipe_{row['id']}"):
                    database.remove_saved_recipe(row["id"])
                    st.rerun()


def render_shopping_list(items: list[dict]) -> None:
    _render_shopping(items)


def render_impact() -> None:
    _render_waste()
