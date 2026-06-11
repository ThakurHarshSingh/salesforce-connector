"""Thin client for Auditify's data-source ingestion endpoint."""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

# Direct multipart upload path. nginx fronts the backend under /api.
_UPLOAD_PATH = "/api/sources/upload"


class AuditifyClient:
    """Uploads CSV files to Auditify as data sources.

    Auth is a Bearer access token whose `tenant` claim scopes the upload to the
    right tenant — the connector never has to pass tenant identifiers itself.
    """

    def __init__(self, base_url: str, access_token: str, timeout: float = 120.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )

    def upload_csv(
        self,
        filename: str,
        content: bytes,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload one CSV file. Returns the registered data-source payload."""
        params = {"folder_id": folder_id} if folder_id else None
        files = {"file": (filename, content, "text/csv")}
        response = self._client.post(_UPLOAD_PATH, params=params, files=files)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AuditifyClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
