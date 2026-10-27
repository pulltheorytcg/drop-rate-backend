'use strict';

// Read-only diagnostics for the pinned n8n 2.32.6 SQLite schema. Do not load
// n8n's CLI/ORM: initialization can migrate state or load credential material.
const { createHash } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const FLAG = 'DROP_RATE_N8N_METADATA_INSPECT_ON_BOOT';
const EVENT = 'DROP_RATE_N8N_METADATA_INSPECTION';
const TIMEOUT_MS = 15000;
const MAX_OUTPUT_BYTES = 65536;
const MAX_DEFINITION_BYTES = 1024 * 1024;
const MAX_CREDENTIALS = 50;
const WORKFLOWS = Object.freeze([
  ['DR90GlobalErrorV1', 'dr-90-global-error.json'],
  ['DR92RuntimeHeartbeatV1', 'dr-92-runtime-heartbeat.json'],
  ['DR93ObjectStorageHealthV1', 'dr-93-object-storage-health.json'],
  ['DR94R2ApprovedMediaMirrorV1', 'dr-94-r2-approved-media-mirror.json'],
]);
const DRIVE_TYPES = Object.freeze(['googleDriveOAuth2Api', 'googleApi']);
const SOURCE_DIRECTORY = path.resolve(__dirname, '..', 'workflows');

function unavailable(reason) {
  return { event: EVENT, schema_version: 1, status: 'UNAVAILABLE', reason };
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}

function definitionHash(workflow) {
  if (!workflow || typeof workflow.id !== 'string' || typeof workflow.name !== 'string'
      || !Array.isArray(workflow.nodes) || !workflow.connections
      || typeof workflow.connections !== 'object' || Array.isArray(workflow.connections)
      || (workflow.settings != null && (typeof workflow.settings !== 'object'
        || Array.isArray(workflow.settings)))
      || (workflow.nodeGroups != null && !Array.isArray(workflow.nodeGroups))) {
    throw new Error('INVALID_DEFINITION');
  }
  // Exclude generated IDs/timestamps, publication state, pinned execution data,
  // static execution state and editor metadata. Preserve all executable fields
  // below, including node credentials references, code and connection ordering.
  const definition = {
    id: workflow.id, name: workflow.name, nodes: workflow.nodes,
    connections: workflow.connections, settings: workflow.settings || {},
    nodeGroups: workflow.nodeGroups || [],
  };
  return createHash('sha256').update(JSON.stringify(canonical(definition))).digest('hex');
}

function errorWorkflow(settings) {
  const id = settings?.errorWorkflow;
  if (id == null || id === '') return null;
  if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(id)) {
    throw new Error('INVALID_ERROR_WORKFLOW');
  }
  return id;
}

function runtimeConfig(env, cwd = process.cwd()) {
  if (env.DB_TYPE && env.DB_TYPE !== 'sqlite') return { reason: 'DATABASE_TYPE_UNSUPPORTED' };
  // File-backed/env-file configuration must be explicitly reviewed, not guessed.
  if (['N8N_USER_FOLDER_FILE', 'DB_SQLITE_DATABASE_FILE', 'DB_TABLE_PREFIX_FILE',
    'DB_TYPE_FILE', 'N8N_CONFIG_FILES'].some(key => env[key])) {
    return { reason: 'DATABASE_CONFIGURATION_UNSUPPORTED' };
  }
  const tablePrefix = env.DB_TABLE_PREFIX || '';
  if (!/^[A-Za-z0-9_]{0,64}$/.test(tablePrefix)) return { reason: 'TABLE_PREFIX_UNSUPPORTED' };
  // Match @n8n/config getN8nFolder() and DbConnectionOptions in 2.32.6.
  const n8nFolder = path.join(env.N8N_USER_FOLDER ?? env.HOME ?? cwd, '.n8n');
  return {
    databasePath: path.resolve(n8nFolder, env.DB_SQLITE_DATABASE ?? 'database.sqlite'),
    tablePrefix,
  };
}

function openDatabase(databasePath) {
  const { DatabaseSync } = require('node:sqlite');
  return new DatabaseSync(databasePath, { readOnly: true, timeout: 250, allowExtension: false });
}

function parsedDefinition(row) {
  return {
    id: row.id, name: row.name,
    nodes: JSON.parse(row.nodes), connections: JSON.parse(row.connections),
    settings: row.settings == null ? {} : JSON.parse(row.settings),
    nodeGroups: row.nodeGroups == null ? [] : JSON.parse(row.nodeGroups),
  };
}

function boundedJson(column) {
  // The identifiers are fixed in this file. Oversize values are rejected without
  // loading their bytes into Node; JSON null is also rejected for required fields.
  return `CASE WHEN length(CAST("${column}" AS BLOB)) <= ${MAX_DEFINITION_BYTES}
    OR "${column}" IS NULL THEN "${column}"
    ELSE '"DROP_RATE_OVERSIZE_VALUE"' END AS "${column}"`;
}

function inspectDatabase(database, sourceDirectory = SOURCE_DIRECTORY, tablePrefix = '') {
  if (!/^[A-Za-z0-9_]{0,64}$/.test(tablePrefix)) return unavailable('TABLE_PREFIX_UNSUPPORTED');
  const report = {
    event: EVENT, schema_version: 1, status: 'COMPLETE',
    normalization: 'drop-rate-workflow-definition-v1', workflows: [],
    drive_credentials: { status: 'COMPLETE', credentials: [], truncated: false },
  };
  for (const [id, file] of WORKFLOWS) {
    const item = {
      id, status: 'COMPLETE', source_sha256: null, stored_sha256: null,
      published_sha256: null, source_matches_stored: null, source_matches_published: null,
      source_errorWorkflow: null, errorWorkflow: null, active: null, published: null,
    };
    report.workflows.push(item);
    try {
      const filename = path.join(sourceDirectory, file);
      const info = fs.statSync(filename);
      if (!info.isFile() || info.size > MAX_DEFINITION_BYTES) throw new Error('SOURCE_UNAVAILABLE');
      const source = JSON.parse(fs.readFileSync(filename, 'utf8'));
      if (source.id !== id) throw new Error('SOURCE_ID_MISMATCH');
      item.source_sha256 = definitionHash(source);
      item.source_errorWorkflow = errorWorkflow(source.settings);
    } catch {
      item.status = 'PARTIAL';
      item.reason = 'SOURCE_DEFINITION_UNAVAILABLE';
    }
    try {
      const row = database.prepare(`SELECT "id", "name", "active", "activeVersionId",
        ${['nodes', 'connections', 'settings', 'nodeGroups'].map(boundedJson).join(', ')}
        FROM "${tablePrefix}workflow_entity" WHERE "id" = ? LIMIT 1`).get(id);
      if (!row) {
        item.status = 'MISSING';
        continue;
      }
      if (![0, 1].includes(row.active) || (row.activeVersionId != null
        && (typeof row.activeVersionId !== 'string'
          || !/^[A-Za-z0-9_-]{1,128}$/.test(row.activeVersionId)))) {
        throw new Error('STORED_STATE_INVALID');
      }
      item.active = row.active === 1;
      // n8n 2.32.6 deprecates `active`; this is the authoritative published state.
      item.published = row.activeVersionId != null;
      const stored = parsedDefinition(row);
      item.stored_sha256 = definitionHash(stored);
      item.errorWorkflow = errorWorkflow(stored.settings);
      item.source_matches_stored = item.source_sha256 == null
        ? null : item.source_sha256 === item.stored_sha256;
      if (item.published) {
        const published = database.prepare(`SELECT
          ${['nodes', 'connections', 'nodeGroups'].map(boundedJson).join(', ')}
          FROM "${tablePrefix}workflow_history"
          WHERE "workflowId" = ? AND "versionId" = ? LIMIT 1`).get(id, row.activeVersionId);
        if (!published) throw new Error('PUBLISHED_VERSION_UNAVAILABLE');
        // Match n8n export:workflow --published: the history contains nodes,
        // connections and node groups; shared workflow settings stay on the entity.
        item.published_sha256 = definitionHash(parsedDefinition({ ...row, ...published }));
        item.source_matches_published = item.source_sha256 == null
          ? null : item.source_sha256 === item.published_sha256;
      }
    } catch {
      item.status = 'PARTIAL';
      item.reason = 'STORED_DEFINITION_UNAVAILABLE';
    }
  }
  try {
    // Intentionally never SELECT or decrypt the credential `data` column.
    // googleApi is a potential service-account credential, not proof of Drive access.
    const rows = database.prepare(`SELECT
      CASE WHEN length("id") <= 128 THEN "id" ELSE NULL END AS "id",
      CASE WHEN length("name") <= 128 THEN "name" ELSE NULL END AS "name", "type"
      FROM "${tablePrefix}credentials_entity" WHERE "type" IN (?, ?)
      ORDER BY "id" LIMIT ${MAX_CREDENTIALS + 1}`).all(...DRIVE_TYPES);
    report.drive_credentials.truncated = rows.length > MAX_CREDENTIALS;
    for (const row of rows.slice(0, MAX_CREDENTIALS)) {
      if (typeof row.id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(row.id)
        || typeof row.name !== 'string' || [...row.name].length > 128
        || !DRIVE_TYPES.includes(row.type)) {
        report.drive_credentials.status = 'PARTIAL';
        continue;
      }
      report.drive_credentials.credentials.push({ id: row.id, name: row.name, type: row.type });
    }
  } catch {
    report.drive_credentials.status = 'UNAVAILABLE';
    report.drive_credentials.reason = 'CREDENTIAL_METADATA_UNAVAILABLE';
  }
  if (report.workflows.some(item => item.status !== 'COMPLETE')
    || report.drive_credentials.status !== 'COMPLETE' || report.drive_credentials.truncated) {
    report.status = 'PARTIAL';
  }
  return report;
}

function worker(env = process.env) {
  const config = runtimeConfig(env);
  if (config.reason) return unavailable(config.reason);
  let database;
  try {
    database = openDatabase(config.databasePath);
    database.exec('BEGIN');
    return inspectDatabase(database, SOURCE_DIRECTORY, config.tablePrefix);
  } catch {
    return unavailable('DATABASE_UNAVAILABLE');
  } finally {
    try { database?.exec('ROLLBACK'); } catch { /* Read-only snapshot only. */ }
    try { database?.close(); } catch { /* Fixed diagnostics only. */ }
  }
}

function run(env = process.env, spawn = spawnSync) {
  if (!env[FLAG] || env[FLAG] === 'false') return null;
  if (env[FLAG] !== 'true') return unavailable('INVALID_OPERATOR_FLAG');
  const config = runtimeConfig(env);
  if (config.reason) return unavailable(config.reason);
  // Do not pass application secrets, NODE_OPTIONS, or the encryption key to
  // this child. The parent bounds even a stuck filesystem/SQLite read.
  const childEnv = { [FLAG]: 'true', NODE_NO_WARNINGS: '1' };
  for (const key of ['N8N_USER_FOLDER', 'HOME', 'DB_SQLITE_DATABASE', 'DB_TABLE_PREFIX', 'DB_TYPE']) {
    if (env[key] !== undefined) childEnv[key] = env[key];
  }
  const child = spawn(process.execPath, ['--no-warnings', __filename, '--inspect-worker'], {
    env: childEnv, encoding: 'utf8', timeout: TIMEOUT_MS, maxBuffer: MAX_OUTPUT_BYTES,
    killSignal: 'SIGKILL', stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (child.error || child.status !== 0) {
    return unavailable(child.error?.code === 'ETIMEDOUT' ? 'INSPECTION_TIMEOUT' : 'INSPECTION_FAILED');
  }
  try {
    const result = JSON.parse(child.stdout);
    if (result.event !== EVENT || result.schema_version !== 1) throw new Error('INVALID_RESULT');
    return result;
  } catch {
    return unavailable('INSPECTION_RESULT_UNAVAILABLE');
  }
}

if (require.main === module) {
  let result;
  try {
    result = process.argv[2] === '--inspect-worker'
      ? (process.env[FLAG] === 'true' ? worker() : null) : run();
  } catch {
    result = unavailable('INSPECTION_FAILED');
  }
  if (result) process.stdout.write(JSON.stringify(result) + '\n');
  // Diagnostic failure is deliberately nonfatal to normal n8n startup.
}

module.exports = { FLAG, WORKFLOWS, definitionHash, runtimeConfig, openDatabase, inspectDatabase, run };
