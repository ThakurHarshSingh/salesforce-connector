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

    # --- Salesforce: shared ---
    # The Connected App's Consumer Key. Shared by both auth flows below.
    sf_client_id: str | None = Field(
        None, description="Connected App consumer key."
    )
    sf_domain: str = Field(
        "login",
        description=(
            "'login' (prod/dev orgs), 'test' (sandboxes), or a full My Domain host "
            "such as 'mycompany.my.salesforce.com'."
        ),
    )

    @property
    def sf_login_base_url(self) -> str:
        """The Salesforce host used for OAuth, honouring custom My Domains.

        Accepts the 'login'/'test' shortcuts or a full My Domain host. Many orgs
        now require login via their My Domain rather than login.salesforce.com.
        """
        domain = self.sf_domain.strip()
        if "." in domain:
            host = domain if domain.endswith(".salesforce.com") else f"{domain}.salesforce.com"
        else:
            host = f"{domain}.salesforce.com"
        return f"https://{host}"

    # --- Salesforce: OAuth 2.0 Authorization Code flow (user clicks "Connect") ---
    # This is the flow behind a "Login with Salesforce" button.
    sf_client_secret: str | None = Field(
        None, description="Connected App consumer secret — used in the token exchange."
    )
    sf_redirect_uri: str = Field(
        "http://localhost:1717/callback",
        description="OAuth callback URL. Must match a Callback URL on the Connected App.",
    )

    # --- Salesforce: OAuth 2.0 JWT Bearer flow (headless, single integration user) ---
    sf_username: str | None = Field(
        None, description="Salesforce username to run as — the JWT `sub` claim."
    )
    sf_private_key_file: Path | None = Field(
        None, description="Path to the RSA private key (PEM) that signs the JWT assertion."
    )

    # --- Auditify: target product API ---
    auditify_base_url: str = Field(
        "http://localhost",
        description="Auditify public base URL, e.g. https://app.example.com (nginx fronts /api).",
    )
    auditify_access_token: str | None = Field(
        None,
        description="Auditify JWT access token. Carries the tenant claim used for isolation.",
    )

    # Where the OAuth login command caches the obtained tokens.
    sf_token_cache: Path = Field(
        Path(".sf_token.json"),
        description="Local file where `login` stores the OAuth tokens it obtains.",
    )
