"""Salesforce access: JWT-bearer authentication and SOQL extraction."""

from __future__ import annotations

from typing import Any

from simple_salesforce import Salesforce  # type: ignore[attr-defined]

from .config import Settings

# Field types that cannot appear in a SOQL SELECT list and must be skipped when
# we auto-discover an object's fields.
_NON_QUERYABLE_TYPES = {"base64"}


def connect(settings: Settings) -> Salesforce:
    """Authenticate using the OAuth 2.0 JWT Bearer flow.

    No password is stored or transmitted: the Connected App's private key signs
    a short-lived assertion that Salesforce exchanges for an access token. This
    is the standard headless server-to-server auth pattern.
    """
    return Salesforce(
        username=settings.sf_username,
        consumer_key=settings.sf_client_id,
        privatekey_file=str(settings.sf_private_key_file),
        domain=settings.sf_domain,
    )


def all_fields(sf: Salesforce, object_name: str) -> list[str]:
    """Return every queryable field name for an sObject (via describe)."""
    describe = getattr(sf, object_name).describe()
    return [
        field["name"]
        for field in describe["fields"]
        if field["type"] not in _NON_QUERYABLE_TYPES
    ]


def build_soql(
    object_name: str,
    fields: list[str],
    where: str | None = None,
    limit: int | None = None,
) -> str:
    """Assemble a SOQL query from parts."""
    soql = f"SELECT {', '.join(fields)} FROM {object_name}"
    if where:
        soql += f" WHERE {where}"
    if limit:
        soql += f" LIMIT {limit}"
    return soql


def query_records(sf: Salesforce, soql: str) -> list[dict[str, Any]]:
    """Run a SOQL query, transparently following pagination, and drop Salesforce
    bookkeeping (`attributes`) from each record."""
    result = sf.query_all(soql)
    return [_clean(record) for record in result["records"]]


def _clean(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "attributes"}
