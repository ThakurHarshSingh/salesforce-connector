"""Command-line interface for the Salesforce → Auditify connector."""

from __future__ import annotations

from pathlib import Path

import typer

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
def check() -> None:
    """Verify Salesforce authentication and that Auditify settings are present."""
    settings = _load_settings()

    try:
        connection = sf.connect(settings)
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
