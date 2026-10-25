"""Backward-compatible entry points for PantryPilot receipt scanning.

The former module contained a second, obsolete extraction implementation with
an invalid response schema. Keep its public scanner names while routing all
work through the validated, consent-gated implementation in :mod:`scanner`.
"""

from __future__ import annotations

from pathlib import Path

from scanner import ReceiptScanError, scan_receipt_for_pantry


def scan_receipt(image: bytes | bytearray | str | Path, *, mime_type: str | None = None) -> dict:
    """Scan a receipt using the same validation and API safeguards as the app."""
    return scan_receipt_for_pantry(image, mime_type=mime_type)


def detect_items(image: bytes | bytearray | str | Path, *, mime_type: str | None = None) -> dict:
    """Legacy alias retained for existing scripts importing ``packagedetector``."""
    return scan_receipt(image, mime_type=mime_type)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Scan a grocery receipt image.")
    parser.add_argument("image", help="Path to a receipt photo")
    args = parser.parse_args()
    print(json.dumps(scan_receipt(args.image), indent=2))
