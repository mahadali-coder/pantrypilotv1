"""Vision-model receipt scanner used by PantryPilot's receipt import flow."""

from __future__ import annotations

import base64
from io import BytesIO
import json
import math
import mimetypes
from pathlib import Path


class ReceiptScanError(RuntimeError):
    """A receipt could not be scanned or validated."""


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "purchase_date": {"type": ["string", "null"]},
        "total_cost": {"type": ["number", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clean_name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "price": {"type": ["number", "null"]},
                    "category": {"type": "string"},
                },
                "required": ["clean_name", "quantity", "unit", "price", "category"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["purchase_date", "total_cost", "items"],
    "additionalProperties": False,
}


def _load_image(image: bytes | bytearray | str | Path, mime_type: str | None) -> tuple[bytes, str]:
    if isinstance(image, (str, Path)):
        image_path = Path(image)
        if not image_path.is_file():
            raise ReceiptScanError(f"Receipt image not found: {image_path}")
        image_bytes = image_path.read_bytes()
        mime_type = mime_type or mimetypes.guess_type(image_path.name)[0]
    else:
        image_bytes = bytes(image)

    if not image_bytes:
        raise ReceiptScanError("The receipt image is empty. Take or upload the photo again.")

    if mime_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        if image_bytes.startswith(b"\xff\xd8\xff"):
            mime_type = "image/jpeg"
        elif image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            mime_type = "image/png"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            mime_type = "image/webp"
        else:
            raise ReceiptScanError("Use a JPEG, PNG or WebP receipt photo.")
    return image_bytes, mime_type


def _validated_result(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ReceiptScanError("The scanner response was missing the item list. Try the photo again.")

    items = []
    for row in payload["items"]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("clean_name") or "").strip()
        unit = str(row.get("unit") or "item").strip()
        try:
            quantity = float(row.get("quantity", 1))
        except (TypeError, ValueError):
            continue
        if not name or not math.isfinite(quantity) or quantity <= 0:
            continue
        try:
            price = float(row["price"]) if row.get("price") is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and (not math.isfinite(price) or price < 0):
            price = None
        items.append({
            "clean_name": name[:120],
            "quantity": quantity,
            "unit": unit[:32] or "item",
            "price": price,
            "category": str(row.get("category") or "Other")[:40],
        })

    if not items:
        raise ReceiptScanError("No grocery items were detected. Try a clear photo showing the whole receipt.")

    purchase_date = payload.get("purchase_date")
    if not isinstance(purchase_date, str):
        purchase_date = None
    try:
        total_cost = float(payload["total_cost"]) if payload.get("total_cost") is not None else None
    except (TypeError, ValueError):
        total_cost = None
    if total_cost is not None and (not math.isfinite(total_cost) or total_cost < 0):
        total_cost = None
    return {"purchase_date": purchase_date, "total_cost": total_cost, "items": items}


def _receipt_images(image_bytes: bytes, mime_type: str) -> list[tuple[bytes, str, str]]:
    """Return the whole receipt plus overlapping sections for small printed rows."""
    try:
        from PIL import Image, ImageOps
        image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGB")
    except Exception:
        return [(image_bytes, mime_type, "Full receipt photo")]

    width, height = image.size
    if max(width, height) < 900:
        return [(image_bytes, mime_type, "Full receipt photo")]
    vertical = height >= width
    length = height if vertical else width
    section = max(1, math.ceil(length * 0.42))
    step = max(1, math.ceil(length * 0.34))
    starts = list(range(0, max(1, length - section + 1), step))
    last_start = max(0, length - section)
    if not starts or starts[-1] != last_start:
        starts.append(last_start)

    result = [(image_bytes, mime_type, "Full receipt photo; read purchase date and final total")]
    for index, start in enumerate(starts, start=1):
        box = (0, start, width, min(height, start + section)) if vertical else (start, 0, min(width, start + section), height)
        output = BytesIO()
        image.crop(box).save(output, format="JPEG", quality=92)
        orientation = "top-to-bottom" if vertical else "left-to-right"
        result.append((output.getvalue(), "image/jpeg", f"Overlapping detail section {index} of {len(starts)}, {orientation}"))
    return result


def scan_receipt_for_pantry(
    image: bytes | bytearray | str | Path,
    *,
    mime_type: str | None = None,
) -> dict:
    """Send a receipt photo to OpenAI and return validated reviewable item data.

    OpenAI credentials are read from OPENAI_API_KEY or this project's .env file.
    The receipt image is transmitted to the OpenAI API when this function runs.
    """
    image_bytes, mime_type = _load_image(image, mime_type)

    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise ReceiptScanError("OpenAI receipt scanning needs the project dependencies. Run `python -m pip install -r requirements.txt`, then restart PantryPilot.") from exc

    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=False)
    try:
        client = OpenAI()
    except Exception as exc:
        raise ReceiptScanError("OpenAI could not be initialized. Check that OPENAI_API_KEY is set in `.env` and restart PantryPilot.") from exc

    prompt = (
        "Read the grocery receipt shown in these images. The full image gives receipt context and its final total/date; "
        "overlapping detail sections make every product line easier to read. Return each visible food, drink, and genuine "
        "grocery good appropriate for a home inventory. Exclude bags, plastic recycling or deposits, containers, fees, "
        "discounts, payment records, loyalty messages, and other non-products. Transcribe every purchased product line, "
        "retaining brand and variety when legible. Count the quantity printed for each purchase: if a line says 2, return "
        "quantity 2, and do not collapse purchased units. Package size in a product name (such as 400 g) is not quantity. "
        "When no count or weight is printed, use quantity 1 and unit 'item'. Use the per-line price, not a subtotal. "
        "For total_cost, read the final amount explicitly labelled TOTAL / TOTAL AUD / AMOUNT DUE, not subtotal or savings; "
        "use null only if the final total cannot be read. If the same line appears in overlapping sections, include it once. "
        "Return JSON matching the required schema. Do not estimate expiry or food safety. Make sure to have the date of purchase as well."
    )
    content = [{"type": "text", "text": prompt}]
    for section_bytes, section_mime, label in _receipt_images(image_bytes, mime_type):
        encoded = base64.b64encode(section_bytes).decode("ascii")
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": f"data:{section_mime};base64,{encoded}", "detail": "high"}})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": content,
            }],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "grocery_receipt", "strict": True, "schema": _RESPONSE_SCHEMA},
            },
        )
        choice = response.choices[0]
        if choice.message.refusal:
            raise ReceiptScanError("The receipt could not be processed. Try another photo.")
        if choice.finish_reason != "stop" or not choice.message.content:
            raise ReceiptScanError("The receipt scan was incomplete. Try the photo again.")
        return _validated_result(json.loads(choice.message.content))
    except ReceiptScanError:
        raise
    except Exception as exc:
        # Avoid echoing request details or image data into the app UI.
        raise ReceiptScanError(f"OpenAI receipt scanning failed ({type(exc).__name__}). Check your API key and connection, then try again.") from exc


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scan a grocery receipt image.")
    parser.add_argument("image", help="Path to a receipt photo")
    args = parser.parse_args()
    print(json.dumps(scan_receipt_for_pantry(args.image), indent=2))
