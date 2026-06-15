# Salesforce Connector — Status vs. "Connect a Source" PRD

**Re:** PRD-CDS-001 · Connect a Source (v2.0)
**Scope of this report:** the **Salesforce** connector only (one connector in the gallery).
**Date:** 15 Jun 2026

---

## TL;DR

The hard part works today. A user can **connect their Salesforce by logging in
through the browser** (OAuth SSO), we can **discover their tables**, and we can
**read records out** — all read-intent. Since the PRD review I also added the
mechanics a *persistent* connection needs: **token auto-refresh**, **revoke on
disconnect**, **row counts**, and a basic **incremental pull**.

**One item needs a product decision, not code:** the PRD promises the consent
screen shows a granular *read-only* scope list and that "create/edit/delete is
never requested." **Salesforce OAuth cannot express that** — see ⚠️ below.

---

## What is DONE and working ✅

| PRD step / requirement | Status | How it works in the connector |
|---|---|---|
| Step 3 — Sign in (SSO) & authorise (FR-3, AC-6/7/8) | ✅ Done | Browser OAuth 2.0 **Authorization Code + PKCE**; user logs in & consents. `sf-connector login` |
| Step 4 — Discover tables (FR-4) | ✅ Done | Lists all objects/tables with API name + label. `sf-connector list-objects` |
| Step 4 — Row counts in picker | ✅ Done | Per-table row count, fetched lazily. `list-objects --counts` |
| Step 5 — Read & extract records (Done) | ✅ Done | SOQL extract → CSV → upload to Auditify. `sf-connector sync` |
| Step 7 — Test connection (AC-17) | ✅ Done | Health check against the org. `sf-connector check` |
| Step 7 — Delete must revoke token (§9, AC-19) | ✅ Done | Revokes the grant at Salesforce, then clears the cache. `sf-connector disconnect` |
| Persistent connection (Step 6 implies) | ✅ Done | Expired sessions **auto-refresh** via the stored refresh token |
| Step 2 — Environment / region / My Domain | ✅ Done | Production/Sandbox + custom **My Domain** host supported; region comes from the org's instance URL |
| Incremental pull (part of Step 4 sync modes) | ◐ Basic | `sync --modified-since <date>` pulls only changed records (via `SystemModstamp`) |

Quality: linter, type-checker, and **15 automated tests** all pass.

---

## What is POSSIBLE but NOT yet built (backend work) 🟠

These are real and doable — they belong in the **Auditify backend**, not this CLI,
because they need a database and a scheduler the connector doesn't have:

| PRD item | Why it's backend work | Effort |
|---|---|---|
| Save connections (name, env, tables, last-synced) — Steps 5/6/7 | Needs a per-tenant database; the CLI keeps one connection in a local file | Medium |
| Encrypted token storage, multi-connection | Production must store refresh tokens encrypted, one per connection | Medium |
| Scheduled sync modes: Daily / Every 6h (Step 4) | Needs a job scheduler; the connector runs on demand | Medium |
| True CDC "Incremental" mode (Step 4) | Needs Salesforce Change Data Capture + streaming; we have date-based incremental as a simpler stand-in | Large |
| Rename / Add another / connected-card UI (Steps 6/7) | Pure frontend + backend store | Frontend |

The connector already exposes the building blocks for all of these; the backend
wraps them in two OAuth endpoints + stored state. Details:
`docs/FRONTEND_INTEGRATION.md`.

---

## What is NOT possible as written — needs a product decision ⚠️

**The "read-only scopes" promise (US-4, FR-3, AC-7, UX note "no write access").**

The PRD says the authorise screen will list granular **read-only** scopes
("view tables/schemas/metadata, read records…") and that **create/edit/delete is
never requested**.

**Salesforce OAuth does not have granular read-only scopes.** We request the
`api` scope, which grants **full read *and* write** with the signed-in user's
permissions, and Salesforce's consent screen simply says *"Manage user data via
APIs."* There is no way to request "read records only" or to show the itemised
read-only list the mockups imply.

**How other tools handle this — pick one:**

1. **Enforce read-only via the user, not the scope.** Ask the connecting user to
   sign in with a Salesforce user that has a **read-only profile/permission set**.
   Then Salesforce itself blocks any write. *(Most robust; needs a setup note.)*
2. **Trust-by-design.** Keep the `api` scope but state plainly: "Irame only ever
   *reads*; it never issues writes." True of our code, but not *enforced* by
   Salesforce. *(Simplest; weaker guarantee.)*
3. **Reword the UI** so it doesn't claim a granular read-only scope list for
   Salesforce — show the actual Salesforce consent text instead.

> **QA note:** AC-7 ("only read-only scopes are requested… create/edit/delete is
> shown as never requested") **cannot pass for Salesforce as written.** It should
> be reworded to match whichever option above we choose, or marked N/A for
> Salesforce.

---

## Recommendation

- **Ship the connector as-is for the connect + discover + read flow** — it meets
  the core of Steps 3–5 and 7.
- **Decide the read-only approach** (option 1 recommended) so QA can finalise AC-7.
- **Sequence the backend work** (connection store → scheduler) for the persistent
  multi-connection experience in Steps 5–7.


