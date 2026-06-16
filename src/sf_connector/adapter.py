"""The source-agnostic connector contract (irame Connector Build Spec §3.2, §6).

This is the interface every data source (Salesforce, SQL Server, Databricks, SAP)
implements so the irame platform sees one stable shape regardless of the source.

Read-only is enforced **by the shape of the interface**: there is no `write_rows`,
`execute`, or DDL method here, so no adapter has a code path to mutate a source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CanonicalType(StrEnum):
    """irame's canonical type set — every source's native types map into this (§6)."""

    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    TIMESTAMP = "TIMESTAMP"  # covers DATE / TIME / DATETIME


@dataclass
class Column:
    """One column of a table, with both its native and canonical type."""

    name: str
    canonical_type: CanonicalType
    native_type: str
    nullable: bool = True
    is_key: bool = False


@dataclass
class TableRef:
    """A reference to a table/object. catalog/schema are unused by flat sources."""

    name: str
    label: str | None = None
    schema: str | None = None
    catalog: str | None = None


@dataclass
class TableSchema:
    table: TableRef
    columns: list[Column]


@dataclass
class Capabilities:
    """What a source supports, so the framework can adapt behaviour and UI."""

    filter_pushdown: bool = False
    paging: bool = False
    incremental: bool = False
    catalogs: bool = False


@dataclass
class ConnectionResult:
    ok: bool
    detail: str = ""


@dataclass
class AuthSession:
    """An opaque, authenticated handle returned by `authenticate`.

    Source adapters subclass this to carry their own connection (a client, a
    token, a DB handle). The framework treats it as opaque.
    """


@dataclass
class ReadRequest:
    """A single read request — the only data operation in the whole contract."""

    table: str
    columns: list[str] = field(default_factory=list)  # empty => all columns
    filter: str | None = None
    order_by: str | None = None
    page_token: str | None = None
    page_size: int | None = None


@dataclass
class ReadResult:
    rows: list[dict[str, Any]]
    next_page_token: str | None = None


class NotSupported(Exception):
    """Raised by optional contract methods a given source does not support."""


class SourceAdapter(ABC):
    """The contract every source adapter implements (spec §3.2).

    Catalog/schema discovery is optional (Databricks, SQL Server use it; Salesforce
    does not) — sources that lack it leave the defaults, which raise NotSupported,
    and declare `catalogs=False` in capabilities().
    """

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Declare what this source supports."""

    # --- 1. Connect / authenticate ---
    @abstractmethod
    def authenticate(self) -> AuthSession:
        """Run the auth handshake (OAuth where applicable); return a session handle."""

    @abstractmethod
    def test_connection(self, session: AuthSession) -> ConnectionResult:
        """Validate that the session can reach the source."""

    # --- 2. Discovery (read-only metadata) ---
    def list_catalogs(self, session: AuthSession) -> list[str]:
        """Optional — sources without catalogs raise NotSupported."""
        raise NotSupported("This source has no catalogs.")

    def list_schemas(self, session: AuthSession, catalog: str | None = None) -> list[str]:
        """Optional — sources without schemas raise NotSupported."""
        raise NotSupported("This source has no schemas.")

    @abstractmethod
    def list_tables(self, session: AuthSession) -> list[TableRef]:
        """List every table/object the credentials are permitted to READ. REQUIRED."""

    @abstractmethod
    def describe_table(self, session: AuthSession, table: TableRef) -> TableSchema:
        """Return columns, canonical types, and keys for one table."""

    # --- 3. Read — the ONLY data path. No write method exists on this contract. ---
    @abstractmethod
    def read_rows(self, session: AuthSession, request: ReadRequest) -> ReadResult:
        """Read rows for one table, with optional filter/order/paging."""
