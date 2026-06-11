"""Configuration loaded from environment variables / a local .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All connector settings. Populated from the environment or a `.env` file.

    See `.env.example` for the full list and how to obtain each value.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Salesforce: OAuth 2.0 JWT Bearer Flow (server-to-server) ---
    sf_client_id: str = Field(
        ..., description="Connected App consumer key — the JWT `iss` claim."
    )
    sf_username: str = Field(
        ..., description="Salesforce username to run as — the JWT `sub` claim."
    )
    sf_private_key_file: Path = Field(
        ..., description="Path to the RSA private key (PEM) that signs the JWT assertion."
    )
    sf_domain: str = Field(
        "login",
        description="'login' for production/developer orgs, 'test' for sandboxes.",
    )

    # --- Auditify: target product API ---
    auditify_base_url: str = Field(
        ...,
        description="Auditify public base URL, e.g. https://app.example.com (nginx fronts /api).",
    )
    auditify_access_token: str = Field(
        ...,
        description="Auditify JWT access token. Carries the tenant claim used for isolation.",
    )
