"""Command-line interface for the Salesforce → Auditify connector."""

from __future__ import annotations

from pathlib import Path

import typer
from simple_salesforce import Salesforce  # type: ignore[attr-defined]

from . import oauth
from . import salesforce as sf
from .config import Settings
from .sync import run_sync

app = typer.Typer(
    help="Extract Salesforce records and upload them into Auditify.",
    no_args_is_help=True,
    add_completion=False,
)


def _load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]  # values come from env / .env
    except Exception as exc:  # pragma: no cover - thin error wrapper
        typer.secho(f"Configuration error: {exc}", fg="red", err=True)
        typer.secho("Copy .env.example to .env and fill it in.", fg="yellow", err=True)
        raise typer.Exit(1) from exc


def _connect(settings: Settings) -> Salesforce:
    """Connect to Salesforce, preferring an OAuth login if one exists."""
    return sf.connect_auto(settings)


@app.command()
def sync(
    object: str | None = typer.Option(
        None, "--object", "-o", help="Salesforce object API name, e.g. Account."
    ),
    fields: str | None = typer.Option(
        None, help="Comma-separated field names. Defaults to every field on the object."
    ),
    soql: str | None = typer.Option(
        None, help="Raw SOQL query. Overrides --object/--fields/--where/--limit."
    ),
    where: str | None = typer.Option(
        None, help="SOQL WHERE clause (without the WHERE keyword)."
    ),
    limit: int | None = typer.Option(None, help="Maximum number of records."),
    folder_id: str | None = typer.Option(
        None, help="Auditify folder external id to upload into."
    ),
    name: str | None = typer.Option(None, help="Override the uploaded file name."),
    output: Path | None = typer.Option(
        None, help="Also write the generated CSV to this local path."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Query and build the CSV but do not upload."
    ),
) -> None:
    """Extract records from Salesforce and upload them to Auditify as a CSV data source."""
    if not object and not soql:
        typer.secho("Provide --object or --soql.", fg="red", err=True)
        raise typer.Exit(2)

    settings = _load_settings()
    field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else None

    try:
        result = run_sync(
            settings,
            object_name=object,
            fields=field_list,
            soql=soql,
            where=where,
            limit=limit,
            folder_id=folder_id,
            name=name,
            upload=not dry_run,
        )
    except Exception as exc:
        typer.secho(f"Sync failed: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc

    typer.secho(
        f"✓ Extracted {result.record_count} record(s) from '{result.label}' "
        f"({len(result.csv_content)} bytes CSV).",
        fg="green",
    )

    if output:
        output.write_bytes(result.csv_content)
        typer.echo(f"  CSV written to {output}")

    if dry_run:
        typer.secho("  Dry run — nothing uploaded.", fg="yellow")
        return

    response = result.upload_response or {}
    source_id = response.get("id") or response.get("external_id") or "?"
    status = response.get("status", "?")
    typer.secho(f"  Uploaded to Auditify: id={source_id} status={status}", fg="green")


@app.command()
def login() -> None:
    """Connect a Salesforce account via the browser ("Connect Salesforce" flow).

    Opens Salesforce in your browser, you log in and click Allow, and the tokens
    are cached locally. This is the exact flow the product's frontend button uses.
    """
    settings = _load_settings()
    if not settings.sf_client_id or not settings.sf_client_secret:
        typer.secho(
            "Set SF_CLIENT_ID and SF_CLIENT_SECRET (Connected App consumer key/secret).",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)

    try:
        tokens = oauth.login(settings)
        connection = sf.connect_with_token(tokens.instance_url, tokens.access_token)
        org = connection.query("SELECT Id, Name FROM Organization LIMIT 1")
        org_name = org["records"][0]["Name"]
    except Exception as exc:
        typer.secho(f"✗ Login failed: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc

    typer.secho(f"✓ Connected to Salesforce org '{org_name}'.", fg="green")
    typer.echo(f"  Tokens cached at {settings.sf_token_cache}.")
    typer.echo("  Now run `sf-connector list-objects` to see the tables.")


@app.command(name="list-objects")
def list_objects(
    all: bool = typer.Option(
        False, "--all", help="Include non-queryable objects too."
    ),
    contains: str | None = typer.Option(
        None, help="Only show objects whose API name or label contains this text."
    ),
) -> None:
    """List the Salesforce objects ("tables") available in the connected org."""
    settings = _load_settings()

    try:
        connection = _connect(settings)
        objects = sf.list_objects(connection, queryable_only=not all)
    except Exception as exc:
        typer.secho(f"✗ Salesforce: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc

    if contains:
        needle = contains.lower()
        objects = [
            obj
            for obj in objects
            if needle in obj["name"].lower() or needle in obj["label"].lower()
        ]

    for obj in objects:
        typer.echo(f"{obj['name']:<40} {obj['label']}")
    typer.secho(f"\n{len(objects)} object(s).", fg="green")


@app.command()
def check() -> None:
    """Verify Salesforce authentication and that Auditify settings are present."""
    settings = _load_settings()

    try:
        connection = _connect(settings)
        org = connection.query("SELECT Id, Name FROM Organization LIMIT 1")
        org_name = org["records"][0]["Name"]
    except Exception as exc:
        typer.secho(f"✗ Salesforce: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc
    typer.secho(f"✓ Salesforce: authenticated to org '{org_name}'.", fg="green")

    typer.secho(
        f"✓ Auditify: base_url + access token configured ({settings.auditify_base_url}).",
        fg="green",
    )
    typer.echo("  (Upload is verified for real by `sync`.)")


if __name__ == "__main__":
    app()
