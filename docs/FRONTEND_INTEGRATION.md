# Frontend integration: "Login with Salesforce" → pick tables → fetch

This document describes how to wire the product's **"Connect Salesforce"** button
to the connector's **OAuth Authorization Code (+ PKCE)** login flow — the same UX
as "Login with Google".

> **Status:** the OAuth login flow is already implemented and tested in this repo
> ([`oauth.py`](../src/sf_connector/oauth.py), exercised by the `sf-connector login`
> command). The backend work below is mostly **moving that same logic behind two
> HTTP endpoints** and storing tokens per tenant. A second **headless JWT** flow
> also exists for unattended/scheduled single-org runs.

## 1. Two auth models — why today's code is not enough

| | JWT Bearer (today) | Authorization Code (what the product needs) |
|---|---|---|
| Who authorizes | An admin, once, for **one** integration user | **Each end-user**, in the browser, for **their own** org |
| Browser login screen | No | Yes ("Allow Auditify to access your data?") |
| Good for | A backend cron job hitting one org you own | A SaaS where many customers connect their own orgs |
| Tokens | Minted on demand from a private key | `access_token` + `refresh_token` stored per user/tenant |

The current [`salesforce.connect`](../src/sf_connector/salesforce.py) uses JWT Bearer.
It is perfect for testing and for single-org internal use, but it cannot let
arbitrary customers self-connect. That requires the Authorization Code flow below.

## 2. Target architecture

```
[User clicks "Connect Salesforce"]
   │
   ▼
Frontend ──GET /connect/salesforce──▶ Backend
   │  302 redirect to login.salesforce.com/services/oauth2/authorize
   │  (with state + PKCE code_challenge)
   ▼
Salesforce login + consent  (the "Login with Google"-style screen)
   │  302 back to our redirect_uri with ?code=...&state=...
   ▼
Backend GET /oauth/callback?code=...
   │  POST /services/oauth2/token  (code + client_id + client_secret + code_verifier)
   ▼
{ access_token, refresh_token, instance_url }  ──▶ store encrypted, keyed by tenant
   │
   ▼
Frontend lists tables ──GET /salesforce/objects──▶ Backend (uses stored token)
   │
   ▼
User picks objects ──POST /salesforce/sync──▶ Backend runs extract → CSV → Auditify
```

## 3. What to reuse vs. build

**Reuse as-is** (these are auth-agnostic — they take a connected `Salesforce`
client and do the data work):
- [`salesforce.list_objects`](../src/sf_connector/salesforce.py) — the catalog for the "pick your tables" screen.
- [`salesforce.all_fields`](../src/sf_connector/salesforce.py), [`build_soql`](../src/sf_connector/salesforce.py), [`query_records`](../src/sf_connector/salesforce.py) — the fetch.
- [`transform.records_to_csv`](../src/sf_connector/transform.py) and [`auditify.AuditifyClient`](../src/sf_connector/auditify.py) — CSV + upload.
- [`sync.run_sync`](../src/sf_connector/sync.py) — the whole extract→csv→upload orchestration.

**Already built — reuse the logic from [`oauth.py`](../src/sf_connector/oauth.py):**
- Token-based connect: [`salesforce.connect_with_token`](../src/sf_connector/salesforce.py)
  builds the client from a stored `(access_token, instance_url)` —
  `Salesforce(instance_url=..., session_id=...)`. No private key needed.
- `oauth._authorize_url(settings, state, code_challenge)` — builds the Salesforce
  authorize URL (incl. PKCE `code_challenge` + `state`).
- `oauth._exchange_code(settings, code, code_verifier)` — POSTs the code to the
  token endpoint with the PKCE `code_verifier` + `client_secret` and returns the tokens.
- `oauth._pkce_pair()` — generates the `(code_verifier, code_challenge)` S256 pair.

**Build new (the backend wrapper around the above):**
1. **OAuth endpoints** in the Auditify backend (not in this CLI):
   - `GET /connect/salesforce` → generate `state` + PKCE pair, store them in the
     user's session, redirect to `_authorize_url(...)`.
   - `GET /oauth/callback` → verify `state`, call `_exchange_code(...)` with the
     stored `code_verifier`, store the returned tokens per tenant.
2. **Token storage + refresh:** persist `refresh_token` encrypted; when a call gets
   401, use the refresh token to mint a new `access_token`.
3. **Thin API over the reused data functions:**
   - `GET /salesforce/objects` → `list_objects(...)`
   - `POST /salesforce/sync {object, fields?, where?, limit?}` → `run_sync(...)`

> **PKCE is required.** Salesforce External Client Apps (and Connected Apps with
> "Require PKCE" on) reject an authorize request without a `code_challenge`. The
> backend must generate the PKCE pair per login, keep the `code_verifier` server-side
> (tied to the session/`state`), and send it at token exchange.

## 4. Connected App settings difference

One app (Connected App **or** the newer External Client App), different OAuth settings:
- **Authorization Code (product):** set a **Callback URL** (your `/oauth/callback`),
  keep the **Consumer Secret** (used in the token exchange), keep **Require PKCE**
  enabled, scopes `api refresh_token`.
- **JWT (headless):** "Use digital signatures" + uploaded certificate.

You can enable both on one app.

## 5. Security notes

- Store `refresh_token` encrypted at rest; never expose tokens to the frontend.
- Use and verify the `state` parameter to prevent CSRF on the callback.
- Scope every stored token + every upload to the tenant (Auditify already does the
  latter via the `tenant` claim on its access token).
- This product is **fetch-only**: request the minimum scopes; do not request write scopes.
