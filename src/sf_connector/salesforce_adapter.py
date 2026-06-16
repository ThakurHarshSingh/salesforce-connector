"""The Salesforce adapter (Connector Build Spec §7.2).

Implements the source-agnostic `SourceAdapter` contract by reusing the
Salesforce-specific logic already proven in `salesforce.py` and `oauth.py`:
OAuth auth-code + PKCE, `describeGlobal`/`describeSObject` discovery, and SOQL
reads with REST cursor paging. Read-only by construction — the contract has no
write methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simple_salesforce import Salesforce  # type: ignore[attr-defined]

from . import salesforce as sf
from .adapter import (
    AuthSession,
    CanonicalType,
    Capabilities,
    Column,
    ConnectionResult,
    ReadRequest,
    ReadResult,
    SourceAdapter,
    TableRef,
    TableSchema,
)
from .config import Settings

# Salesforce describe field "type" → irame canonical type (spec §6).
# Anything unmapped falls back to STRING.
_CANONICAL_BY_SF_TYPE: dict[str, CanonicalType] = {
    "string": CanonicalType.STRING,
    "picklist": CanonicalType.STRING,
    "multipicklist": CanonicalType.STRING,
    "combobox": CanonicalType.STRING,
    "id": CanonicalType.STRING,
    "reference": CanonicalType.STRING,
    "email": CanonicalType.STRING,
    "phone": CanonicalType.STRING,
    "url": CanonicalType.STRING,
    "textarea": CanonicalType.STRING,
    "encryptedstring": CanonicalType.STRING,
    "address": CanonicalType.STRING,
    "anyType": CanonicalType.STRING,
    "int": CanonicalType.INTEGER,
    "long": CanonicalType.INTEGER,
    "double": CanonicalType.DECIMAL,
    "currency": CanonicalType.DECIMAL,
    "percent": CanonicalType.DECIMAL,
    "boolean": CanonicalType.BOOLEAN,
    "date": CanonicalType.TIMESTAMP,
    "datetime": CanonicalType.TIMESTAMP,
    "time": CanonicalType.TIMESTAMP,
}


def canonical_type(sf_type: str) -> CanonicalType:
    """Map a Salesforce field type to the canonical type set (§6)."""
    return _CANONICAL_BY_SF_TYPE.get(sf_type, CanonicalType.STRING)


@dataclass
class SalesforceSession(AuthSession):
    """An authenticated Salesforce session — carries the connected client."""

    client: Salesforce


class SalesforceAdapter(SourceAdapter):
    """Salesforce as a read-only irame connector adapter."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def capabilities(self) -> Capabilities:
        # Salesforce is a flat object model (no catalogs/schemas); SOQL supports
        # WHERE/ORDER BY pushdown, REST cursor paging, and SystemModstamp incrementals.
        return Capabilities(
            filter_pushdown=True,
            paging=True,
            incremental=True,
            catalogs=False,
        )

    def authenticate(self) -> SalesforceSession:
        # Reuses connect_auto: a cached browser login (auth-code + PKCE) or JWT,
        # auto-refreshing an expired session. The browser login itself is `login`.
        return SalesforceSession(client=sf.connect_auto(self._settings))

    def test_connection(self, session: AuthSession) -> ConnectionResult:
        client = _client(session)
        org = client.query("SELECT Id, Name FROM Organization LIMIT 1")
        name = org["records"][0]["Name"]
        return ConnectionResult(ok=True, detail=f"Connected to org '{name}'.")

    def list_tables(self, session: AuthSession) -> list[TableRef]:
        client = _client(session)
        return [
            TableRef(name=obj["name"], label=obj["label"])
            for obj in sf.list_objects(client)
        ]

    def describe_table(self, session: AuthSession, table: TableRef) -> TableSchema:
        client = _client(session)
        described = getattr(client, table.name).describe()
        columns = [
            Column(
                name=fld["name"],
                canonical_type=canonical_type(fld["type"]),
                native_type=fld["type"],
                nullable=fld.get("nillable", True),
                is_key=fld["type"] == "id",
            )
            for fld in described["fields"]
        ]
        return TableSchema(table=table, columns=columns)

    def read_rows(self, session: AuthSession, request: ReadRequest) -> ReadResult:
        client = _client(session)
        # Continue an existing cursor, or start a new query.
        if request.page_token:
            result = client.query_more(request.page_token, identifier_is_url=True)
        else:
            columns = request.columns or sf.all_fields(client, request.table)
            soql = sf.build_soql(
                request.table,
                columns,
                where=request.filter,
                limit=request.page_size,
                order_by=request.order_by,
            )
            result = client.query(soql)

        rows = [_strip_attributes(record) for record in result["records"]]
        next_token = None if result.get("done", True) else result.get("nextRecordsUrl")
        return ReadResult(rows=rows, next_page_token=next_token)


def _client(session: AuthSession) -> Salesforce:
    if not isinstance(session, SalesforceSession):
        raise TypeError("SalesforceAdapter requires a SalesforceSession.")
    return session.client


def _strip_attributes(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "attributes"}
