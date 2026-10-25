# pantrypilotv1
Repo for v1 of Pantry Pilot

# PantryPilot 2.0

PantryPilot is a local-first household food inventory and waste-prevention prototype built with Python, Streamlit and SQLite. It helps people see what they have, decide what to use, plan simple meals, avoid duplicate shopping and record what gets used or discarded.

Priority labels and entered dates are reminders only. PantryPilot does not decide whether food is safe from its appearance or a date.

## Features

- **Inventory:** quick multi-item entry, receipt photo import, searchable stock, location and priority filters, dates, prices, editing and corrections. Single-item entry and receipt import suggest Refrigerator, Freezer or Pantry from product-name keywords; every suggestion can be overridden.
- **Smart storage suggestions:** frozen and frozen-fruit items suggest Freezer; dry goods and shelf-stable products suggest Pantry; other or unknown items default to Refrigerator. Quick entry can suggest locations line by line or apply one location to the whole batch. Receipt rows have an editable location per item. These are simple name-based suggestions, not product-database lookups.
- **Receipt import:** after explicit consent, a receipt image is sent to the OpenAI API. The scanner reads a final total/date and product lines. Review the printed product row beside each editable quantity, correct the receipt date, and check the result before import. Imported receipt totals are retained in local purchase history. JPEG, PNG and WebP images are validated and limited to 15 MB and 40 megapixels; OpenAI calls have a 45-second timeout and bounded transient retries.
- **Package date capture:** scan a close-up photo of a food package label to transcribe a clearly printed use-by or best-before date. The app checks that the model's ISO date agrees with visible Australian day-first or textual date text and that matching date wording is present. Verify the result in the item editor and save it. This photo is sent to OpenAI only after consent.
- **Food attention list:** reminders use recorded use-by and best-before dates, user priorities, and storage location. Freezer and pantry context raises a review reminder about storage history or package instructions; it does not predict shelf life or decide whether food is safe. Dismissal lasts until relevant item details change.
- **Explainable meal ranking:** generated recipe options are ranked locally using Use First stock, name/ID matches to pantry items, required missing ingredients, optional items and estimated time. Each option explains the factors behind its rank. Name matches do not confirm stock amounts or substitutions; review them.
- **AI meal ideas:** users choose pantry ingredients and preferences, then consent to send only those selected names, quantities and preferences to OpenAI for generated recipe options. Results distinguish selected ingredients from possible pantry matches and additional ingredients, show steps and time, and can add needed ingredients to the shopping list. Users can optionally record a cooked meal and reduce selected stock using explicitly entered amounts in their inventory units.
- **Shopping list:** add items manually or from missing meal essentials, check similar names against current inventory, optionally override a duplicate warning, merge repeated ingredients with compatible units, edit quantities and units, mark items purchased, and remove entries.
- **Purchase-to-pantry flow:** check off bought items, choose a storage location, then add them to inventory with today's purchase date in one step.
- **Restock alerts:** set an optional per-item minimum quantity. Home shows items at or below their threshold and can add them to the shopping list. Thresholds use that item's own unit.
- **Saved AI recipes and serving size:** request recipes for 1–8 servings, save generated recipes locally, and reopen or remove them later. Recipe amounts are proportionally scaled from the generated serving count; review quantities before cooking.
- **Duplicate receipt guard:** the exact same receipt image cannot be committed twice. The app stores a one-way SHA-256 image fingerprint, not the receipt photo.
- **Receipt reconciliation:** compare the receipt total with reviewed line amounts and an optional receipt-level discount. Mismatches and unknown values require acknowledgment; the app does not invent or distribute price differences. Reviewed line text and corrections are retained in local receipt history; the photo is not.
- **Data integrity:** matching product batches with the same location, dates, priority and category combine only when their units can be converted. Different dates or incompatible units remain separate. Cooking and use/discard events update inventory and history atomically; partial use reduces recorded purchase value proportionally.
- **Waste and use history:** record partial or full quantities used/discarded, choose a discard reason and view recent counts, reasons, meal logs and purchase values allocated from recorded prices. These recorded amounts are not claims of savings or impact.
- **Local value measures:** count local browser sessions, active days, recommended meals logged as cooked, and recorded discard events over adjacent periods. No data leaves the device for these measures. They describe recorded activity only and do not establish retention across people or prove reduced household waste.
- **Data ownership:** download the current inventory as CSV or the complete SQLite database as a backup; restore a validated backup from the same screen after explicit confirmation. A pre-restore copy is saved beside the active database.
- **Local persistence:** ingredients, shopping list, receipts, meal logs and events are stored in SQLite on this computer.
- **Recent activity:** additions, edits, removals, shopping changes, use/discard records, cooking and receipt imports are recorded locally and shown on Home.

### Current screens and workflows

- **Home:** live inventory and attention counts, food-attention reminders, per-item restock alerts, recent persisted activity, and working shortcuts to add or scan groceries, generate recipes, and open the shopping list.
- **My Kitchen:** quick multi-item entry with smart locations; detailed single-item entry; consent-based receipt preview, scanning and review; search, filters and sorting; per-item date-label scanning; editing, partial use/discard tracking, incorrect-entry removal, CSV export, and full database backup.
- **Discover Meals:** consent-based AI recipe generation from selected pantry items, dietary preferences, time and serving size; save or reopen generated recipes; add missing ingredients to shopping; optionally log cooking and user-entered stock usage.
- **Shopping List:** add or combine items, detect likely pantry matches, check off purchases, transfer checked items into inventory with a location and purchase date, and remove list items.
- **My Impact:** review recorded use/discard events and reasons, recorded values, meal logs, receipt totals and purchase history. These are based only on recorded data.

## Requirements

- Python 3.10 or newer
- pip
- An OpenAI API key with API access enabled for receipt scanning (other features work without scanning)

## Setup

From the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## OpenAI API key

Receipt photos are sent to the OpenAI API only after the user agrees in the app and clicks **Read receipt**. AI recipe generation likewise requires explicit agreement in Discover Meals and sends selected item names, quantities, units, priority labels and preferences. Put the key in the project `.env` file:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

If needed, copy `.env.example` to `.env` and replace the placeholder. Keep `.env` private; it is ignored by Git.

On macOS or Linux, initialize the optional key file with `cp .env.example .env` and edit `.env`. Restart Streamlit after changing the key. Do not paste API keys into chat or commit them.

## Launch

```sh
source .venv/bin/activate
streamlit run app.py
```

Open the local URL printed by Streamlit, usually http://localhost:8501. The database is created as `pantrypilot.db` beside the app. To use another database file:

```sh
PANTRYPILOT_DB_PATH="$PWD/data/pantry.sqlite3" streamlit run app.py
```

## Tests

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Tests use temporary databases and do not modify the default pantry.

## Design

The current UI follows the supplied Fridge Food Figma guide, with Home, My Kitchen, Discover Meals, Shopping List and My Impact views. The source SVGs and implementation notes are retained in `design/fridge-food-figma/` and `design/FIGMA_GUIDE.md`. Receipt import and package-date photo scanning remain available as optional AI-assisted entry methods with consent and review.

## Backup and restore

In **My Kitchen → Back up or export your PantryPilot data**, download the full SQLite backup and save it somewhere separate from the project. To restore, select the downloaded backup in the restore section, check the replacement confirmation and submit. PantryPilot validates the database before replacing the active one and saves the current database beside it as a uniquely named `*-pre-restore-*.sqlite3` recovery copy. Restoring replaces active data with the selected snapshot, so later records will no longer appear in the active database. Keep both files private.

## Troubleshooting

- If Streamlit is missing, activate `.venv` and run `python -m pip install -r requirements.txt`.
- If AI scanning or recipe generation is unavailable, check the optional `OPENAI_API_KEY`, account permissions and quota. Local inventory and shopping features work without it.
- If port 8501 is occupied, run `streamlit run app.py --server.port 8502` and open the URL Streamlit prints.
- Tests use temporary databases. To run one test module, use `python -m unittest discover -s tests -p 'test_inventory.py' -v`.

## Current boundaries

PantryPilot is a single-device local prototype. It has no user accounts, household sharing, hosted deployment, cloud sync, scheduled notifications, barcode/product catalog integration, grocery-store account connection, payment system or nutritional analysis. Receipt extraction, package-date reading and AI-generated recipes can be wrong; review extracted items, quantities, dates, ingredients, substitutions and food-handling guidance yourself. Package-date validation checks consistency and explicit date wording but does not verify that the AI read the pixels correctly. Dietary checks reject common explicit ingredient conflicts but cannot certify labels, preparation methods or cross-contamination. Duplicate receipt detection catches identical image bytes only; a re-photographed or cropped receipt can still be imported. Keep exports and backups private because they contain inventory and purchase history. Saved recipes and restock thresholds are included in the SQLite backup.

Generated recipe amounts do not prove that the selected stock contains enough food; recipe quantity requirements are not converted into pantry stock requirements. Recorded purchase values depend on prices entered or extracted and are only estimates. Recipe ranking is a transparent heuristic, not a calibrated recommender. The local session and discard measures are not a controlled retention or waste-reduction study. Receipt total comparison may include non-food items, tax, deposits or unallocated promotions, so a difference needs user review.

## Roadmap-informed validation

Before selling or making waste-reduction claims, test with households using their real groceries. Measure the time and corrections needed for inventory and receipt entry, whether people return, which suggestions they cook, how often reminders help, and whether waste records change over time. Compare the workflow with existing products and revise it based on what users value. The counters in My Impact are instrumentation for that evaluation, not proof of value on their own.
