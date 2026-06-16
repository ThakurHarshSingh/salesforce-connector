# Auditify Salesforce Connector

A standalone connector that lets a user **connect their Salesforce account**
(the same UX as "Login with Google"), lists the objects/tables in their org, and
pulls records out into **Auditify** as data sources. It ships as a CLI today; the
OAuth login logic is written so the product backend can reuse it directly behind a
**"Connect Salesforce"** button.

> Separate repository — it imports nothing from the Auditify app and only talks to
> Auditify over its public HTTP API.

## What this proves / what it's for

- **Connect:** a user logs into Salesforce in the browser and consents — no admin
  setup, no credentials handed to us. (OAuth 2.0 Authorization Code + PKCE.)
- **Discover:** we read the list of objects ("tables") available in their org.
- **Fetch (read-only):** we extract records via SOQL and write them to CSV / upload
  to Auditify.

There are **two** ways to authenticate, for two different situations:

| | **OAuth login** (product flow) | **JWT bearer** (headless) |
|---|---|---|
| Who authorizes | Each end-user, in the browser | One integration user, set up once by an admin |
| Looks like | "Login with Google" | A backend service account |
| Use it for | Customers self-connecting their own org | An unattended cron job against a single org you own |
| Command | `sf-connector login` | `sf-connector check` / `sync` with a private key |

The product uses the **OAuth login** flow. JWT is kept for headless/scheduled runs.

---

## Quickstart — test the "Connect Salesforce" flow

What you need: a Salesforce org (a free [Developer Edition](https://developer.salesforce.com/signup)
works) and ~15 minutes.

### 1. Register one app in Salesforce (done once, by us — never by end-users)

Like registering your app once in Google Cloud Console for "Login with Google",
you create **one** app and every user just clicks through it. Either
**Connected App** or the newer **External Client App** works.

In Salesforce → **Setup**:

1. Create the app (e.g. **External Client App Manager → New**, or **App Manager → New Connected App**).
2. **Enable OAuth**, and set:
   - **Callback URL:** `http://localhost:1717/callback` (for local testing — add your
     real backend callback URL for production).
   - **OAuth scopes:** `Manage user data via APIs (api)` and
     `Perform requests at any time (refresh_token)`.
   - **PKCE:** leave **Require PKCE enabled** (the connector sends a PKCE challenge).
   - Do **not** enable "Use digital signatures" (that's only for the JWT flow).
3. Open **Consumer Details** (or the app's OAuth settings) and copy the
   **Consumer Key** and **Consumer Secret**.

### 2. Configure

```bash
uv sync                 # install
cp .env.example .env     # then edit .env
```

Set these four values in `.env` (it is git-ignored — never commit it):

```ini
SF_CLIENT_ID=<your Consumer Key>
SF_CLIENT_SECRET=<your Consumer Secret>
SF_REDIRECT_URI=http://localhost:1717/callback
SF_DOMAIN=login          # 'login' for prod/dev orgs, 'test' for sandboxes
```

### 3. Connect and list tables

```bash
uv run sf-connector login          # opens the browser → log in → Allow
uv run sf-connector list-objects   # prints the objects/tables in the org
```

`login` should end with `✓ Connected to Salesforce org '<name>'`. Tokens are
cached locally in `.sf_token.json` (git-ignored), so `list-objects` and `sync`
reuse the session automatically.

> **"Why ~500 tables when I never created any?"** Those are Salesforce's built-in
> **standard objects** (`Account`, `Contact`, `Lead`, `Opportunity`, plus system
> tables) — every org ships with them, like `information_schema` in a fresh
> database. Your own **custom objects** would appear with names ending in `__c`.

### 4. (Optional) prove real rows come through

```bash
uv run sf-connector sync --object Account --dry-run --limit 5 --output ./account_sample.csv
```

Open `account_sample.csv` — live records pulled from Salesforce.

---

## For the team building the product

This repo is a runnable **reference implementation**. The complete plan for what to
build to ship this at production scale — architecture, the database/multi-tenant model,
the backend API endpoints, the security model, and a readiness checklist — is in:

**➡️ [docs/PRODUCTION_HANDOFF.md](docs/PRODUCTION_HANDOFF.md) — read this first.**

In short, the backend wraps [`oauth.py`](src/sf_connector/oauth.py) and the
[`SourceAdapter`](src/sf_connector/adapter.py) in two OAuth endpoints
(`/connect/salesforce`, `/oauth/callback`) plus a read API, backed by a per-tenant
database. Full detail in the handoff doc.

---

## CLI reference

| Command | What it does |
|---|---|
| `login` | Browser OAuth login; caches tokens (the "Connect Salesforce" flow) |
| `list-objects` | List objects/tables (`--all`, `--contains <text>`, `--counts` for row counts) |
| `check` | Verify connectivity (uses the cached login, or JWT if configured) |
| `sync` | Extract records → CSV → upload to Auditify (`--modified-since` for incremental) |
| `disconnect` | Revoke the OAuth grant at Salesforce and delete the local token cache |

The cached login **auto-refreshes** expired sessions using the stored refresh
token, so a connection keeps working over time. `SF_DOMAIN` also accepts a full
**My Domain** host (e.g. `acme.my.salesforce.com`).

`sync` examples:

```bash
# A whole object (all fields)
uv run sf-connector sync --object Account

# Specific fields, filtered, limited
uv run sf-connector sync --object Contact \
  --fields "Id,FirstName,LastName,Email" --where "Email != null" --limit 1000

# Raw SOQL, into a specific Auditify folder
uv run sf-connector sync \
  --soql "SELECT Id, Subject, Status FROM Case WHERE IsClosed = false" \
  --folder-id <auditify-folder-external-id>

# Preview without uploading (also save the CSV)
uv run sf-connector sync --object Account --dry-run --output ./accounts.csv
```

Run any command with `--help` for all options.

---

## Configuration reference

| Variable | Flow | What it is |
|---|---|---|
| `SF_CLIENT_ID` | both | Connected/External App **Consumer Key** |
| `SF_CLIENT_SECRET` | OAuth login | Connected/External App **Consumer Secret** |
| `SF_REDIRECT_URI` | OAuth login | Callback URL; must match one configured on the app |
| `SF_DOMAIN` | both | `login` (prod/dev orgs) or `test` (sandbox) |
| `SF_USERNAME` | JWT | Salesforce user the integration runs as |
| `SF_PRIVATE_KEY_FILE` | JWT | RSA private key (PEM) paired with the cert on the app |
| `AUDITIFY_BASE_URL` | upload | Auditify public base URL (nginx routes `/api`) |
| `AUDITIFY_ACCESS_TOKEN` | upload | Auditify JWT access token carrying a tenant claim |

<details>
<summary>JWT bearer (headless) setup — only for unattended/scheduled runs</summary>

1. Generate a key pair:
   ```bash
   openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
     -keyout secrets/server.key -out secrets/server.crt \
     -subj "/CN=auditify-connector"
   ```
2. On the Connected App: enable **Use digital signatures**, upload `server.crt`,
   scopes `api` + `refresh_token`.
3. Pre-authorise the integration user (**Manage → Edit Policies → Permitted Users:
   Admin approved users**, then assign via a Permission Set/Profile).
4. Point `SF_PRIVATE_KEY_FILE` at `server.key` (kept out of git) and set
   `SF_USERNAME`. Then `uv run sf-connector check`.

</details>

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or `pip install -e .`

## Quality gates

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

## Scaling notes

- Uses the Salesforce **REST Query API** (`query_all`), which transparently pages
  results — fine for exports up to ~hundreds of thousands of rows. For very large
  extracts, **Bulk API 2.0** slots in behind the same `salesforce.query_records`
  boundary.
- Uploads use Auditify's direct multipart endpoint (`POST /api/sources/upload`);
  ingestion is asynchronous on Auditify's side.

## Security

- `.env`, `.sf_token.json`, and `*.pem`/`*.key` are git-ignored — never commit secrets.
- The connector is **read-only**: it requests the minimum scopes and never write scopes.
- A production backend must store `refresh_token` encrypted at rest and verify the
  OAuth `state` parameter on the callback (the local CLI relaxes the `state` check
  because the loopback redirect can't be intercepted and PKCE binds the code).
