"""Food attention reminders based on user labels and recorded dates, never safety verdicts."""

from __future__ import annotations

from datetime import date
import json
import database

USE_BY_WARNING_DAYS = 3
BEST_BEFORE_WARNING_DAYS = 7


def _version(item: dict) -> str:
    return json.dumps({key: item.get(key) for key in (
        "id", "name", "quantity", "unit", "location", "priority", "use_by_date", "best_before_date"
    )}, sort_keys=True)


def build_attention_list(items: list[dict], *, today: date | None = None,
                         dismissed: dict[int, str] | None = None, db_path=None) -> list[dict]:
    today = today or date.today()
    dismissed = dismissed if dismissed is not None else database.get_dismissed_reminders(db_path)
    attention = []
    for item in items:
        reasons = []
        score = 0
        if item["priority"] == "Use First":
            reasons.append("You marked this Use First.")
            score += 100
        elif item["priority"] == "Check Condition":
            reasons.append("You marked this to check condition.")
            score += 70
        active_date_alerts = []
        for date_field, label, warning_window, base_score in (
            ("use_by_date", "use-by", USE_BY_WARNING_DAYS, 90),
            ("best_before_date", "best-before", BEST_BEFORE_WARNING_DAYS, 45),
        ):
            raw_date = item.get(date_field)
            if not raw_date:
                continue
            try:
                recorded_date = date.fromisoformat(raw_date)
                days = (recorded_date - today).days
                if days < 0:
                    reasons.append(f"Your recorded {label} date was {abs(days)} day{'s' if abs(days) != 1 else ''} ago.")
                    score = max(score, base_score + min(abs(days), 30))
                    active_date_alerts.append(label)
                elif days <= warning_window:
                    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
                    reasons.append(f"Your recorded {label} date is {when}.")
                    score = max(score, base_score - days)
                    active_date_alerts.append(label)
            except ValueError:
                pass
        if not reasons:
            continue
        location = item.get("location")
        if active_date_alerts and location:
            if location == "Freezer":
                reasons.append("Stored in the freezer: check that the recorded package date applies to this product's storage and freeze history.")
                # This is a review-priority adjustment for date uncertainty,
                # not an assumption that frozen food expires sooner or later.
                score += 8
            elif location == "Pantry":
                reasons.append("Stored in the pantry: check the package's storage instructions, especially if it has been opened.")
                score += 4
            else:
                reasons.append("Stored in the refrigerator. This reminder uses your entered date and does not account for storage history.")
        if dismissed.get(int(item["id"])) == _version(item):
            continue
        attention.append({**item, "reasons": reasons, "_score": score, "_version": _version(item)})
    attention.sort(key=lambda item: (
        -item["_score"], item.get("use_by_date") or item.get("best_before_date") or "9999-12-31", item["name"].casefold()
    ))
    return attention


def dismiss(item: dict, db_path=None) -> None:
    database.dismiss_reminder(int(item["id"]), item.get("_version") or _version(item), db_path)
