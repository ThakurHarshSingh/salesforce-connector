"""Orchestration: extract from Salesforce, build CSV, upload to Auditify."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import salesforce as sf
from .auditify import AuditifyClient
from .config import Settings
from .transform import records_to_csv


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
    folder_id: str | None = None,
    name: str | None = None,
    upload: bool = True,
) -> SyncResult:
    """Run one extract → transform → (optional) upload cycle.

    Provide either `soql` (a full query) or `object_name` (fields default to the
    object's full field set when omitted).
    """
    if not soql and not object_name:
        raise ValueError("Provide either `soql` or `object_name`.")

    connection = sf.connect(settings)

    if not soql:
        assert object_name is not None
        query_fields = fields or sf.all_fields(connection, object_name)
        soql = sf.build_soql(object_name, query_fields, where, limit)

    records = sf.query_records(connection, soql)
    csv_content = records_to_csv(records)

    label = object_name or "soql"
    filename = name or f"salesforce_{label}.csv"

    upload_response: dict[str, Any] | None = None
    if upload:
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
