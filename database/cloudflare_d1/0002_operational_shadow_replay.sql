-- Additive metadata in the EXISTING private operational shadow. No authority switch.
CREATE TABLE IF NOT EXISTS ops_shadow_replay_checkpoints (
 generation_id TEXT PRIMARY KEY REFERENCES ops_shadow_generations(generation_id),
 parent_generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 source_snapshot TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 inventory_version_root TEXT NOT NULL CHECK(length(inventory_version_root)=64),
 changed_records INTEGER NOT NULL CHECK(changed_records>=0),
 plan_sha256 TEXT NOT NULL CHECK(length(plan_sha256)=64)
);
CREATE TABLE IF NOT EXISTS ops_shadow_inventory_replay (
 generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 inventory_id TEXT NOT NULL,
 prior_sha256 TEXT NOT NULL CHECK(length(prior_sha256)=64),
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 prior_version INTEGER NOT NULL,
 source_version INTEGER NOT NULL CHECK(source_version>=prior_version),
 classification TEXT NOT NULL,
 changed_columns_json TEXT NOT NULL CHECK(json_valid(changed_columns_json)),
 PRIMARY KEY(generation_id,inventory_id)
);
CREATE TABLE IF NOT EXISTS ops_shadow_replay_daily_budget (
 utc_day TEXT PRIMARY KEY,
 generation_id TEXT NOT NULL,
 parent_generation_id TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 source_snapshot TEXT NOT NULL,
 logical_rows_reserved INTEGER NOT NULL CHECK(logical_rows_reserved BETWEEN 1 AND 2500)
);
CREATE TABLE IF NOT EXISTS ops_shadow_replay_head (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 generation_id TEXT NOT NULL REFERENCES ops_shadow_replay_checkpoints(generation_id),
 captured_at TEXT NOT NULL
);
