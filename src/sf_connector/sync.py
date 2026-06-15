"""Orchestration: extract from Salesforce, build CSV, upload to Auditify."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import salesforce as sf
from .auditify import AuditifyClient
from .config import Settings
from .transform import records_to_csv


def _apply_modified_since(where: str | None, modified_since: str | None) -> str | None:
    """AND a `SystemModstamp >= <instant>` filter onto an existing WHERE clause."""
    if not modified_since:
        return where
    clause = f"SystemModstamp >= {modified_since}"
    return f"({where}) AND {clause}" if where else clause


@dataclass
class SyncResult:
    label: str
    record_count: int
    csv_content: bytes
    upload_response: dict[str, Any] | None


def run_sync(
    settings: Settings,
    *,
    object_name: str | None = None,
    fields: list[str] | None = None,
    soql: str | None = None,
    where: str | None = None,
    limit: int | None = None,
    modified_since: str | None = None,
    folder_id: str | None = None,
    name: str | None = None,
    upload: bool = True,
) -> SyncResult:
    """Run one extract → transform → (optional) upload cycle.

    Provide either `soql` (a full query) or `object_name` (fields default to the
    object's full field set when omitted). `modified_since` (an ISO-8601 instant,
    e.g. 2026-06-01T00:00:00Z) filters to records changed since then — a simple
    incremental pull on top of the object's `SystemModstamp`.
    """
    if not soql and not object_name:
        raise ValueError("Provide either `soql` or `object_name`.")

    connection = sf.connect_auto(settings)

    if not soql:
        assert object_name is not None
        where = _apply_modified_since(where, modified_since)
        query_fields = fields or sf.all_fields(connection, object_name)
        soql = sf.build_soql(object_name, query_fields, where, limit)

    records = sf.query_records(connection, soql)
    csv_content = records_to_csv(records)

    label = object_name or "soql"
    filename = name or f"salesforce_{label}.csv"

    upload_response: dict[str, Any] | None = None
    if upload:
        if not settings.auditify_access_token:
            raise RuntimeError(
                "Uploading needs AUDITIFY_ACCESS_TOKEN. Use --dry-run to skip the upload."
            )
        with AuditifyClient(
            settings.auditify_base_url, settings.auditify_access_token
        ) as client:
            upload_response = client.upload_csv(filename, csv_content, folder_id=folder_id)

    return SyncResult(
        label=label,
        record_count=len(records),
        csv_content=csv_content,
        upload_response=upload_response,
    )
