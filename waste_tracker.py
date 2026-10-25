"""Waste-history summaries from user-recorded discard events."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

import database

WASTE_REASONS = (
    "Date passed (recorded)",
    "Spoiled or damaged",
    "Cooked too much",
    "Bought too much",
    "Leftovers not eaten",
    "Other",
    "Not recorded",
)


def get_waste_events(db_path: str | Path | None = None) -> list[dict]:
    return database.get_inventory_events(db_path, action="discarded")


def summarize_usage(events: list[dict], *, days: int = 30, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    recent = []
    for event in events:
        try:
            created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (KeyError, AttributeError, ValueError):
            continue
        if created >= cutoff:
            recent.append(event)
    priced = [float(event["purchase_price"]) for event in recent if event.get("purchase_price") is not None]
    return {
        "event_count": len(recent),
        "recorded_value": sum(priced) if priced else None,
        "events_with_value": len(priced),
    }


def weekly_waste_trend(events: list[dict], *, weeks: int = 8, now: datetime | None = None) -> list[dict]:
    """Count recorded discard events by week for a simple trend chart."""
    now = now or datetime.now(timezone.utc)
    current_week = now.date() - timedelta(days=now.weekday())
    starts = [current_week - timedelta(weeks=offset) for offset in reversed(range(weeks))]
    counts = Counter()
    for event in events:
        try:
            created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (KeyError, AttributeError, ValueError):
            continue
        start = created.date() - timedelta(days=created.weekday())
        if start in starts:
            counts[start] += 1
    return [{"Week of": start.strftime("%d %b"), "Discard events": counts[start]} for start in starts]


def summarize_waste(events: list[dict], *, days: int = 30, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    recent = []
    for event in events:
        raw = event.get("created_at")
        try:
            created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (AttributeError, ValueError):
            continue
        if created >= cutoff:
            recent.append(event)
    reasons = Counter(event.get("reason") or "Not recorded" for event in recent)
    products = Counter(event.get("ingredient_name", "Unknown") for event in recent)
    quantity_by_unit = Counter()
    recorded_value = 0.0
    events_with_value = 0
    for event in recent:
        quantity_by_unit[event.get("unit", "item")] += float(event.get("quantity", 0))
        if event.get("purchase_price") is not None:
            recorded_value += float(event["purchase_price"])
            events_with_value += 1
    return {
        "days": days,
        "event_count": len(recent),
        "product_count": len(products),
        "reasons": reasons,
        "products": products,
        "quantity_by_unit": quantity_by_unit,
        "recorded_value": recorded_value if events_with_value else None,
        "events_with_value": events_with_value,
        "events": recent,
    }


def compare_recorded_waste(events: list[dict], *, days: int = 30,
                           now: datetime | None = None) -> dict:
    """Compare adjacent windows of logged discard activity, without claiming causation."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    windows = {
        "current": (now - timedelta(days=days), now),
        "previous": (now - timedelta(days=days * 2), now - timedelta(days=days)),
    }
    results = {}
    for label, (start, end) in windows.items():
        rows = []
        for event in events:
            try:
                created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except (KeyError, AttributeError, ValueError):
                continue
            if start <= created < end:
                rows.append(event)
        quantity_by_unit = Counter()
        products = Counter()
        recorded_value = 0.0
        value_count = 0
        for event in rows:
            try:
                amount = float(event.get("quantity", 0))
            except (TypeError, ValueError):
                amount = 0
            if math.isfinite(amount):
                quantity_by_unit[event.get("unit") or "item"] += amount
            products[event.get("ingredient_name") or "Unknown"] += 1
            try:
                value = float(event["purchase_price"])
                if math.isfinite(value):
                    recorded_value += value
                    value_count += 1
            except (KeyError, TypeError, ValueError):
                pass
        results[label] = {"event_count": len(rows), "quantity_by_unit": quantity_by_unit,
                          "products": products, "recorded_value": recorded_value if value_count else None,
                          "events_with_value": value_count}
    return results
