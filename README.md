# Drop Rate Backend

Private FastAPI backend and founder dashboard for Drop Rate's inventory system.

## Inventory workflow

- Search and filter owner-scoped inventory.
- Edit acquisition, condition, grading, location, pricing and audit details.
- Allocate one binder or set purchase total across multiple cards atomically.
- Review missing information in the Action Required queue.
- Approve complete stock records through a dedicated validation endpoint.
- Record every inventory change through the database audit trigger.

Unknown acquisition costs remain `null`; the dashboard never converts them to zero. Bulk allocations use integer minor units and must reconcile exactly to the purchase total.

## API

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/me`
- `GET /api/v1/inventory`
- `GET /api/v1/inventory/readiness`
- `PATCH /api/v1/inventory/{inventory_id}`
- `POST /api/v1/inventory/{inventory_id}/approve`
- `POST /api/v1/inventory/bulk-cost`
- `POST /api/v1/automation/inventory-review`

Protected routes require a valid Supabase bearer token. The verified user ID is applied to the transaction with `SET LOCAL`, and PostgreSQL row-level security determines which owner and inventory rows are visible.
