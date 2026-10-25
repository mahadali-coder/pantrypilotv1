"""SQLite persistence for PantryPilot's household inventory."""

from __future__ import annotations

import os
import math
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from units import convert_quantity


DEFAULT_DB_PATH = Path(__file__).with_name("pantrypilot.db")


def resolve_db_path(path: str | Path | None = None) -> Path:
    """Resolve an explicit path, the environment override, or the app default."""
    return Path(path or os.environ.get("PANTRYPILOT_DB_PATH") or DEFAULT_DB_PATH)


def backup_database(path: str | Path | None = None) -> bytes:
    """Return a consistent SQLite backup snapshot without copying an active file directly."""
    source_path = resolve_db_path(path)
    if not source_path.is_file():
        raise FileNotFoundError("PantryPilot database was not found.")
    with tempfile.TemporaryDirectory(prefix="pantrypilot-backup-") as folder:
        target_path = Path(folder) / "backup.sqlite3"
        source = sqlite3.connect(str(source_path))
        target = sqlite3.connect(str(target_path))
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        return target_path.read_bytes()


def _validate_backup_file(path: Path) -> None:
    try:
        conn = sqlite3.connect(str(path))
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("The selected backup failed SQLite integrity validation.")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "ingredients" not in tables or "inventory_events" not in tables:
                raise ValueError("The selected file is not a PantryPilot database backup.")
            ingredient_columns = {row[1] for row in conn.execute("PRAGMA table_info(ingredients)")}
            event_columns = {row[1] for row in conn.execute("PRAGMA table_info(inventory_events)")}
            if not {"id", "name", "quantity", "unit", "location", "priority", "status"}.issubset(ingredient_columns):
                raise ValueError("The selected backup has an incompatible inventory schema.")
            if not {"id", "ingredient_name", "action", "quantity", "unit"}.issubset(event_columns):
                raise ValueError("The selected backup has an incompatible activity schema.")
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError("The selected file is not a valid SQLite backup.") from exc


def restore_database(backup: bytes, target_path: str | Path) -> Path:
    """Validate and atomically restore a backup to a separate or stopped-app DB path."""
    if not isinstance(backup, (bytes, bytearray)) or not backup:
        raise ValueError("Choose a non-empty PantryPilot database backup.")
    destination = resolve_db_path(target_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".pantrypilot-restore-", suffix=".sqlite3",
                                         dir=destination.parent, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(bytes(backup))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        _validate_backup_file(temp_path)
        recovery_backup = None
        if destination.is_file():
            # Preserve the current database beside it before replacing it. The
            # unique filename makes every successful restore independently reversible.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            recovery_backup = destination.with_name(
                f"{destination.stem}-pre-restore-{stamp}.sqlite3"
            )
            recovery_bytes = backup_database(destination)
            with recovery_backup.open("xb") as recovery_file:
                recovery_file.write(recovery_bytes)
                recovery_file.flush()
                os.fsync(recovery_file.fileno())
        os.replace(temp_path, destination)
        return destination
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


@contextmanager
def connection(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(path: str | Path | None = None) -> None:
    with connection(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit TEXT NOT NULL,
                location TEXT NOT NULL CHECK(location IN ('Refrigerator', 'Freezer', 'Pantry')),
                purchase_date TEXT,
                use_by_date TEXT,
                best_before_date TEXT,
                priority TEXT NOT NULL CHECK(priority IN ('Normal', 'Use First', 'Check Condition')),
                category TEXT NOT NULL DEFAULT 'Other',
                purchase_price REAL,
                reorder_threshold REAL CHECK(reorder_threshold IS NULL OR reorder_threshold >= 0),
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'used', 'discarded')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Additive migration keeps existing pantry databases and their rows.
        ingredient_columns = {row["name"] for row in conn.execute("PRAGMA table_info(ingredients)")}
        if "category" not in ingredient_columns:
            conn.execute("ALTER TABLE ingredients ADD COLUMN category TEXT NOT NULL DEFAULT 'Other'")
        if "purchase_price" not in ingredient_columns:
            conn.execute("ALTER TABLE ingredients ADD COLUMN purchase_price REAL")
        if "reorder_threshold" not in ingredient_columns:
            conn.execute("ALTER TABLE ingredients ADD COLUMN reorder_threshold REAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingredient_id INTEGER,
                ingredient_name TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('used', 'discarded')),
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                reason TEXT,
                purchase_price REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(inventory_events)")}
        if "reason" not in event_columns:
            conn.execute("ALTER TABLE inventory_events ADD COLUMN reason TEXT")
        if "purchase_price" not in event_columns:
            conn.execute("ALTER TABLE inventory_events ADD COLUMN purchase_price REAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminder_dismissals (
                ingredient_id INTEGER PRIMARY KEY,
                item_updated_at TEXT NOT NULL,
                dismissed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shopping_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'Manual',
                checked INTEGER NOT NULL DEFAULT 0 CHECK(checked IN (0,1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meal_cook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_name TEXT NOT NULL,
                ingredients_json TEXT NOT NULL,
                recommended INTEGER NOT NULL DEFAULT 0 CHECK(recommended IN (0,1)),
                operation_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        meal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(meal_cook_events)")}
        if "recommended" not in meal_columns:
            conn.execute("ALTER TABLE meal_cook_events ADD COLUMN recommended INTEGER NOT NULL DEFAULT 0")
        if "operation_id" not in meal_columns:
            conn.execute("ALTER TABLE meal_cook_events ADD COLUMN operation_id TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS meal_cook_events_operation_id ON meal_cook_events(operation_id) WHERE operation_id IS NOT NULL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_sessions (
                session_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_session_days (
                session_id TEXT NOT NULL,
                active_date TEXT NOT NULL DEFAULT (date('now')),
                PRIMARY KEY (session_id, active_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS receipt_purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_date TEXT,
                total_cost REAL CHECK(total_cost IS NULL OR total_cost >= 0),
                discount_total REAL CHECK(discount_total IS NULL OR discount_total >= 0),
                item_count INTEGER NOT NULL DEFAULT 0 CHECK(item_count >= 0),
                image_hash TEXT UNIQUE,
                reviewed_lines_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        receipt_columns = {row["name"] for row in conn.execute("PRAGMA table_info(receipt_purchases)")}
        if "image_hash" not in receipt_columns:
            conn.execute("ALTER TABLE receipt_purchases ADD COLUMN image_hash TEXT")
        if "discount_total" not in receipt_columns:
            conn.execute("ALTER TABLE receipt_purchases ADD COLUMN discount_total REAL")
        if "reviewed_lines_json" not in receipt_columns:
            conn.execute("ALTER TABLE receipt_purchases ADD COLUMN reviewed_lines_json TEXT NOT NULL DEFAULT '[]'")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS receipt_purchases_image_hash ON receipt_purchases(image_hash) WHERE image_hash IS NOT NULL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                recipe_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _log_activity(conn: sqlite3.Connection, description: str) -> None:
    conn.execute("INSERT INTO activity_log (description) VALUES (?)", (str(description)[:240],))


def _shopping_name_tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    words = re.findall(r"[a-z0-9]+", normalized)
    return frozenset(
        word[:-3] + "y" if len(word) > 4 and word.endswith("ies")
        else word[:-2] if len(word) > 4 and word.endswith("oes")
        else word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss")
        else word
        for word in words
    )


def _automatic_restock(conn: sqlite3.Connection, *, name: str, quantity: float,
                       unit: str, source: str) -> bool:
    """Add truly depleted food to the open list within the stock transaction."""
    item_tokens = _shopping_name_tokens(name)
    remaining_stock = conn.execute("SELECT name FROM ingredients WHERE status = 'active'").fetchall()
    if item_tokens and any(_shopping_name_tokens(row["name"]) == item_tokens for row in remaining_stock):
        return False
    rows = conn.execute("SELECT id, name, quantity, unit, source FROM shopping_list WHERE checked = 0").fetchall()
    for row in rows:
        converted = convert_quantity(quantity, unit, row["unit"])
        if item_tokens and item_tokens == _shopping_name_tokens(row["name"]) and converted is not None:
            sources = list(dict.fromkeys((row["source"] + "," + source).split(",")))
            new_quantity = float(row["quantity"]) + converted
            conn.execute("UPDATE shopping_list SET quantity = ?, source = ? WHERE id = ?",
                         (new_quantity, ",".join(sources), row["id"]))
            _log_activity(conn, f"Added depleted stock to shopping list: {row['name']} · +{converted:g} {row['unit']}")
            return True

    conn.execute("INSERT INTO shopping_list (name, quantity, unit, source) VALUES (?, ?, ?, ?)",
                 (name, quantity, unit, source))
    _log_activity(conn, f"Automatically added depleted stock to shopping list: {name} · {quantity:g} {unit}")
    return True


def _product_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", normalized))


def _same_inventory_batch(existing: dict, incoming: dict) -> bool:
    identity_fields = ("location", "purchase_date", "use_by_date", "best_before_date", "priority", "category", "reorder_threshold")
    return (_product_key(existing["name"]) == _product_key(incoming["name"])
            and all(existing.get(field) == incoming.get(field) for field in identity_fields))


def _insert_or_combine_ingredient(conn: sqlite3.Connection, data: dict) -> int:
    fields = ("name", "quantity", "unit", "location", "purchase_date", "use_by_date", "best_before_date", "priority", "category", "purchase_price", "reorder_threshold")
    candidates = conn.execute("SELECT * FROM ingredients WHERE status = 'active' AND location = ?", (data["location"],)).fetchall()
    for raw in candidates:
        existing = dict(raw)
        if not _same_inventory_batch(existing, data):
            continue
        if (existing.get("purchase_price") is None) != (data.get("purchase_price") is None):
            # Keep separately priced and unpriced quantities distinct rather
            # than implying that the known value covers the whole combined lot.
            continue
        converted = convert_quantity(float(data["quantity"]), data["unit"], existing["unit"])
        if converted is None:
            continue
        total = float(existing["quantity"]) + converted
        old_price, new_price = existing.get("purchase_price"), data.get("purchase_price")
        total_price = float(old_price) + float(new_price) if old_price is not None and new_price is not None else None
        conn.execute("UPDATE ingredients SET quantity = ?, purchase_price = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (total, total_price, existing["id"]))
        return int(existing["id"])
    cursor = conn.execute(
        f"INSERT INTO ingredients ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
        tuple(data.get(field, "Other" if field == "category" else None) for field in fields),
    )
    return int(cursor.lastrowid)


def add_ingredient(data: dict, path: str | Path | None = None) -> int:
    return add_ingredients([data], path)[0]


def add_ingredients(records: list[dict], path: str | Path | None = None, *, receipt: dict | None = None) -> list[int]:
    """Insert or combine compatible batches atomically and return their IDs."""
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ids = []
        for data in records:
            ids.append(_insert_or_combine_ingredient(conn, data))
            _log_activity(conn, f"Added stock: {data['name']} · {float(data['quantity']):g} {data['unit']}")
        if receipt is not None:
            try:
                import json
                reviewed_lines = json.dumps(receipt.get("reviewed_lines", []), ensure_ascii=False)
                conn.execute("INSERT INTO receipt_purchases (purchase_date, total_cost, discount_total, item_count, image_hash, reviewed_lines_json) VALUES (?, ?, ?, ?, ?, ?)",
                             (receipt.get("purchase_date"), receipt.get("total_cost"), receipt.get("discount_total"),
                              len(ids), receipt.get("image_hash"), reviewed_lines))
                _log_activity(conn, f"Imported receipt · {len(ids)} reviewed line(s)")
            except sqlite3.IntegrityError as exc:
                if receipt.get("image_hash"):
                    raise ValueError("This exact receipt photo has already been imported.") from exc
                raise
        return ids


def update_ingredient(ingredient_id: int, data: dict, path: str | Path | None = None) -> None:
    fields = ("name", "quantity", "unit", "location", "purchase_date", "use_by_date", "best_before_date", "priority", "category", "purchase_price", "reorder_threshold")
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        siblings = conn.execute("SELECT * FROM ingredients WHERE status = 'active' AND location = ? AND id <> ?",
                                (data["location"], ingredient_id)).fetchall()
        if any(_same_inventory_batch(dict(row), data)
               and convert_quantity(float(data["quantity"]), data["unit"], row["unit"]) is not None
               for row in siblings):
            raise ValueError("An equivalent active item already exists. Update that entry or change this item's details so the batches stay distinct.")
        cursor = conn.execute(
            f"UPDATE ingredients SET {', '.join(f'{field} = ?' for field in fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'active'",
            (*[data.get(field, "Other" if field == "category" else None) for field in fields], ingredient_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Active ingredient {ingredient_id} was not found")
        _log_activity(conn, f"Updated ingredient: {data['name']}")


def get_ingredients(path: str | Path | None = None, *, status: str = "active") -> list[dict]:
    with connection(path) as conn:
        rows = conn.execute("SELECT * FROM ingredients WHERE status = ? ORDER BY name COLLATE NOCASE, id", (status,)).fetchall()
        return [dict(row) for row in rows]


def remove_ingredient(ingredient_id: int, path: str | Path | None = None) -> None:
    with connection(path) as conn:
        row = conn.execute("SELECT name FROM ingredients WHERE id = ? AND status = 'active'", (ingredient_id,)).fetchone()
        cursor = conn.execute("DELETE FROM ingredients WHERE id = ? AND status = 'active'", (ingredient_id,))
        if cursor.rowcount == 0:
            raise LookupError(f"Active ingredient {ingredient_id} was not found")
        _log_activity(conn, f"Removed incorrect entry: {row['name']}")


def record_event(ingredient: dict, action: str, path: str | Path | None = None, *,
                 reason: str | None = None, quantity: float | None = None) -> bool:
    """Record a used/discarded quantity and reduce or close its active stock."""
    if action not in ("used", "discarded"):
        raise ValueError("Action must be used or discarded.")
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM ingredients WHERE id = ? AND status = 'active'", (ingredient["id"],)).fetchone()
        if row is None:
            raise LookupError(f"Active ingredient {ingredient['id']} was not found")
        current = dict(row)
        amount = float(current["quantity"] if quantity is None else quantity)
        current_quantity = float(current["quantity"])
        remaining = current_quantity - amount
        if not math.isfinite(amount) or amount <= 0 or remaining < -1e-9:
            raise ValueError("Recorded amount must be greater than zero and no more than the current quantity.")
        status = action if remaining <= 1e-9 else "active"
        new_quantity = max(remaining, 0) if status == "active" else current_quantity
        current_price = current.get("purchase_price")
        event_price = (float(current_price) * amount / current_quantity) if current_price is not None else None
        remaining_price = (float(current_price) - event_price) if current_price is not None and status == "active" else current_price
        cursor = conn.execute(
            "UPDATE ingredients SET quantity = ?, purchase_price = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'active' AND quantity = ?",
            (new_quantity, remaining_price, status, current["id"], current_quantity),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Active ingredient {ingredient['id']} was not found")
        conn.execute(
            "INSERT INTO inventory_events (ingredient_id, ingredient_name, action, quantity, unit, reason, purchase_price) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (current["id"], current["name"], action, amount, current["unit"], reason, event_price),
        )
        if action == "used" and status == "used":
            return _automatic_restock(conn, name=current["name"], quantity=amount, unit=current["unit"],
                                      source="Automatic restock after running out")
        return False


def record_cooked_meal(meal_name: str, ingredients: list[dict], path: str | Path | None = None,
                       *, recommended: bool = False, operation_id: str | None = None) -> int:
    """Atomically record a cooked meal and the user-entered inventory quantities it used."""
    import json

    operation_id = str(operation_id or "").strip() or None
    if operation_id is not None and len(operation_id) > 128:
        raise ValueError("Cooking operation ID must be 128 characters or fewer.")

    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if operation_id is not None:
            previous = conn.execute("SELECT id FROM meal_cook_events WHERE operation_id = ?", (operation_id,)).fetchone()
            if previous is not None:
                return int(previous["id"])
        recorded = []
        usage_by_ingredient: dict[int, float] = {}
        depleted_ingredients: dict[int, dict] = {}
        for use in ingredients:
            try:
                amount = float(use["quantity"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("Each amount used must be a number greater than zero.") from None
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError("Each amount used must be a finite number greater than zero.")
            row = conn.execute("SELECT * FROM ingredients WHERE id = ? AND status = 'active'", (use["id"],)).fetchone()
            if row is None:
                raise LookupError("A selected ingredient is no longer in your current inventory. Refresh and try again.")
            ingredient = dict(row)
            if amount > float(ingredient["quantity"]):
                raise ValueError(f"Amount for {ingredient['name']} exceeds its current quantity.")
            remainder = float(ingredient["quantity"]) - amount
            status = "used" if remainder <= 1e-9 else "active"
            new_quantity = float(ingredient["quantity"]) if status == "used" else remainder
            price = ingredient.get("purchase_price")
            used_price = (float(price) * amount / float(ingredient["quantity"])) if price is not None else None
            remaining_price = float(price) - used_price if price is not None and status == "active" else price
            conn.execute("UPDATE ingredients SET quantity = ?, purchase_price = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (new_quantity, remaining_price, status, ingredient["id"]))
            conn.execute("""
                INSERT INTO inventory_events (ingredient_id, ingredient_name, action, quantity, unit, reason, purchase_price)
                VALUES (?, ?, 'used', ?, ?, ?, ?)
            """, (ingredient["id"], ingredient["name"], amount, ingredient["unit"], f"Cooked: {meal_name}", used_price))
            ingredient_id = int(ingredient["id"])
            usage_by_ingredient[ingredient_id] = usage_by_ingredient.get(ingredient_id, 0.0) + amount
            if status == "used":
                depleted_ingredients[ingredient_id] = ingredient
            recorded.append({"name": ingredient["name"], "quantity": amount, "unit": ingredient["unit"]})
        for ingredient_id, ingredient in depleted_ingredients.items():
            _automatic_restock(conn, name=ingredient["name"], quantity=usage_by_ingredient[ingredient_id],
                               unit=ingredient["unit"], source=f"Automatic restock after cooking: {meal_name}")
        cursor = conn.execute("INSERT INTO meal_cook_events (meal_name, ingredients_json, recommended, operation_id) VALUES (?, ?, ?, ?)",
                              (meal_name, json.dumps(recorded), int(bool(recommended)), operation_id))
        return int(cursor.lastrowid)


def get_inventory_events(path: str | Path | None = None, *, action: str | None = None) -> list[dict]:
    with connection(path) as conn:
        if action:
            rows = conn.execute("SELECT * FROM inventory_events WHERE action = ? ORDER BY created_at DESC, id DESC", (action,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM inventory_events ORDER BY created_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]


def get_dismissed_reminders(path: str | Path | None = None) -> dict[int, str]:
    with connection(path) as conn:
        rows = conn.execute("SELECT ingredient_id, item_updated_at FROM reminder_dismissals").fetchall()
        return {int(row["ingredient_id"]): row["item_updated_at"] for row in rows}


def dismiss_reminder(ingredient_id: int, item_updated_at: str, path: str | Path | None = None) -> None:
    with connection(path) as conn:
        conn.execute("""
            INSERT INTO reminder_dismissals (ingredient_id, item_updated_at) VALUES (?, ?)
            ON CONFLICT(ingredient_id) DO UPDATE SET item_updated_at=excluded.item_updated_at, dismissed_at=CURRENT_TIMESTAMP
        """, (ingredient_id, item_updated_at))


def add_shopping_item(data: dict, path: str | Path | None = None) -> int:
    with connection(path) as conn:
        cursor = conn.execute("INSERT INTO shopping_list (name, quantity, unit, source) VALUES (?, ?, ?, ?)",
                               (data["name"], data["quantity"], data["unit"], data.get("source", "Manual")))
        _log_activity(conn, f"Added to shopping list: {data['name']} · {float(data['quantity']):g} {data['unit']}")
        return int(cursor.lastrowid)


def combine_shopping_item(item_id: int, *, quantity: float, source: str, path: str | Path | None = None) -> None:
    with connection(path) as conn:
        row = conn.execute("SELECT quantity, source FROM shopping_list WHERE id = ? AND checked = 0", (item_id,)).fetchone()
        if not row:
            raise LookupError("Open shopping-list item was not found")
        sources = list(dict.fromkeys((row["source"] + "," + source).split(",")))
        conn.execute("UPDATE shopping_list SET quantity = ?, source = ? WHERE id = ?",
                     (float(row["quantity"]) + float(quantity), ",".join(sources), item_id))
        _log_activity(conn, f"Combined shopping-list item · +{float(quantity):g}")


def get_shopping_items(path: str | Path | None = None) -> list[dict]:
    with connection(path) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM shopping_list ORDER BY checked, name COLLATE NOCASE, id")]


def update_shopping_item(item_id: int, *, quantity: float | None = None, unit: str | None = None,
                         checked: bool | None = None,
                         path: str | Path | None = None) -> None:
    assignments, values = [], []
    if quantity is not None:
        assignments.append("quantity = ?"); values.append(quantity)
    if unit is not None:
        assignments.append("unit = ?"); values.append(unit)
    if checked is not None:
        assignments.append("checked = ?"); values.append(int(checked))
    if not assignments:
        return
    values.append(item_id)
    with connection(path) as conn:
        current = conn.execute("SELECT name FROM shopping_list WHERE id = ?", (item_id,)).fetchone()
        if current is None:
            raise LookupError("Shopping-list item was not found")
        conn.execute(f"UPDATE shopping_list SET {', '.join(assignments)} WHERE id = ?", values)
        description = f"Updated shopping-list item: {current['name']}"
        if checked is not None:
            description = f"{'Marked purchased' if checked else 'Marked to buy'}: {current['name']}"
        _log_activity(conn, description)


def remove_shopping_item(item_id: int, path: str | Path | None = None) -> None:
    with connection(path) as conn:
        row = conn.execute("SELECT name FROM shopping_list WHERE id = ?", (item_id,)).fetchone()
        conn.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
        if row is not None:
            _log_activity(conn, f"Removed from shopping list: {row['name']}")


def purchase_checked_items(*, location: str, purchase_date: str, path: str | Path | None = None) -> int:
    """Move checked shopping rows into inventory as one atomic purchase."""
    if location not in ("Refrigerator", "Freezer", "Pantry"):
        raise ValueError("Choose a valid storage location.")
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT * FROM shopping_list WHERE checked = 1 ORDER BY id").fetchall()
        if not rows:
            raise ValueError("Mark at least one shopping-list item as purchased first.")
        for row in rows:
            _insert_or_combine_ingredient(conn, {
                "name": row["name"], "quantity": row["quantity"], "unit": row["unit"],
                "location": location, "purchase_date": purchase_date, "use_by_date": None,
                "best_before_date": None, "priority": "Normal", "category": "Other",
                "purchase_price": None, "reorder_threshold": None,
            })
            conn.execute("DELETE FROM shopping_list WHERE id = ?", (row["id"],))
            _log_activity(conn, f"Purchased: {row['name']} · {float(row['quantity']):g} {row['unit']}")
        return len(rows)


def add_meal_cook_event(meal_name: str, ingredients_json: str, path: str | Path | None = None,
                        *, recommended: bool = False) -> int:
    with connection(path) as conn:
        cursor = conn.execute("INSERT INTO meal_cook_events (meal_name, ingredients_json, recommended) VALUES (?, ?, ?)",
                               (meal_name, ingredients_json, int(bool(recommended))))
        return int(cursor.lastrowid)


def get_meal_cook_events(path: str | Path | None = None) -> list[dict]:
    with connection(path) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM meal_cook_events ORDER BY created_at DESC, id DESC")]


def get_recent_activity(path: str | Path | None = None, *, limit: int = 20) -> list[dict]:
    """Return persisted inventory, shopping, receipt, and cooking activity."""
    limit = max(1, min(int(limit), 200))
    with connection(path) as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT description AS text, created_at FROM activity_log ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )]
        rows.extend({"text": f"Recorded {row['action']}: {row['quantity']:g} {row['unit']} {row['ingredient_name']}",
                     "created_at": row["created_at"]}
                    for row in conn.execute("SELECT * FROM inventory_events ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)))
        rows.extend({"text": f"Cooked: {row['meal_name']}", "created_at": row["created_at"]}
                    for row in conn.execute("SELECT * FROM meal_cook_events ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)))
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return rows[:limit]


def record_app_session(session_id: str, path: str | Path | None = None) -> None:
    """Record one random local browser session; repeat reruns only update last_seen."""
    if not session_id or len(session_id) > 80:
        raise ValueError("Invalid local session identifier.")
    with connection(path) as conn:
        conn.execute("""
            INSERT INTO app_sessions (session_id) VALUES (?)
            ON CONFLICT(session_id) DO UPDATE SET last_seen_at = CURRENT_TIMESTAMP
        """, (session_id,))
        conn.execute("INSERT OR IGNORE INTO app_session_days (session_id) VALUES (?)", (session_id,))


def get_app_usage_summary(path: str | Path | None = None) -> dict:
    with connection(path) as conn:
        sessions = conn.execute("""SELECT (SELECT COUNT(*) FROM app_sessions) AS sessions,
                                (SELECT COUNT(DISTINCT active_date) FROM app_session_days) AS active_days,
                                (SELECT MAX(last_seen_at) FROM app_sessions) AS last_seen_at""").fetchone()
        meals = conn.execute("SELECT COUNT(*) AS total, SUM(recommended) AS recommended FROM meal_cook_events").fetchone()
        return {"sessions": int(sessions["sessions"] or 0), "active_days": int(sessions["active_days"] or 0),
                "last_seen_at": sessions["last_seen_at"], "meals_cooked": int(meals["total"] or 0),
                "recommended_meals_cooked": int(meals["recommended"] or 0)}


def get_receipt_purchases(path: str | Path | None = None) -> list[dict]:
    import json
    with connection(path) as conn:
        purchases = [dict(row) for row in conn.execute("SELECT * FROM receipt_purchases ORDER BY created_at DESC, id DESC")]
        for purchase in purchases:
            try:
                purchase["reviewed_lines"] = json.loads(purchase.pop("reviewed_lines_json", "[]"))
            except (TypeError, json.JSONDecodeError):
                purchase["reviewed_lines"] = []
        return purchases


def receipt_image_imported(image_hash: str, path: str | Path | None = None) -> bool:
    with connection(path) as conn:
        return conn.execute("SELECT 1 FROM receipt_purchases WHERE image_hash = ? LIMIT 1", (image_hash,)).fetchone() is not None


def save_recipe(recipe: dict, path: str | Path | None = None) -> int:
    import json
    with connection(path) as conn:
        existing = conn.execute("SELECT id FROM saved_recipes WHERE title = ?", (recipe["title"],)).fetchone()
        if existing:
            return int(existing["id"])
        cursor = conn.execute("INSERT INTO saved_recipes (title, recipe_json) VALUES (?, ?)",
                              (recipe["title"], json.dumps(recipe, ensure_ascii=False)))
        return int(cursor.lastrowid)


def get_saved_recipes(path: str | Path | None = None) -> list[dict]:
    import json
    with connection(path) as conn:
        return [{**dict(row), "recipe": json.loads(row["recipe_json"])}
                for row in conn.execute("SELECT * FROM saved_recipes ORDER BY created_at DESC, id DESC")]


def remove_saved_recipe(recipe_id: int, path: str | Path | None = None) -> None:
    with connection(path) as conn:
        conn.execute("DELETE FROM saved_recipes WHERE id = ?", (recipe_id,))
