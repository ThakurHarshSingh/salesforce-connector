# Auditify Salesforce Connector

A small, standalone CLI that pulls records out of **Salesforce** and uploads
them into **Auditify** as data sources. Run it on demand or on a schedule
(cron) — there is no server to host.

> This is a **separate** repository. It is not part of the Auditify application
> repo and imports nothing from it; it only talks to Auditify over its public
> HTTP API.

## How it works

```
Salesforce ──(SOQL, JWT bearer auth)──▶ connector ──(CSV, POST /api/sources/upload)──▶ Auditify
```

1. Authenticate to Salesforce with the **OAuth 2.0 JWT Bearer flow**
   (Connected App + private key — no passwords stored).
2. Run a SOQL query (or query an object's full field set) and follow pagination.
3. Serialise the records to CSV.
4. Upload the CSV to Auditify's data-source ingestion endpoint with an Auditify
   access token (its `tenant` claim scopes the upload to the right tenant).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Salesforce Connected App configured for the JWT bearer flow
- An Auditify access token carrying a tenant claim

## Install

```bash
uv sync          # creates .venv and installs the connector + dev tools
```

(or `pip install -e .` into a virtualenv)

## Configure

```bash
cp .env.example .env
# then edit .env
```

| Variable | What it is |
|---|---|
| `SF_CLIENT_ID` | Connected App **Consumer Key** (JWT issuer) |
| `SF_USERNAME` | Salesforce user the integration runs as (JWT subject) |
| `SF_PRIVATE_KEY_FILE` | Path to the RSA private key (PEM) paired with the cert on the Connected App |
| `SF_DOMAIN` | `login` (prod/dev orgs) or `test` (sandbox) |
| `AUDITIFY_BASE_URL` | Auditify public base URL (nginx routes `/api` to the backend) |
| `AUDITIFY_ACCESS_TOKEN` | Auditify JWT access token with a tenant claim |

### Salesforce Connected App setup (one time)

1. Generate a key pair:
   ```bash
   openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
     -keyout secrets/server.key -out secrets/server.crt \
     -subj "/CN=auditify-connector"
   ```
2. In Salesforce → **Setup → App Manager → New Connected App**:
   - Enable OAuth settings, check **Use digital signatures**, upload `server.crt`.
   - OAuth scopes: `api`, `refresh_token`.
3. Pre-authorise the integration user (Connected App → **Manage → Edit Policies →
   Permitted Users: Admin approved users**, then assign via a Permission Set/Profile).
4. Put `server.key` where `SF_PRIVATE_KEY_FILE` points (kept out of git).

## Usage

Verify connectivity:

```bash
uv run sf-connector check
```

Sync a whole object (all fields):

```bash
uv run sf-connector sync --object Account
```

Pick fields, filter, and limit:

```bash
uv run sf-connector sync \
  --object Contact \
  --fields "Id,FirstName,LastName,Email" \
  --where "Email != null" \
  --limit 1000
```

Raw SOQL, into a specific Auditify folder:

```bash
uv run sf-connector sync \
  --soql "SELECT Id, Subject, Status FROM Case WHERE IsClosed = false" \
  --folder-id <auditify-folder-external-id>
```

Preview without uploading (also save the CSV locally):

```bash
uv run sf-connector sync --object Account --dry-run --output ./accounts.csv
```

Run `uv run sf-connector sync --help` for all options.

## Quality gates

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

## Scope & scaling notes

- Uses the Salesforce **REST Query API** (`query_all`), which transparently
  pages through results — fine for typical exports up to ~hundreds of thousands
  of rows. For very large extracts, the Salesforce **Bulk API 2.0** is the next
  step; it would slot in behind the same `salesforce.query_records` boundary.
- Uploads use Auditify's direct multipart endpoint (`POST /api/sources/upload`),
  so no S3 staging is required. Ingestion is asynchronous on Auditify's side;
  this connector reports the registered data-source id and status.
