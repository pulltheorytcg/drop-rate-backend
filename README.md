# Drop Rate Backend

Private FastAPI backend for Drop Rate's founder inventory system.

## Responsibilities

- Verify Supabase founder access tokens.
- Enforce owner-scoped inventory access through PostgreSQL row-level security.
- Search and update physical inventory records.
- Produce idempotent inventory-review reports for n8n.
- Expose Railway liveness and database-readiness checks.

Shopify remains the customer-facing storefront. PostgreSQL/Supabase remains the source of truth, and n8n only orchestrates calls to this API.

## Runtime

Required environment variables:

- `TCG_DATABASE_URL`
- `TCG_AUTH_ISSUER`
- `TCG_AUTH_AUDIENCE`
- `TCG_ENVIRONMENT`

Optional:

- `TCG_JWKS_URL`
- `TCG_DB_POOL_MIN`
- `TCG_DB_POOL_MAX`

Start command:

```bash
uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}
```

## API

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/me`
- `GET /api/v1/inventory`
- `PATCH /api/v1/inventory/{inventory_id}`
- `POST /api/v1/automation/inventory-review`

Protected routes require a valid Supabase bearer token. The database session receives the verified user ID with `SET LOCAL`; RLS then determines which owner and inventory rows are visible.
