# Salesforce Connector — Production Handoff & Build Plan

**Audience:** the team building the product (frontend + backend).
**What this is:** a working, **live-tested reference implementation** of the Salesforce
data connector, plus a complete plan for everything still needed to ship it at
production scale.

Read this first. To see the reference run, see [README.md](../README.md).

---

## 1. What this repository is (and is not)

**Is:** a working Salesforce connector that proves the hard parts end-to-end against a
real Salesforce org — browser login, token refresh, table discovery, and read
extraction, all read-only. It is structured to match the *irame Connector Build Spec*
(one shared framework + a thin adapter per source); the **Salesforce adapter** is built.

**Is not:** a multi-user production service. Today it's a command-line tool that holds
**one** connection in a local file. There is **no database, no web API, no UI**. Those
are the production pieces this document specifies.

Think of this repo as the *engine and the proof it works* — the product wraps it.

---

## 2. What already works (tested live on a real org)

All of this is implemented and was verified against a live Salesforce org (`irame`,
743 tables):

| Capability | Where in code |
|---|---|
| **Connect via browser** — OAuth 2.0 Authorization Code + PKCE (the "Connect Salesforce" / "Sign in with Google"-style flow) | [oauth.py](../src/sf_connector/oauth.py) |
| **Stay connected** — expired sessions auto-refresh with the stored refresh token | [salesforce.py](../src/sf_connector/salesforce.py) `connect_auto` |
| **Disconnect cleanly** — revokes the grant at Salesforce, not just locally | [cli.py](../src/sf_connector/cli.py) `disconnect` |
| **Discover tables** — lists all objects (`describeGlobal`) | `salesforce.list_objects` |
| **Describe a table** — columns, types, keys (`describeSObject`) + canonical types | [salesforce_adapter.py](../src/sf_connector/salesforce_adapter.py) |
| **Read records** — SOQL with filter/order pushdown + cursor paging | `salesforce_adapter.read_rows` |
| **The source-agnostic contract** — `SourceAdapter` interface + canonical type set | [adapter.py](../src/sf_connector/adapter.py) |

**Read-only is guaranteed by design:** the `SourceAdapter` contract has no
write/insert/update/delete/execute method anywhere — there is no code path to change a
customer's data.

---

## 3. Target production architecture

```
  ┌─────────────┐   HTTPS    ┌──────────────────┐
  │  Frontend   │ ─────────► │   Backend API    │   (the product's web app + API)
  │  (the UI)   │            └────────┬─────────┘
  └─────────────┘                     │
                                       ▼
                        ┌─────────────────────────────┐
                        │   Connector Framework        │  shared, write-once:
                        │   (secrets vault, audit,      │  · stores connections (DB)
                        │    read-only guard, exposure) │  · encrypts tokens
                        └───────────────┬──────────────┘  · runs the adapters
                                        ▼
                        ┌─────────────────────────────┐
                        │   Salesforce Adapter ✅       │  ← built (this repo)
                        │   (SAP / SQL Server / …)      │  ← future adapters, same contract
                        └───────────────┬──────────────┘
                                        ▼
                                   Salesforce
                              ┌──────────────────┐
                              │  Database         │  per-tenant connections + encrypted tokens
                              └──────────────────┘
```

**The Salesforce adapter (bottom) exists. Everything above it does not yet.**

---

## 4. The biggest gap: there is no database (multi-user)

Today one connection lives in a local file (`.sf_token.json`) with config in `.env` —
fine for one developer, impossible for many customers. Production needs a database with
**tenant isolation**.

### Proposed `connections` table

| Column | Notes |
|---|---|
| `id` | connection id (used in API routes) |
| `tenant_id` | the customer/workspace — **every query filters on this** |
| `user_id` | who connected it |
| `source` | `'salesforce'` (the same table serves all sources) |
| `connection_name` | user-editable label (e.g. "Salesforce — Production") |
| `environment` | production / sandbox |
| `instance_url` | the org's URL (returned by OAuth) |
| `refresh_token_encrypted` | **encrypted at rest** (KMS/secrets vault) — never plaintext |
| `selected_tables` | JSON — the tables the user chose to expose |
| `sync_mode` | one-time / daily / 6h / incremental |
| `status`, `last_synced_at` | health + freshness |
| `created_at`, `updated_at` | audit |

The connector's current "read the cached token → refresh if expired → save it back"
logic (`connect_auto`) maps directly onto "read the tenant's row → refresh → update the
row". One file becomes one row.

---

## 5. What to build for production — by area

### A. Frontend — the "Connect a Source" UI (per PRD-CDS-001)
- Connector gallery (Salesforce card with a read-only badge).
- Configure step (connection name, environment).
- **"Connect Salesforce" button** → kicks off the OAuth flow (section B).
- Table picker — searchable, checkboxes, **row counts**, "select all", sync-mode choice.
- Connected-sources cards — name, tables, last-synced; **Manage** (rename / test / delete / add another).

### B. Backend API — wraps the adapter (mirrors the reference code)
| Endpoint | Reuses |
|---|---|
| `GET /connect/salesforce` → redirect to Salesforce authorize URL (with `state` + PKCE) | `oauth._authorize_url` |
| `GET /oauth/callback?code=…` → exchange code, **store encrypted token in DB** | `oauth._exchange_code` |
| `GET /connections` · `DELETE /connections/{id}` (revoke + stop syncs) | `oauth.revoke_token` |
| `GET /connections/{id}/tables` (+ row counts) | `adapter.list_tables` / `count_records` |
| `POST /connections/{id}/tables` (save the user's selection) | DB write |
| `GET /connections/{id}/tables/{t}/schema` | `adapter.describe_table` |
| `GET /connections/{id}/tables/{t}/rows?select=&filter=&pageSize=&pageToken=` | `adapter.read_rows` |

### C. Connector Framework — shared, write-once (per Build Spec §3)
- **Secrets vault** — encrypt/decrypt tokens (KMS-backed); adapters never see raw secrets in logs.
- **Connection store** — the DB above; persist selection per connection.
- **Read-only guard + audit log** — central; log every connect / discover / read.
- **Metadata cache** — cache discovery so the UI is fast.
- **Exposure layer** — serve selected tables as a read-only **REST/OData** feed (the rows endpoint above). *Only selected tables are routable; everything else 404s.*
- *(Auth manager + type mapper already exist for Salesforce in this repo.)*

### D. Security (production-grade)
- **Read-only enforced at the source:** connect with a Salesforce user that has a **read-only permission set** (the Build Spec §7.2 mandates this — it also resolves the open "read-only scope" question; see section 7).
- Encrypt all tokens at rest; rotate on a schedule; never log tokens.
- **Verify the `state` parameter** on the OAuth callback (the local CLI relaxes this; a server must not).
- Request least-privilege OAuth scopes; TLS everywhere; audit trail for compliance.

### E. Sync & scheduling
- **Scheduler** for recurring syncs (daily / every 6h).
- **Incremental** pulls — the connector already supports date-based incremental via `SystemModstamp` (`sync --modified-since`); wire it to a scheduler.
- **Bulk API 2.0** for very large extracts (we use the REST cursor today — fine to ~hundreds of thousands of rows).

### F. Operations
- Monitoring/alerting on sync failures and token expiry.
- Retry + backoff; handle Salesforce API rate limits.
- Per-tenant audit logs for compliance review.

---

## 6. Production readiness checklist

**Framework / backend**
- [ ] Database with `connections` table + tenant isolation
- [ ] Encrypted token storage (secrets vault / KMS)
- [ ] OAuth endpoints: `/connect/salesforce`, `/oauth/callback` (with `state` verification)
- [ ] Connection CRUD API (list, delete-with-revoke, rename)
- [ ] Table discovery + selection API (with row counts)
- [ ] Read API (schema + paged rows) — the REST/OData exposure layer
- [ ] Central read-only guard + audit logging
- [ ] Scheduler for recurring/incremental syncs
- [ ] Bulk API 2.0 path for large extracts

**Frontend**
- [ ] Connector gallery + Salesforce card
- [ ] Configure + "Connect Salesforce" button → OAuth
- [ ] Table picker (search, counts, select-all, sync mode)
- [ ] Connected-source cards + Manage (rename / test / delete / add another)

**Security / ops**
- [ ] Read-only Salesforce permission set documented for customers
- [ ] Token encryption + rotation
- [ ] Monitoring, alerting, retries, rate-limit handling
- [ ] Per-tenant audit trail

---

## 7. One open product decision (not an engineering task)

The "Connect a Source" PRD promises the approval screen shows only **read-only**
permissions. **Salesforce OAuth has no read-only-only scope** — its only API scope grants
read *and* write, and the consent screen says "Manage user data via APIs." Our connector
only ever reads, but Salesforce won't *display* a read-only-only request.

**Resolution (already pointed to by the Connector Build Spec §7.2):** have customers
connect with a Salesforce user assigned a **read-only permission set** — then Salesforce
itself blocks any write. Decide and document this; QA's "only read-only scopes
requested" test should be reworded accordingly.

---

## 8. Code map (where everything lives)

| File | Purpose |
|---|---|
| [adapter.py](../src/sf_connector/adapter.py) | The source-agnostic `SourceAdapter` contract + canonical types (the framework interface) |
| [salesforce_adapter.py](../src/sf_connector/salesforce_adapter.py) | The Salesforce adapter (the reference implementation) |
| [oauth.py](../src/sf_connector/oauth.py) | OAuth login (auth-code + PKCE), refresh, revoke — reuse for the backend endpoints |
| [salesforce.py](../src/sf_connector/salesforce.py) | Connect/refresh, discovery, SOQL build + query |
| [cli.py](../src/sf_connector/cli.py) | The CLI commands (login, list-objects, sync, disconnect, check) |
| [sync.py](../src/sf_connector/sync.py) · [transform.py](../src/sf_connector/transform.py) · [auditify.py](../src/sf_connector/auditify.py) | The CSV extract→upload path (one example consumer of the read API) |
| [config.py](../src/sf_connector/config.py) | Settings (becomes per-connection DB rows in production) |
| `tests/` | 20 tests covering OAuth URL/PKCE, type mapping, the contract, SOQL building |

---

*Source repo is private. To run the reference yourself, follow [README.md](../README.md).*
