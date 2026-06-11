"""Turn Salesforce records into a CSV payload Auditify can ingest."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def records_to_csv(records: list[dict[str, Any]]) -> bytes:
    """Serialise records to UTF-8 CSV bytes.

    The header is the union of every record's keys (in first-seen order), so a
    record missing a field still lines up. Nested values (from relationship
    queries) are JSON-encoded into a single cell.
    """
    if not records:
        return b""

    fieldnames = list(dict.fromkeys(key for record in records for key in record))

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow({key: _stringify(record.get(key)) for key in fieldnames})
    return buffer.getvalue().encode("utf-8")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)
