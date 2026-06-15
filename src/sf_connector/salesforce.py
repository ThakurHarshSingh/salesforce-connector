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
    if not (settings.sf_client_id and settings.sf_username and settings.sf_private_key_file):
        raise RuntimeError(
            "JWT auth needs SF_CLIENT_ID, SF_USERNAME and SF_PRIVATE_KEY_FILE. "
            "Or connect interactively with `sf-connector login`."
        )
    return Salesforce(
        username=settings.sf_username,
        consumer_key=settings.sf_client_id,
        privatekey_file=str(settings.sf_private_key_file),
        domain=settings.sf_domain,
    )


def list_objects(sf: Salesforce, queryable_only: bool = True) -> list[dict[str, Any]]:
    """List the org's sObjects ("tables").

    Returns each object's API name, human label, and whether it is queryable.
    This is the catalog a UI would show so a user can pick what to pull.
    """
    described = sf.describe()
    if not described:
        return []
    objects = [
        {
            "name": obj["name"],
            "label": obj["label"],
            "queryable": obj["queryable"],
        }
        for obj in described["sobjects"]
    ]
    if queryable_only:
        objects = [obj for obj in objects if obj["queryable"]]
    return sorted(objects, key=lambda obj: obj["name"])


def connect_with_token(instance_url: str, access_token: str) -> Salesforce:
    """Build a Salesforce client from an OAuth access token (the user-login flow).

    Used after a user connects via the Authorization Code flow: no private key,
    just the token Salesforce handed back. This is the path the product uses.
    """
    return Salesforce(instance_url=instance_url, session_id=access_token)


def connect_auto(settings: Settings) -> Salesforce:
    """Connect, preferring an OAuth login if one exists, else headless JWT.

    A cached OAuth token (from `login`) represents a real user "Connect
    Salesforce" session and takes precedence. If that session has expired, we
    transparently refresh it with the stored refresh token and re-cache the
    result — so a long-lived connection keeps working. Imported lazily to avoid
    a config/oauth import cycle at module load.
    """
    from .oauth import OAuthTokens, refresh_tokens

    if not settings.sf_token_cache.exists():
        return connect(settings)

    tokens = OAuthTokens.from_file(settings.sf_token_cache)
    if not _session_alive(tokens.instance_url, tokens.access_token):
        if not tokens.refresh_token:
            raise RuntimeError(
                "Salesforce session expired and no refresh token is cached. "
                "Run `sf-connector login` to reconnect."
            )
        tokens = refresh_tokens(settings, tokens.refresh_token)
        settings.sf_token_cache.write_text(tokens.to_json())
    return connect_with_token(tokens.instance_url, tokens.access_token)


def _session_alive(instance_url: str, access_token: str, timeout: float = 10.0) -> bool:
    """Bounded check of whether an access token is still valid.

    Hits `/services/oauth2/userinfo`, which *requires* a valid token (unlike
    `/services/data/`, which is unauthenticated) and is API-version agnostic.
    Uses a short timeout so a slow endpoint fails fast instead of hanging. A
    401/403 means the session expired and the caller should refresh; a network
    error is treated as "valid" so the real request surfaces the problem.
    """
    import httpx

    try:
        response = httpx.get(
            f"{instance_url}/services/oauth2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
    except httpx.HTTPError:
        return True
    return response.status_code not in (401, 403)


def count_records(sf: Salesforce, object_name: str) -> int:
    """Return the row count for one object (`SELECT COUNT() FROM <object>`).

    Counted lazily, per object, because Salesforce has no cheap bulk row-count:
    counting every object in an org would be hundreds of queries. A UI should
    count only the tables the user is actually considering.
    """
    return int(sf.query(f"SELECT COUNT() FROM {object_name}")["totalSize"])


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
