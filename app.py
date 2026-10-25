"""PantryPilot 2.0 — inventory and quick-entry interface."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import html
import math
import sqlite3
import uuid

import pandas as pd
import streamlit as st

import database
import app_features
import exports
import inventory
import priorities
import scanner
import shopping
import waste_tracker


st.set_page_config(page_title="PantryPilot", page_icon="🥕", layout="wide")
database.initialize_database()
local_session_id = st.session_state.setdefault("pantrypilot_local_session_id", uuid.uuid4().hex)
try:
    database.record_app_session(local_session_id)
except sqlite3.Error:
    # Engagement measurement is optional; a metrics table error must not block
    # local inventory management.
    pass
items = inventory.list_current()

st.markdown("""
<style>
:root { color-scheme:light; --pp-green:#1f4d3a; --pp-green-2:#356b50; --pp-lime:#dde8dc; --pp-cream:#faf7f0; --pp-ink:#2b2b2b; --pp-muted:#626262; --pp-line:#e6e1d5; --pp-white:#fff; --pp-amber:#b7791f; --pp-red:#b3261e; }
html, body, [class*="css"] { color:var(--pp-ink); }
.stApp { background:var(--pp-cream); color:var(--pp-ink); font-family:'Avenir Next',Arial,sans-serif; }
[data-testid="stHeader"] { background:var(--pp-cream); }
[data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > .main { background:var(--pp-cream); }
.block-container { max-width:1380px; padding-top:1.5rem; padding-bottom:3rem; }
h1,h2,h3,h4,h5,h6,p,li,label { color:var(--pp-ink); }
h1,h2,h3 { font-family:'Avenir Next',Arial,sans-serif !important; letter-spacing:-.035em; }
h1 { font-size:2.65rem !important; font-weight:800 !important; }
h2 { font-weight:750 !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color:var(--pp-muted) !important; }
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label, [data-testid="stMarkdownContainer"] p { color:var(--pp-ink); }
[data-testid="stMarkdownContainer"] a { color:var(--pp-green); }
.pp-topbar { display:flex; align-items:center; justify-content:space-between; padding:0 0 1.1rem; border-bottom:1px solid var(--pp-line); margin-bottom:1.7rem; }
.pp-brand { display:flex; align-items:center; gap:.65rem; color:var(--pp-green); font:800 1.2rem 'Avenir Next',Arial,sans-serif; letter-spacing:-.04em; }
.pp-brand-mark { width:34px; height:34px; display:grid; place-items:center; color:#fff; font-size:18px; background:var(--pp-green); border-radius:12px; }
.pp-top-note { color:var(--pp-muted); font-size:.86rem; }
.pp-hero { position:relative; overflow:hidden; padding:2rem 2.2rem; border-radius:20px; color:#fff; background:linear-gradient(115deg,#1f4d3a 0%,#356b50 100%); margin:1.1rem 0 1.25rem; }
.pp-hero:after { content:' '; position:absolute; right:-50px; top:-140px; width:370px; height:370px; border:1px solid rgba(255,255,255,.12); border-radius:50%; box-shadow:0 0 0 35px rgba(255,255,255,.035),0 0 0 75px rgba(255,255,255,.025); }
.pp-eyebrow { color:#cfe4bb; font-size:.72rem; font-weight:700; letter-spacing:.15em; text-transform:uppercase; margin-bottom:.55rem; }
.pp-hero-title { position:relative; z-index:1; font:800 2rem/1.18 'Avenir Next',Arial,sans-serif; letter-spacing:-.045em; max-width:650px; }
.pp-hero-copy { position:relative; z-index:1; color:#dcebe2; font-size:.98rem; margin-top:.55rem; max-width:600px; }
.pp-section-label { color:var(--pp-muted); font-size:.72rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; margin:1.4rem 0 .7rem; }
.pp-stat { background:white; border:1px solid var(--pp-line); border-radius:17px; padding:1rem 1.15rem; min-height:92px; box-shadow:0 2px 9px rgba(34,66,48,.025); }
.pp-stat-label { color:var(--pp-muted); font-size:.78rem; font-weight:600; }
.pp-stat-value { color:var(--pp-green); font:800 1.65rem 'Avenir Next',Arial,sans-serif; margin-top:.12rem; letter-spacing:-.04em; }
.pp-stat-note { color:var(--pp-muted); font-size:.73rem; margin-top:.02rem; }
[data-testid="stExpander"] { background:var(--pp-white); border:1px solid var(--pp-line); border-radius:16px; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary span { color:var(--pp-green) !important; font-weight:700; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap:.45rem; border-bottom:1px solid var(--pp-line); }
[data-testid="stTabs"] button[role="tab"] { color:var(--pp-muted) !important; font-weight:650; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color:var(--pp-green) !important; }
button[data-testid="stBaseButton-primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] { background:var(--pp-green) !important; color:#fff !important; border:1px solid var(--pp-green) !important; border-radius:11px; font-weight:700; }
button[data-testid="stBaseButton-secondary"], .stButton button:not([kind="primary"]) { background:#fff !important; color:var(--pp-green) !important; border:1px solid #b9c9bd !important; border-radius:11px; font-weight:650; }
button[data-testid="stBaseButton-primary"] *, button[data-testid="stBaseButton-secondary"] * { color:inherit !important; }
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stTextArea"] textarea, [data-testid="stDateInput"] input, [data-testid="stSelectbox"] [data-baseweb="select"], [data-testid="stMultiSelect"] [data-baseweb="select"] { background:#fff !important; color:var(--pp-ink) !important; border-radius:10px; }
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder { color:#66776e !important; opacity:1; }
[data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"], [role="option"] { background:#fff !important; color:var(--pp-ink) !important; }
[role="option"]:hover, [aria-selected="true"][role="option"] { background:#eaf2e9 !important; color:var(--pp-green) !important; }
[data-testid="stCheckbox"] label, [data-testid="stRadio"] label, [data-testid="stToggle"] label { color:var(--pp-ink) !important; }
[data-testid="stCheckbox"] label p, [data-testid="stRadio"] label p { color:var(--pp-ink) !important; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border:1px solid var(--pp-line); border-radius:14px; overflow:hidden; }
[data-testid="stAlert"] { border-radius:13px; }
[data-testid="stAlert"] p { color:var(--pp-ink) !important; }
[data-testid="stMetric"] { background:#fff; border:1px solid var(--pp-line); border-radius:14px; padding:.8rem 1rem; }
[data-testid="stMetricLabel"], [data-testid="stMetricValue"] { color:var(--pp-ink) !important; }
[data-testid="stFileUploader"] section { background:#fff; border:1px dashed #9aafa0; border-radius:14px; }
[data-testid="stFileUploader"] section * { color:var(--pp-ink) !important; }
:focus-visible { outline:3px solid #7cae85 !important; outline-offset:2px; }
hr { border-color:var(--pp-line); }
[class*="st-key-main_navigation"] > div[data-testid="stRadio"] > label, [class*="st-key-kitchen_action"] > div[data-testid="stRadio"] > label, [data-testid="stRadio"].st-key-main_navigation > label, [data-testid="stRadio"].st-key-kitchen_action > label { display:none; }
[class*="st-key-main_navigation"] [role="radiogroup"], [class*="st-key-kitchen_action"] [role="radiogroup"] { display:flex; gap:.25rem; padding:.35rem; border-bottom:1px solid var(--pp-line); background:transparent; }
[class*="st-key-main_navigation"] [role="radiogroup"] label, [class*="st-key-kitchen_action"] [role="radiogroup"] label { border-radius:9px; padding:.55rem .9rem; color:var(--pp-muted) !important; font-weight:600; }
[class*="st-key-main_navigation"] [role="radiogroup"] label:has(input:checked), [class*="st-key-kitchen_action"] [role="radiogroup"] label:has(input:checked) { background:var(--pp-lime); color:var(--pp-green) !important; }
.pp-local-badge { background:var(--pp-lime); color:var(--pp-green); padding:.4rem .7rem; border-radius:999px; font-size:.78rem; font-weight:650; }
.pp-card { background:#fff; border:1px solid var(--pp-line); border-radius:16px; padding:1rem 1.1rem; height:100%; }
.pp-card-muted { color:var(--pp-muted); font-size:.86rem; }
.pp-pill { display:inline-block; padding:.25rem .55rem; background:#fbefd5; color:#80530e; border-radius:999px; font-size:.75rem; font-weight:650; }
@media(max-width:700px) { .block-container{padding:1rem .8rem 2rem}.pp-hero{padding:1.5rem}.pp-hero-title{font-size:1.65rem}.pp-top-note{display:none} [class*="st-key-main_navigation"] [role="radiogroup"]{overflow-x:auto;flex-wrap:nowrap} [class*="st-key-main_navigation"] [role="radiogroup"] label{white-space:nowrap;padding:.45rem .6rem} }
</style>
<div class="pp-topbar"><div class="pp-brand"><span class="pp-brand-mark">✿</span> PantryPilot</div><div class="pp-local-badge">Local-first · AI scans require consent</div></div>
""", unsafe_allow_html=True)

# A pending navigation request is applied before rendering the radio navigation widget.
pending_navigation = st.session_state.pop("pending_navigation", None)
if pending_navigation:
    st.session_state["main_navigation"] = pending_navigation["page"]
    if pending_navigation.get("kitchen_action"):
        st.session_state["kitchen_action"] = pending_navigation["kitchen_action"]
    if pending_navigation.get("meal_id"):
        st.session_state["selected_meal"] = pending_navigation["meal_id"]

page = st.radio("Main navigation", ["Home", "My Kitchen", "Discover Meals", "Shopping List", "My Impact"],
                horizontal=True, key="main_navigation", label_visibility="collapsed")


def navigate(page_name: str, *, kitchen_action: str | None = None, meal_id: str | None = None) -> None:
    st.session_state["pending_navigation"] = {
        "page": page_name, "kitchen_action": kitchen_action, "meal_id": meal_id,
    }
    st.rerun()


app_features.render_flash_messages()

if page == "Home":
    greeting = "Good morning" if datetime.now().hour < 12 else "Good afternoon" if datetime.now().hour < 18 else "Good evening"
    st.markdown(
        f'<div class="pp-hero"><div class="pp-eyebrow">Your kitchen, at a glance</div>'
        f'<div class="pp-hero-title">{greeting}<br>Let’s make the most of what’s in your kitchen.</div>'
        '<div class="pp-hero-copy">A clearer view of what you have, what needs attention, and what you can make.</div></div>',
        unsafe_allow_html=True,
    )
    attention = priorities.build_attention_list(items)
    low_stock = [item for item in items if item.get("reorder_threshold") is not None
                 and float(item["quantity"]) <= float(item["reorder_threshold"])]
    generated_meals = st.session_state.get("ai_generated_recipes", [])
    cols = st.columns(5)
    metrics = [
        ("Items in kitchen", str(len(items))),
        ("Marked Use First", str(sum(item["priority"] == "Use First" for item in items))),
        ("AI ideas generated", str(len(generated_meals))),
        ("Food Rescue", str(len(attention))),
        ("Restock alerts", str(len(low_stock))),
    ]
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.markdown(f'<div class="pp-stat"><div class="pp-stat-label">{label}</div><div class="pp-stat-value">{value}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="pp-section-label">Food Rescue</div>', unsafe_allow_html=True)
    st.caption("Items you marked Use First or want to check. These are reminders, not food-safety assessments.")
    if not attention:
        st.success("Nothing is currently marked for attention.")
    else:
        for item in attention[:4]:
            with st.container(border=True):
                item_col, button_col = st.columns([5, 1.5])
                with item_col:
                    st.markdown(f"**{item['name']}** · {item['quantity']:g} {item['unit']} · {item['location']}")
                    st.caption(" ".join(item["reasons"]))
                with button_col:
                    if st.button("Mark as used", key=f"home_used_{item['id']}", type="primary", width="stretch"):
                        try:
                            inventory.consume(item["id"], item["quantity"], "used")
                        except (ValueError, LookupError) as exc:
                            st.error(str(exc))
                            st.stop()
                        st.rerun()
                    if st.button("Dismiss reminder", key=f"home_dismiss_{item['id']}", width="stretch"):
                        priorities.dismiss(item)
                        st.rerun()

    if low_stock:
        st.markdown('<div class="pp-section-label">Restock alerts</div>', unsafe_allow_html=True)
        st.caption("These alerts use the minimum quantities you set for individual items.")
        for item in low_stock[:8]:
            row_col, action_col = st.columns([5, 1.5])
            with row_col:
                st.write(f"**{item['name']}** · {item['quantity']:g} {item['unit']} remaining (restock at {item['reorder_threshold']:g})")
            with action_col:
                if st.button("Add to shopping list", key=f"restock_{item['id']}", width="stretch"):
                    shopping.add_item(item["name"], max(float(item["reorder_threshold"]) - float(item["quantity"]), 1),
                                      item["unit"], source="Restock alert")
                    st.session_state["pantry_flash_message"] = f"Added {item['name']} to your shopping list."
                    st.rerun()

    st.markdown('<div class="pp-section-label">AI meal ideas</div>', unsafe_allow_html=True)
    st.caption("Choose what you want to use and generate fresh recipe ideas in Discover Meals.")
    if not generated_meals:
        st.info("No AI recipes generated yet. Choose ingredients to start.")
    else:
        meal_cols = st.columns(min(3, len(generated_meals)))
        for meal_index, (col, meal) in enumerate(zip(meal_cols, generated_meals[:3])):
            with col:
                safe_title = html.escape(str(meal.get("title", "Recipe idea")))
                safe_summary = html.escape(str(meal.get("summary", "")))
                safe_minutes = max(0, min(int(meal.get("minutes", 0)), 240))
                st.markdown(f'<div class="pp-card"><div class="pp-eyebrow" style="color:#757575">AI IDEA · ABOUT {safe_minutes} MIN</div>'
                            f'<strong>{safe_title}</strong><p class="pp-card-muted">{safe_summary}</p></div>',
                            unsafe_allow_html=True)
                if st.button("Open recipe ideas", key=f"home_meal_{meal_index}", width="stretch"):
                    navigate("Discover Meals")

    st.markdown('<div class="pp-section-label">Quick actions</div>', unsafe_allow_html=True)
    actions = [
        ("＋ Add an ingredient", "My Kitchen", "Add one with dates"),
        ("▧ Scan a receipt", "My Kitchen", "Import receipt photo"),
        ("▤ View my kitchen", "My Kitchen", None),
        ("✦ Generate AI recipe ideas", "Discover Meals", None),
        ("▤ Open shopping list", "Shopping List", None),
    ]
    quick_cols = st.columns(len(actions))
    for col, (label, target, kitchen_action) in zip(quick_cols, actions):
        with col:
            if st.button(label, key=f"home_action_{target}_{kitchen_action or 'default'}", width="stretch"):
                navigate(target, kitchen_action=kitchen_action)

    activity = database.get_recent_activity(limit=8)
    st.markdown('<div class="pp-section-label">Recent activity</div>', unsafe_allow_html=True)
    if activity:
        for row in activity[:5]:
            st.text(f"{row['created_at']} · {row['text']}")
    else:
        st.info("No activity recorded yet. Used, discarded and cooked items will appear here.")

elif page == "My Kitchen":
    st.markdown('<div class="pp-section-label">Add items or import a receipt</div>', unsafe_allow_html=True)

    with st.container(border=True):
        kitchen_action = st.radio("Add or import", ["Quick add multiple", "Add one with dates", "Import receipt photo"],
                                  horizontal=True, key="kitchen_action", label_visibility="collapsed")
        if kitchen_action == "Quick add multiple":
            st.caption("Paste or type one item per line: `name | quantity | unit`. PantryPilot suggests a storage location for each line; choose one location for all if you prefer.")
            with st.form("quick_add", clear_on_submit=True, enter_to_submit=False):
                quick_text = st.text_area("Items", placeholder="Milk | 2 | litres\nSpinach | 1 | bag\nEggs | 12 | items", height=110)
                quick_col1, quick_col2 = st.columns(2)
                with quick_col1:
                    quick_location_mode = st.selectbox("Storage location", ("Suggest for each item", *inventory.LOCATIONS), key="quick_location_mode")
                with quick_col2:
                    quick_priority = st.selectbox("Priority for these items", inventory.PRIORITIES, key="quick_priority")
                quick_submit = st.form_submit_button("Add these items", type="primary")
            if quick_submit:
                try:
                    quick_location = None if quick_location_mode == "Suggest for each item" else quick_location_mode
                    rows = inventory.parse_quick_entries(quick_text, location=quick_location, priority=quick_priority)
                    ids = inventory.add_many(rows)
                    st.success(f"Added {len(ids)} items with suggested storage locations.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        elif kitchen_action == "Import receipt photo":
            st.caption("Upload or take a grocery receipt photo. Check and correct the scanner's results before adding them to inventory.")
            st.warning("Scanning sends the receipt photo to the OpenAI API for processing. Receipts can include store, purchase, or payment details. Scanning is disabled until you agree.")
            receipt_file = st.file_uploader("Receipt photo", type=["png", "jpg", "jpeg", "webp"],
                                            max_upload_size=15, key="receipt_upload")
            camera_receipt = st.camera_input("Or take a receipt photo", key="receipt_camera")
            image_source = camera_receipt or receipt_file
            if image_source is not None:
                st.image(image_source, caption="Receipt photo to be processed after you agree and select Read receipt.", width=420)
            consent_key = "allow_openai_receipt_none"
            receipt_image_digest = None
            if image_source is not None:
                receipt_image_digest = hashlib.sha256(image_source.getvalue()).hexdigest()
                image_fingerprint = receipt_image_digest[:16]
                consent_key = f"allow_openai_receipt_{image_fingerprint}"
            receipt_already_imported = bool(receipt_image_digest and database.receipt_image_imported(receipt_image_digest))
            if receipt_already_imported:
                st.info("This exact receipt photo is already in purchase history, so PantryPilot skipped another API scan.")
            allow_openai_scan = st.checkbox(
                "I agree to send this receipt photo to OpenAI for item extraction.", key=consent_key
            )
            if st.button("Read receipt", type="primary", disabled=image_source is None or not allow_openai_scan or receipt_already_imported, key="read_receipt"):
                try:
                    receipt_bytes = image_source.getvalue()
                    scanned_receipt = scanner.scan_receipt_for_pantry(
                        receipt_bytes, mime_type=image_source.type
                    )
                    st.session_state["receipt_draft"] = scanned_receipt
                    st.session_state["receipt_draft_image_hash"] = receipt_image_digest
                    st.session_state["receipt_draft_token"] = receipt_image_digest[:16]
                    st.session_state.pop("receipt_review_editor", None)
                    st.session_state.pop("receipt_review_ready", None)
                    st.session_state.pop("receipt_reviewed_rows", None)
                    rows = st.session_state["receipt_draft"]["items"]
                    st.success(f"Found {len(rows)} possible grocery items. Check quantities and remove any packaging or non-food lines before saving.")
                except scanner.ReceiptScanError as exc:
                    st.error(str(exc))

            if st.session_state.get("receipt_draft"):
                receipt_result = st.session_state["receipt_draft"]
                receipt_image_hash = st.session_state.get("receipt_draft_image_hash")
                duplicate_receipt = bool(receipt_image_hash and database.receipt_image_imported(receipt_image_hash))
                if duplicate_receipt:
                    st.error("This exact receipt photo has already been imported. It cannot be added a second time.")
                parsed_purchase_date = None
                receipt_date = receipt_result.get("purchase_date")
                summary_parts = []
                if receipt_date:
                    try:
                        parsed_purchase_date = date.fromisoformat(receipt_date)
                        summary_parts.append(f"Receipt date: {parsed_purchase_date.isoformat()}")
                    except ValueError:
                        st.caption("Receipt date could not be read reliably.")
                if receipt_result.get("total_cost") is not None:
                    st.metric("Detected receipt total", f"${receipt_result['total_cost']:.2f}")
                else:
                    st.warning("Receipt total could not be read. You can enter a correction after reviewing the item lines.")
                st.warning("Check the printed line and count for every product. Package sizes (like 400 g or 6 pack) are not the number purchased. Remove bags, recycling and non-food lines. Scanner output can be wrong.")
                with st.form("confirm_receipt", enter_to_submit=False):
                    draft_df = pd.DataFrame([{
                        "Include": True,
                        "Ingredient": item["clean_name"],
                        "Printed receipt line": item.get("receipt_line", item["clean_name"]),
                        "Quantity": item["quantity"],
                        "Unit": item["unit"],
                        "Storage location": inventory.suggest_storage_location(item["clean_name"]),
                        "Price": item["price"],
                        "Category": item["category"],
                    } for item in receipt_result["items"]])
                    reviewed = st.data_editor(
                        draft_df, hide_index=True, width="stretch", num_rows="dynamic",
                        disabled=["Printed receipt line"],
                        column_config={
                            "Include": st.column_config.CheckboxColumn("Add", default=True),
                            "Ingredient": st.column_config.TextColumn("Item name", required=True),
                            "Printed receipt line": st.column_config.TextColumn("Printed receipt line", disabled=True, width="large"),
                            "Quantity": st.column_config.NumberColumn("Quantity", min_value=0.01, step=1.0),
                            "Unit": st.column_config.TextColumn("Unit", required=True),
                            "Storage location": st.column_config.SelectboxColumn("Storage location", options=inventory.LOCATIONS, required=True),
                            "Price": st.column_config.NumberColumn("Line amount before receipt discounts", format="$%.2f", min_value=0.0),
                            "Category": st.column_config.TextColumn("Category"),
                        },
                        key="receipt_review_editor",
                    )
                    receipt_priority = st.selectbox("Priority for checked items", inventory.PRIORITIES, key="receipt_priority")
                    st.caption("Storage is suggested per item from its name. Review or change it in the table before importing.")
                    if parsed_purchase_date:
                        st.caption("Receipt date detected: " + parsed_purchase_date.isoformat())
                    receipt_purchase_date = st.date_input(
                        "Confirm purchase date", value=parsed_purchase_date,
                        key=f"receipt_confirmed_purchase_date_{st.session_state.get('receipt_draft_token', 'current')}",
                        help="Taken from the receipt. Correct it if needed; leave blank if the receipt date is unclear.",
                    )
                    review_receipt = st.form_submit_button("Review checked items and total", type="primary", disabled=duplicate_receipt)
                if review_receipt:
                    st.session_state["receipt_reviewed_rows"] = reviewed[reviewed["Include"]].to_dict("records")
                    st.session_state["receipt_review_priority"] = receipt_priority
                    st.session_state["receipt_review_purchase_date"] = receipt_purchase_date.isoformat() if receipt_purchase_date else None
                    st.session_state["receipt_review_ready"] = True
                    st.rerun()

                if st.session_state.get("receipt_review_ready"):
                    try:
                        chosen = st.session_state.get("receipt_reviewed_rows", [])
                        token = st.session_state.get("receipt_draft_token", "current")
                        st.markdown("**Final receipt check**")
                        st.dataframe(pd.DataFrame([{
                            "Item": row["Ingredient"], "Quantity": (f"{float(row['Quantity']):g} {row['Unit']}"
                                if row.get("Quantity") is not None and pd.notna(row.get("Quantity")) else "Unknown — correct before import"),
                            "Location": row["Storage location"], "Line amount": row["Price"] if pd.notna(row["Price"]) else "Unknown",
                        } for row in chosen]), hide_index=True, width="stretch")
                        quantities_valid = all(row.get("Quantity") is not None and pd.notna(row.get("Quantity"))
                                               and math.isfinite(float(row["Quantity"])) and float(row["Quantity"]) > 0
                                               for row in chosen)
                        if not quantities_valid:
                            st.error("At least one checked item has an unknown quantity. Edit its line and enter the count from the receipt before importing.")
                        total_col, discount_col = st.columns(2)
                        with total_col:
                            total_text = st.text_input("Receipt total (correct if needed)",
                                value="" if receipt_result.get("total_cost") is None else str(receipt_result["total_cost"]),
                                key=f"receipt_total_{token}", help="Leave blank if it cannot be read; PantryPilot will store it as unknown.")
                        with discount_col:
                            discount_text = st.text_input("Receipt-level discounts (optional)",
                                value="" if receipt_result.get("discount_total") is None else str(receipt_result["discount_total"]),
                                key=f"receipt_discount_{token}", help="Enter the positive total discount amount. It is not subtracted from individual item prices.")
                        total_value = scanner.parse_optional_currency(total_text)
                        discount_value = scanner.parse_optional_currency(discount_text)
                        comparison = scanner.reconcile_receipt_total(total_value,
                            [{"price": row["Price"]} for row in chosen], discount_total=discount_value)
                        discrepancy_needs_ack = comparison["status"] != "matches"
                        if comparison["status"] == "matches":
                            st.success(f"Reviewed line amounts reconcile to ${total_value:.2f} after the recorded discount.")
                        elif comparison["status"] == "review":
                            st.warning(f"Receipt total differs from reviewed product lines by ${comparison['difference']:.2f}. This may reflect missing lines, deposits, discounts or extraction errors. PantryPilot will not assign the difference to products automatically.")
                        else:
                            st.warning("The total cannot be reconciled because it or all checked line amounts are unknown. You can still import with the unknown values preserved.")
                        acknowledge = False
                        if discrepancy_needs_ack:
                            acknowledge = st.checkbox("I reviewed the discrepancy or unknown amounts and want to continue.", key=f"receipt_ack_{token}")
                        final_col1, final_col2 = st.columns(2)
                        with final_col1:
                            if st.button("Edit receipt lines", key=f"receipt_back_{token}"):
                                st.session_state["receipt_review_ready"] = False
                                st.rerun()
                        with final_col2:
                            if st.button("Confirm and import items", type="primary", disabled=duplicate_receipt or not chosen or not quantities_valid or (discrepancy_needs_ack and not acknowledge), key=f"receipt_commit_{token}"):
                                records = [{"name": row["Ingredient"], "quantity": row["Quantity"], "unit": row["Unit"],
                                            "location": row["Storage location"], "priority": st.session_state["receipt_review_priority"],
                                            "purchase_date": st.session_state.get("receipt_review_purchase_date"), "use_by_date": None, "best_before_date": None,
                                            "category": row["Category"], "purchase_price": row["Price"] if pd.notna(row["Price"]) else None}
                                           for row in chosen]
                                ids = inventory.add_many(records, receipt={
                                    "purchase_date": st.session_state.get("receipt_review_purchase_date"),
                                    "total_cost": total_value, "discount_total": discount_value,
                                    "image_hash": receipt_image_hash,
                                    "reviewed_lines": [{
                                        "name": row["Ingredient"], "receipt_line": row.get("Printed receipt line"),
                                        "quantity": float(row["Quantity"]), "unit": row["Unit"],
                                        "price": None if pd.isna(row["Price"]) else float(row["Price"]),
                                        "category": row["Category"], "location": row["Storage location"],
                                    } for row in chosen],
                                })
                                for key in ("receipt_draft", "receipt_draft_image_hash", "receipt_draft_token",
                                            "receipt_review_editor", "receipt_review_ready", "receipt_reviewed_rows"):
                                    st.session_state.pop(key, None)
                                st.session_state["receipt_import_success"] = f"Imported {len(ids)} reviewed item line(s) and saved receipt history."
                                st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

        elif kitchen_action == "Add one with dates":
            name = st.text_input("Ingredient name", placeholder="e.g. frozen berries", key="single_ingredient_name")
            suggested_location = inventory.suggest_storage_location(name)
            st.caption(f"Suggested storage: **{suggested_location}** · based on the item name. You can change it below.")
            location_widget_key = "single_location_" + hashlib.sha256(name.casefold().encode()).hexdigest()[:12]
            with st.form("add_single", clear_on_submit=True, enter_to_submit=False):
                quantity_col, unit_col = st.columns([1, 1])
                with quantity_col:
                    quantity = st.number_input("Quantity", min_value=0.01, value=1.0, step=1.0)
                with unit_col:
                    unit = st.text_input("Unit", placeholder="bunch, g, items")
                details1, details2, details3 = st.columns(3)
                with details1:
                    location = st.selectbox("Storage location", inventory.LOCATIONS,
                        index=inventory.LOCATIONS.index(suggested_location), key=location_widget_key)
                with details2:
                    priority = st.selectbox("Priority", inventory.PRIORITIES)
                with details3:
                    purchase = st.date_input("Purchase date (optional)", value=None)
                metadata1, metadata2 = st.columns(2)
                with metadata1:
                    category = st.selectbox("Category", inventory.CATEGORIES)
                with metadata2:
                    purchase_price = st.text_input("Total paid for this quantity (optional)", placeholder="e.g. 4.50 AUD")
                reorder_threshold = st.number_input("Restock alert at (optional; 0 disables)", min_value=0.0, value=0.0, step=1.0,
                                                    help="Choose the minimum quantity at which you want a reminder. Uses the same unit as the quantity above.")
                dates1, dates2 = st.columns(2)
                with dates1:
                    use_by = st.date_input("Use-by date (optional)", value=None)
                with dates2:
                    best_before = st.date_input("Best-before date (optional)", value=None)
                submitted = st.form_submit_button("Add ingredient", type="primary")
            if submitted:
                try:
                    inventory.add({"name": name, "quantity": quantity, "unit": unit, "location": location, "priority": priority,
                                   "purchase_date": purchase, "use_by_date": use_by, "best_before_date": best_before,
                                   "category": category, "purchase_price": purchase_price or None,
                                   "reorder_threshold": reorder_threshold or None})
                    st.session_state.pop("single_ingredient_name", None)
                    st.success(f"Added {name.strip()}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.markdown('<div class="pp-section-label">MY KITCHEN</div>', unsafe_allow_html=True)
    st.subheader(f"{len(items)} item{'s' if len(items) != 1 else ''} across your fridge, freezer and pantry")
    if not items:
        st.write("Your inventory is empty. Use **Quick add multiple** to enter several items at once.")
    else:
        filter1, filter2, filter3, filter4 = st.columns([2, 1, 1, 1.25])
        with filter1:
            search = st.text_input("Search inventory", placeholder="Search by ingredient name")
        with filter2:
            location_filter = st.selectbox("Filter location", ("All locations", *inventory.LOCATIONS))
        with filter3:
            priority_filter = st.selectbox("Filter priority", ("All priorities", *inventory.PRIORITIES))
        with filter4:
            sort_order = st.selectbox("Sort by", ("Name A–Z", "Priority", "Quantity low to high", "Earliest date"))
        shown = [i for i in items if search.strip().casefold() in i["name"].casefold()
                 and (location_filter == "All locations" or i["location"] == location_filter)
                 and (priority_filter == "All priorities" or i["priority"] == priority_filter)]
        priority_order = {"Use First": 0, "Check Condition": 1, "Normal": 2}
        if sort_order == "Priority":
            shown.sort(key=lambda item: (priority_order[item["priority"]], item["name"].casefold()))
        elif sort_order == "Quantity low to high":
            shown.sort(key=lambda item: (float(item["quantity"]), item["name"].casefold()))
        elif sort_order == "Earliest date":
            shown.sort(key=lambda item: (item.get("use_by_date") or item.get("best_before_date") or "9999-12-31",
                                         item["name"].casefold()))
        else:
            shown.sort(key=lambda item: item["name"].casefold())
        display = [{"Ingredient": i["name"], "Quantity": f"{i['quantity']:g} {i['unit']}",
                    "Location": {"Refrigerator": "Fridge", "Freezer": "Freezer", "Pantry": "Pantry"}[i["location"]],
                    "Purchased": i["purchase_date"] or "—",
                    "Use by / best before": i["use_by_date"] or i["best_before_date"] or "—",
                    "Restock at": f"{i['reorder_threshold']:g} {i['unit']}" if i.get("reorder_threshold") is not None else "—",
                    "Priority": i["priority"]} for i in shown]
        if display:
            st.dataframe(pd.DataFrame(display), hide_index=True, width="stretch")
        else:
            st.caption("No inventory items match these filters.")

        st.divider()
        st.subheader("Manage an ingredient")
        selected = st.selectbox("Choose an item", items, format_func=lambda i: f"{i['name']} · {i['quantity']:g} {i['unit']} ({i['location']})", key="selected_item")
        with st.expander("📷 Scan this package for its printed date"):
            st.caption("Take a close, clear photo of the package date label. PantryPilot will transcribe a clearly printed use-by or best-before date; it will not estimate one. Verify the result, then save it with the item.")
            st.warning("The photo is sent to OpenAI for extraction only after you agree and press Scan package date.")
            package_photo = st.camera_input("Take a close-up of the date label", key=f"package_camera_{selected['id']}")
            package_upload = st.file_uploader("Or upload a close-up", type=["png", "jpg", "jpeg", "webp"], key=f"package_upload_{selected['id']}")
            package_image = package_photo or package_upload
            package_fingerprint = hashlib.sha256(package_image.getvalue()).hexdigest()[:16] if package_image else "none"
            if package_image is not None:
                st.image(package_image, caption="Check that the date marking is in focus and fills the frame.", width=300)
            package_consent = st.checkbox(
                "I agree to send this package photo to OpenAI.",
                key=f"package_scan_consent_{selected['id']}_{package_fingerprint}",
            )
            if st.button("Scan package date", type="primary", disabled=package_image is None or not package_consent,
                         key=f"scan_package_date_{selected['id']}"):
                try:
                    package_date_result = scanner.scan_product_date(
                        package_image.getvalue(), product_name=selected["name"], mime_type=package_image.type
                    )
                    st.session_state[f"package_date_result_{selected['id']}"] = package_date_result
                    if package_date_result["date"] and package_date_result["date_type"] in {"use_by", "best_before"}:
                        field = "use_by_date" if package_date_result["date_type"] == "use_by" else "best_before_date"
                        widget_key = f"useby_{selected['id']}" if field == "use_by_date" else f"bestbefore_{selected['id']}"
                        st.session_state[widget_key] = date.fromisoformat(package_date_result["date"])
                        st.success(f"Read {package_date_result['date_type'].replace('_', ' ')} date: {package_date_result['date']}. Check it below, then save changes.")
                        st.rerun()
                    else:
                        st.warning("No clear use-by or best-before date was found. Try a closer photo with the printed date in focus.")
                except scanner.ReceiptScanError as exc:
                    st.error(str(exc))
            package_date_result = st.session_state.get(f"package_date_result_{selected['id']}")
            if package_date_result and package_date_result.get("product_text"):
                st.caption("Label text detected: " + package_date_result["product_text"])
            if package_date_result and package_date_result.get("date_text"):
                st.caption("Date marking read from photo: " + package_date_result["date_text"])
        tab_edit, tab_status = st.tabs(["Edit details", "Update status"])
        with tab_edit:
            with st.form("edit_ingredient", enter_to_submit=False):
                col1, col2 = st.columns(2)
                with col1:
                    edit_name = st.text_input("Name", value=selected["name"])
                    edit_quantity = st.number_input("Quantity", min_value=0.01, value=float(selected["quantity"]), step=1.0)
                    edit_unit = st.text_input("Unit", value=selected["unit"])
                    edit_location = st.selectbox("Location", inventory.LOCATIONS, index=inventory.LOCATIONS.index(selected["location"]))
                    edit_category_options = tuple(dict.fromkeys((*inventory.CATEGORIES, selected["category"])))
                    edit_category = st.selectbox("Category", edit_category_options, index=edit_category_options.index(selected["category"]))
                    edit_purchase_price = st.text_input("Recorded value of remaining stock", value=str(selected["purchase_price"] or ""))
                    edit_reorder_threshold = st.number_input("Restock alert at (0 disables)", min_value=0.0,
                        value=float(selected.get("reorder_threshold") or 0), step=1.0,
                        help="Uses the same unit as this item's quantity.")
                with col2:
                    edit_priority = st.selectbox("Priority", inventory.PRIORITIES, index=inventory.PRIORITIES.index(selected["priority"]))
                    def date_value(field: str):
                        raw = selected[field]
                        return date.fromisoformat(raw) if raw else None
                    edit_purchase = st.date_input("Purchase date", value=date_value("purchase_date"), key=f"purchase_{selected['id']}")
                    edit_use_by = st.date_input("Use-by date", value=date_value("use_by_date"), key=f"useby_{selected['id']}")
                    edit_best_before = st.date_input("Best-before date", value=date_value("best_before_date"), key=f"bestbefore_{selected['id']}")
                save = st.form_submit_button("Save changes", type="primary")
            if save:
                try:
                    inventory.update(selected["id"], {"name": edit_name, "quantity": edit_quantity, "unit": edit_unit,
                        "location": edit_location, "priority": edit_priority, "purchase_date": edit_purchase,
                        "use_by_date": edit_use_by, "best_before_date": edit_best_before,
                        "category": edit_category, "purchase_price": edit_purchase_price or None,
                        "reorder_threshold": edit_reorder_threshold or None})
                    st.success("Ingredient updated.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with tab_status:
            st.caption("Record the amount you actually used or discarded. PantryPilot tracks the remaining quantity and records discard reasons for your waste report.")
            action_label = st.radio("Record as", ("Used", "Discarded"), horizontal=True, key=f"record_action_{selected['id']}")
            amount_col, reason_col, record_col = st.columns([1, 2, 1])
            with amount_col:
                current_quantity = float(selected["quantity"])
                event_quantity = st.number_input("Amount", min_value=min(0.01, current_quantity), max_value=current_quantity,
                                                 value=current_quantity, step=min(0.1, current_quantity), key=f"record_quantity_{selected['id']}")
            event_reason = None
            with reason_col:
                if action_label == "Discarded":
                    reason_choice = st.selectbox("Why was it discarded?", waste_tracker.WASTE_REASONS,
                                                 key=f"discard_reason_{selected['id']}")
                    event_reason = None if reason_choice == "Not recorded" else reason_choice
                else:
                    st.caption(f"Current stock: {selected['quantity']:g} {selected['unit']}")
            with record_col:
                if st.button("Record amount", type="primary", width="stretch", key=f"record_stock_{selected['id']}"):
                    try:
                        restocked = inventory.consume(selected["id"], event_quantity, action_label.casefold(), reason=event_reason)
                        message = f"Recorded {event_quantity:g} {selected['unit']} as {action_label.casefold()}."
                        if action_label == "Used" and event_quantity >= float(selected["quantity"]) - 1e-9:
                            if restocked:
                                message += f" Added {selected['name']} to your shopping list for automatic restock."
                            else:
                                message += f" Another {selected['name']} batch is still in your kitchen, so no restock was added."
                        st.session_state["pantry_flash_message"] = message
                        st.rerun()
                    except (ValueError, LookupError) as exc:
                        st.error(str(exc))
                    except sqlite3.Error:
                        st.error("PantryPilot couldn't save the use record and its restock item. No changes were saved; check the database and try again.")
            with st.expander("Incorrect entry?", expanded=False):
                st.caption("Remove an incorrect record without counting it as food that was used or discarded.")
                if st.button("Remove incorrect entry", key=f"remove_ingredient_{selected['id']}"):
                    inventory.remove(selected["id"])
                    st.success("Entry removed.")
                    st.rerun()

elif page == "Discover Meals":
    app_features.render_discover_meals(items)
elif page == "Shopping List":
    app_features.render_shopping_list(items)
elif page == "My Impact":
    app_features.render_impact()

if page == "My Kitchen":
    with st.expander("Recently recorded used or discarded items"):
        history = database.get_inventory_events()
        if history:
            st.dataframe(pd.DataFrame([{"Ingredient": i["ingredient_name"], "Quantity": f"{i['quantity']:g} {i['unit']}",
                                        "Action": i["action"].capitalize(), "Reason": i.get("reason") or "—",
                                        "Value": f"${i['purchase_price']:.2f}" if i.get("purchase_price") is not None else "—",
                                        "Recorded": i["created_at"]} for i in history[:50]]),
                         hide_index=True, width="stretch")
        else:
            st.caption("No used or discarded items recorded yet.")

    with st.expander("Back up or export your PantryPilot data"):
        st.caption("These downloads stay on your device unless you choose to share them. Inventory and receipts can reveal household and purchase details; keep backup files private.")
        export_cols = st.columns(2)
        with export_cols[0]:
            inventory_csv = exports.inventory_csv(items)
            st.download_button("Download current inventory CSV", data=inventory_csv,
                               file_name="pantrypilot-inventory.csv", mime="text/csv", width="stretch")
        with export_cols[1]:
            database_path = database.resolve_db_path()
            backup = database.backup_database() if database_path.is_file() else b""
            backup_name = f"pantrypilot-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
            st.download_button("Download full SQLite backup", data=backup, file_name=backup_name,
                               mime="application/vnd.sqlite3", disabled=not backup, width="stretch")
        st.caption("A full backup includes your inventory, purchase history, shopping list and activity records.")
        st.markdown("**Restore from a PantryPilot backup**")
        st.warning("Restoring replaces the current pantry with the selected backup. Records created after that backup will no longer be in the active database. A recoverable copy of the current database will be saved beside it first.")
        restore_upload = st.file_uploader(
            "Choose a PantryPilot SQLite backup", type=["sqlite3", "sqlite", "db"],
            max_upload_size=100, help="Maximum 100 MB. The file is validated before the active database is changed.",
            key="restore_database_upload",
        )
        confirm_restore = st.checkbox(
            "I understand this will replace the active PantryPilot data.", key="confirm_database_restore"
        )
        if st.button("Validate backup and restore", type="primary",
                     disabled=restore_upload is None or not confirm_restore,
                     key="restore_database_submit"):
            try:
                restored_path = database.restore_database(restore_upload.getvalue(), database.resolve_db_path())
                st.session_state["pantry_flash_message"] = (
                    f"Backup restored to {restored_path.name}. A pre-restore recovery copy was saved beside it."
                )
                st.rerun()
            except (ValueError, OSError, sqlite3.Error) as exc:
                st.error(f"The backup could not be restored. Your current database was left in place. {exc}")
