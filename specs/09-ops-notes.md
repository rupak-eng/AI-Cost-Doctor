# Ops notes — production readiness runbook

**Date:** 2026-09-21 · Status: living doc, update on every infra change

This is the operator's runbook for AI Cost Doctor: what must be configured,
backed up, migrated, and monitored. Names of environment variables only —
no values; see `app/.env.example` for the template.

## 1. Environment variables (names only)

| Variable | Required? | Notes |
|---|---|---|
| `ENVIRONMENT` | optional (`development`) | Set `production` to enable fail-fast gates (valid `FERNET_KEY`, real `JWT_SECRET` ≥ 32 chars, PostgreSQL `DATABASE_URL`). |
| `DATABASE_URL` | required in prod | PostgreSQL connection string. The compose dev default is `postgres:postgres` on localhost — override in prod. |
| `FERNET_KEY` | **required, always** | 32 urlsafe-base64 bytes. Backend refuses to boot if missing/invalid (see §5). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `JWT_SECRET` | required in prod | ≥ 32 chars, never the `dev-only-insecure-secret` placeholder. Generate: `python -c "import secrets; print(secrets.token_urlsafe(64))"`. |
| `JWT_ALGORITHM` | optional (`HS256`) | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | optional (`30`) | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | optional (`30`) | |
| `CORS_ORIGINS` | optional | Comma-separated. Default is localhost-only (safe). Prod: set the real frontend origin(s). |
| `LOG_LEVEL` | optional (`INFO`) | `DEBUG\|INFO\|WARNING\|ERROR`; applied to uvicorn/app loggers. |
| `DEMO_NAMESPACE` | optional | UUID seed for the synthetic demo org. |
| `FRONTEND_URL` | optional | Public frontend base URL (Stripe Checkout success/cancel URLs). |
| `NEXT_PUBLIC_API_URL` | build-time only | Baked into the Next.js bundle via compose **build arg**, not runtime env. |
| `STRIPE_SECRET_KEY` | required when billing live | Stripe API secret. Unset → billing endpoints fail closed (503). |
| `STRIPE_WEBHOOK_SECRET` | required when billing live | Webhook signing secret. Unset → webhook returns 503. |
| `STRIPE_PRICE_STARTER` / `STRIPE_PRICE_GROWTH` | required when billing live | Price IDs created in the Stripe Dashboard. |
| `NARRATIVE_LLM_API_KEY` | optional | Unset → deterministic template narrative is used. |
| `NARRATIVE_LLM_MODEL` | optional (`gpt-4o-mini`) | |
| `NARRATIVE_LLM_BASE_URL` | optional (OpenAI) | |
| `TEST_DATABASE_URL` | test only | Read by `tests/conftest.py`, never by the app. |

Secrets must come from the platform's secret manager (or a root-owned,
`0600` env file) — never baked into images, never committed.

## 2. Startup validation (fail-fast)

Boot order per container: `entrypoint.sh` → **config validation** →
`alembic upgrade head` → server/worker. Validation lives in
`app/backend/app/core/config.py` (`validate_fernet_key`,
`Settings.validate_startup`) and is invoked from `app/main.py`, `app/worker.py`,
and `entrypoint.sh`. A bad config prints a `FATAL:` banner naming the variable
and exits 1 — no cryptic traceback, no half-started server, and migrations
never run against a misconfigured deployment.

## 3. Database backups

- Postgres 16 data lives in the `pgdata` named volume. Back up with
  `pg_dump` on a schedule, not just volume snapshots:
  `docker compose exec db pg_dump -U postgres ai_cost_doctor | gzip > backup-$(date +%F).sql.gz`
- Keep ≥ 7 daily + 4 weekly copies off-host. Test restores quarterly:
  restore into a scratch DB and run `alembic upgrade head` + the smoke
  checks in §6.
- Before any migration, snapshot first (§4).

## 4. Migration procedure

- Migrations run automatically at container start (`alembic upgrade head`
  in `entrypoint.sh`) after config validation. The chain is linear
  (`001`→`006`, single head) — keep it that way; never merge heads by hand.
- Lesson learned (2026-09-21): migration `001` runs
  `Base.metadata.create_all()`, so any table added by a later migration must
  use `checkfirst=True` (or it fails on fresh databases with
  `DuplicateTable`).
- Manual run (no compose): `cd app/backend && alembic upgrade head`
  (reads `DATABASE_URL` from the environment; `python-dotenv` is a
  dependency but nothing calls `load_dotenv`, so export vars in the shell).
- Rollback: `alembic downgrade -1` — verify the target revision's
  `downgrade()` is implemented before relying on it.

## 5. Secret rotation

- **FERNET_KEY**: rotating the master key invalidates every stored provider
  credential (they are envelope-encrypted under it). There is no online
  re-encryption job yet — treat rotation as a planned migration: decrypt
  with the old key, re-encrypt with the new, then swap the env var.
  Until that tooling exists, protect the key as irreplaceable.
- **JWT_SECRET**: rotation invalidates all outstanding access/refresh
  tokens — users simply log in again. Safe to rotate on suspicion.
- **Stripe keys**: rotate in the Dashboard, then update env + restart.

## 6. Health checks & logging

- `GET /healthz` — liveness (compose healthcheck target).
- `GET /readyz` — readiness: liveness + `SELECT 1` DB round-trip; 503 with a
  generic body when the DB is unreachable (no internals leak).
- Logs: structured `%(asctime)s %(levelname)s %(name)s` lines to stdout;
  collect with `docker compose logs` or ship to your log aggregator.
  Tune with `LOG_LEVEL`. Never log secrets — key material, tokens, and
  connection strings must not appear in logs (grep releases for them).
- Compose: `api` and `worker` wait for `db` healthy; `web` waits for `api`
  healthy. `db` is not port-published.

## 7. Stripe webhook registration (reminder)

When billing goes live, register this endpoint in the Stripe Dashboard
(**Developers → Webhooks**) and copy the signing secret to
`STRIPE_WEBHOOK_SECRET`:

```
https://<api-host>/api/v1/billing/webhook
```

Subscribe to: `checkout.session.completed`,
`customer.subscription.created|updated|deleted`,
`invoice.payment_failed`. The handler verifies the HMAC signature and fails
closed (400/503) on any verification problem — never trust an unverified
payload. Use Stripe CLI (`stripe listen --forward-to …`) for local testing.

## 8. Production deploy checklist

1. `ENVIRONMENT=production` on api + worker.
2. Real `FERNET_KEY` (generated, 32 bytes), `JWT_SECRET` (≥ 32 chars),
   production `DATABASE_URL`; `POSTGRES_PASSWORD` changed from the compose
   dev default.
3. `CORS_ORIGINS` = real frontend origin(s); `FRONTEND_URL` = public URL.
4. Stripe keys + price IDs set; webhook registered (§7).
5. Backups scheduled and restore-tested (§3).
6. Log aggregation wired; `LOG_LEVEL=INFO` (not `DEBUG`).
7. Smoke: `/healthz` → 200, `/readyz` → 200, signup → login → P&L loads,
   demo clearly labeled as synthetic data.
