# Aligning the Salesforce connector with the Connector Build Spec

**Re:** irame Connector Build Specification (Draft v1.0) — the unified
framework + thin-adapter-per-source model (SAP, Salesforce, SQL Server, Databricks).

This repo started as a standalone Salesforce tool. This note shows how it now maps
onto the spec's `SourceAdapter` contract, what is already done, and what the shared
framework still owns.

## What we did here

We implemented the spec's source-agnostic contract and a Salesforce adapter against it,
**reusing the Salesforce code already proven on a live org**:

- [`adapter.py`](../src/sf_connector/adapter.py) — the `SourceAdapter` interface (§3.2),
  the canonical type set (§6), and the data model (`TableRef`, `TableSchema`, `Column`,
  `ReadRequest`, `ReadResult`, `Capabilities`). Read-only **by shape**: there is no
  write/execute/DDL method anywhere on the contract.
- [`salesforce_adapter.py`](../src/sf_connector/salesforce_adapter.py) — the Salesforce
  adapter (§7.2), wrapping our existing OAuth + discovery + SOQL code.

Verified live against the `irame` org through the interface: `authenticate` →
`test_connection` → `list_tables` (743) → `describe_table` (Account, 45 columns with
canonical types) → `read_rows` (real records).

## Contract coverage (spec §3.2)

| Contract method | Salesforce adapter | Status |
|---|---|---|
| `authenticate()` | OAuth auth-code + PKCE, with refresh (reuses `oauth.py` / `connect_auto`) | ✅ |
| `test_connection()` | Org query ping | ✅ |
| `list_tables()` | `describeGlobal` via `list_objects` | ✅ |
| `describe_table()` | `describeSObject` → columns + **canonical types** + key flag | ✅ |
| `read_rows()` | SOQL with column/filter/order pushdown + **REST cursor paging** (`pageToken`) | ✅ |
| `capabilities()` | `filter_pushdown`, `paging`, `incremental` = true; `catalogs` = false | ✅ |
| `list_catalogs()` / `list_schemas()` | N/A — Salesforce is flat; declared unsupported | ✅ (correct) |

## Canonical type mapping (spec §6)

Implemented in `salesforce_adapter.canonical_type`, matching the spec's table:
`string/picklist/id/reference/… → STRING`, `int → INTEGER`,
`double/currency/percent → DECIMAL`, `boolean → BOOLEAN`,
`date/datetime/time → TIMESTAMP`. Unknown types fall back to `STRING`.

## What the shared FRAMEWORK still owns (not the adapter)

These are deliberately **out of this adapter** — per the spec they live in the
write-once framework, and apply to all four sources:

- **Exposure layer (§5):** serve selected tables as a read-only **REST/OData** feed
  (`GET …/tables/{table}/rows`). Today this repo also has a CSV→Auditify path, which
  becomes one consumer of the read API rather than the contract itself.
- **Secrets vault (§3.1):** encrypted token storage. We cache tokens in a local file;
  the framework replaces that with a KMS-backed vault.
- **Central read-only guard + audit (§8):** the adapter is read-only by shape; the
  framework adds the central guard and the audit log of every connect/discover/read.
- **Metadata cache, query/paging engine (§3.1):** the framework caches discovery and
  drives the read loop across sources.

## Salesforce-specific items still open (spec §7.2)

- **Bulk API 2.0** for very large extracts — we use the REST query cursor (fine up to
  ~hundreds of thousands of rows; Bulk is the next step).
- **Field-level security / compound-field flattening** — to handle on `describe_table`.

## Where this fits the build plan (spec §9)

The plan sequences Salesforce at **M4** (after the framework, SQL Server, Databricks).
This adapter is effectively a **working M4 reference** built early — it de-risks the
Salesforce specifics (PKCE, refresh, session expiry, paging, types) and gives a concrete
input for finalising the `SourceAdapter` interface before the framework is written.

## Recommendation

1. Adopt this `SourceAdapter` contract (or a close variant) as the framework interface —
   it's been exercised against a real source.
2. Build the framework's exposure layer + vault + audit (the shared, write-once parts).
3. Keep this Salesforce adapter as the reference; add SQL Server / Databricks / SAP
   adapters against the same contract.
