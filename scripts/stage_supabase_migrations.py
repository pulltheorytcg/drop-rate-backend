#!/usr/bin/env python3
"""Stage canonical Drop Rate SQL for the linked production Supabase history.

Early Drop Rate migrations were applied before repository filenames were aligned
with Supabase's generated migration timestamps. Supabase compares timestamps
only, so copying database/migrations verbatim into supabase/migrations would
make already-applied DDL look pending.

This script translates only that historical drift. New migrations keep their
repository timestamp unchanged.

Three early SQL files are also known to have their schema effects present in
production without a corresponding Supabase history row. They are staged as
no-op baseline records so the next deliberate migration apply can repair
history without replaying already-present DDL.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "database" / "migrations"
MANIFEST_PATH = ROOT / "database" / "migration_history_baseline.json"
MIGRATION_RE = re.compile(r"^(?P<version>\d{12,14})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationStageError(RuntimeError):
    pass


def _parse_filename(path: Path) -> tuple[str, str]:
    match = MIGRATION_RE.fullmatch(path.name)
    if match is None:
        raise MigrationStageError(f"Invalid migration filename: {path.name}")
    return match.group("version"), match.group("name")


def _placeholder(*, version: str, name: str, reason: str, source_sha256: str | None = None) -> str:
    lines = [
        "-- Drop Rate production migration-history baseline.",
        f"-- version: {version}",
        f"-- name: {name}",
        f"-- reason: {reason}",
    ]
    if source_sha256:
        lines.append(f"-- canonical_source_sha256: {source_sha256}")
    lines.extend(
        [
            "--",
            "-- Intentionally no SQL. The schema effect was independently verified",
            "-- in production before this history-only baseline was added.",
            "",
        ]
    )
    return "\n".join(lines)


def stage(output_dir: Path) -> dict[str, int]:
    manifest = json.loads(MANIFEST_PATH.read_text())
    if manifest.get("schema_version") != 1:
        raise MigrationStageError("Unsupported migration history baseline schema")

    source_files = sorted(SOURCE_DIR.glob("*.sql"))
    if not source_files:
        raise MigrationStageError("No canonical migrations found")

    parsed = {}
    for path in source_files:
        version, name = _parse_filename(path)
        if name in parsed:
            raise MigrationStageError(f"Duplicate canonical migration name: {name}")
        parsed[name] = (version, path)

    overrides: dict[str, str] = manifest.get("historical_version_overrides", {})
    remote_only: list[dict[str, str]] = manifest.get("remote_only_applied", [])
    unrecorded: list[dict[str, str]] = manifest.get("schema_verified_unrecorded", [])

    missing_override_sources = sorted(set(overrides) - set(parsed))
    if missing_override_sources:
        raise MigrationStageError(
            "Historical override has no canonical source: "
            + ", ".join(missing_override_sources)
        )

    unrecorded_by_name = {item["name"]: item for item in unrecorded}
    missing_unrecorded_sources = sorted(set(unrecorded_by_name) - set(parsed))
    if missing_unrecorded_sources:
        raise MigrationStageError(
            "Schema-verified baseline has no canonical source: "
            + ", ".join(missing_unrecorded_sources)
        )

    if output_dir.resolve() == SOURCE_DIR.resolve():
        raise MigrationStageError("Refusing to stage over canonical migrations")
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.glob("*.sql"):
        path.unlink()

    used_versions: dict[str, str] = {}

    def reserve(version: str, name: str) -> None:
        previous = used_versions.get(version)
        if previous is not None:
            raise MigrationStageError(
                f"Migration version collision {version}: {previous} vs {name}"
            )
        used_versions[version] = name

    for item in remote_only:
        version = str(item["version"])
        name = str(item["name"])
        reserve(version, name)
        (output_dir / f"{version}_{name}.sql").write_text(
            _placeholder(
                version=version,
                name=name,
                reason=str(item["reason"]),
            )
        )

    copied = 0
    remapped = 0
    baselined = 0
    for name, (local_version, source) in sorted(
        parsed.items(), key=lambda item: item[1][0]
    ):
        target_version = str(overrides.get(name, local_version))
        reserve(target_version, name)
        target = output_dir / f"{target_version}_{name}.sql"

        baseline = unrecorded_by_name.get(name)
        if baseline is not None:
            if str(baseline["version"]) != local_version:
                raise MigrationStageError(
                    f"Baseline version mismatch for {name}: "
                    f"{baseline['version']} != {local_version}"
                )
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target.write_text(
                _placeholder(
                    version=target_version,
                    name=name,
                    reason=str(baseline["reason"]),
                    source_sha256=digest,
                )
            )
            baselined += 1
            continue

        shutil.copyfile(source, target)
        copied += 1
        if target_version != local_version:
            remapped += 1

    return {
        "canonical": len(source_files),
        "staged": len(list(output_dir.glob("*.sql"))),
        "copied": copied,
        "remapped": remapped,
        "remote_only_placeholders": len(remote_only),
        "schema_verified_baselines": baselined,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: stage_supabase_migrations.py <output-directory>",
            file=sys.stderr,
        )
        return 2
    try:
        result = stage(Path(sys.argv[1]))
    except (OSError, ValueError, KeyError, MigrationStageError) as exc:
        print(f"migration staging failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
