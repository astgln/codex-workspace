# Refactoring delivery plan

Keep React/TypeScript, FastAPI, SQLite, the normal desktop application and two
outbound-only local services. Preserve existing task execution permissions.
Changes ship incrementally; passing unit tests alone does not prove live delivery.

## Stages and evidence

1. **Contracts and access:** one access/approval policy module; characterize
   owner/member grants, project inheritance, task denies, read-only targets,
   revocation and idempotency. In progress: `cloud/access.py` owns policy;
   `cloud/workspace.py` retains compatible imports for existing callers.
2. **Persistence:** versioned SQLite migrations from the JSON mailbox into domain
   tables. Verify old-state import, transaction rollback, interruption/retry,
   foreign keys, data parity and a restoration procedure before production use.
3. **Server domains:** separate catalog, requests, decisions and response
   publication from authentication and HTTP adapters. Remove legacy bot and
   Cloud Functions dependencies from the active application path.
4. **Worker:** separate queue, permission preflight, execution, correlation and
   publication. Preserve uncertain outcomes without automatic redispatch;
   distinguish busy tasks from missing settings and terminal errors.
5. **Synchronization:** independent catalog, history, activity and quota updates;
   explicit journal format handling and restart-safe cursors. Verify discovery
   of new projects/tasks, partial journal records and active tasks.
6. **Frontend:** separate API types/client, project navigation, access management,
   conversation state, composer and notifications. Preserve scroll restoration
   and opening new conversations at their end.
7. **Notifications and operations:** durable event identity and deduplication,
   permission rechecks, bounded retries, diagnostic health and safe shutdown.
8. **Retirement and release:** remove obsolete controller/shared-server paths,
   update setup and operations documentation, commit/push reviewed changes and
   deploy verified releases over SSH. Update workers only when no request runs.

## Acceptance that remains external

- Real member login, scoped access, approval and attachment round trip through
  the autonomous worker; do not impersonate the member.
- Real iOS Home Screen installation, push permission and receipt of approval and
  response notifications; provider acceptance is not device delivery.

These are outstanding acceptance items, not reasons to stop independent
refactoring. No desktop restart or network/security configuration change is
included in this plan.

## Schema 1 checkpoint

`server/migrations.py` migrates bindings, project/task grants, task denies and
member approval policies into typed access tables in one immediate transaction.
The remaining request/catalog state is still in the mailbox during this stage.
The state adapter preserves existing domain function contracts; history uses that
adapter too. Migrated fields are removed from JSON, so there is one authority.
Migration compares reconstructed state against the original before committing;
an error rolls back both DDL and data. Newer schema versions fail closed.

Before production migration, take a consistent SQLite backup and verify it on the
actual host. Do not run a pre-migration release against schema 1: it cannot read
access tables. For rollback, stop writes and use the new release's code:

```sh
python3 -m server.migrations /path/to/workspace.sqlite3 /private/restore/workspace.sqlite3
```

This creates an exclusive mode-0600 schema-0 copy using SQLite backup, including
sessions/history/push tables and changes made since migration. It reconstructs
the legacy mailbox and verifies database integrity without changing the source.
Switch the old service to the restored database only while stopped; retain other
service data such as uploaded files and VAPID keys. Never overwrite a running
SQLite file or replace it without handling its WAL/SHM sidecars.

Tests cover migration parity, repeated startup, interrupted migration and retry,
mutation rollback, newer-schema rejection and restoration of post-migration data.
This checkpoint was deployed with the first refactoring release; see the verified release record below.

## Server domain checkpoint

`cloud/workspace.py` is now an import facade for `access`, `identity`, `catalog`,
`requests`, `responses` and `views`. Domain functions retain their transaction
boundary and public contracts. The VM uses `server/api.py` with explicit storage
injection; `server/app.py` no longer imports or monkey-patches `cloud/runtime.py`.
Legacy YDB, Bot API and Cloud Functions handlers remain isolated for historical
compatibility until their removal, and are not loaded by the active VM server.
The legacy `/v1` collector endpoints are absent from the VM adapter. Import tests
explicitly block the legacy runtime to verify that the server does not need it.

## Frontend domain checkpoint

The browser API is split into transport/session, Telegram login, workspace,
attachments, history, push and shared data types under `web/src/api/`. Existing
imports use a compatibility export file. CSRF state remains private to transport;
all domains use the same request policy and session invalidation behavior.
`workspace/AccessPanel`, `ProjectPanel` and `PublicEvent` now own their rendering.
The application shell still owns navigation and conversation/composer state;
extracting those stateful responsibilities remains a later step. Read-only task
copy no longer assumes a special controller task exists.

## Worker boundary checkpoint

`cli_worker.py` now contains the service loop only. `worker_dispatch.py` owns
preflight and durable intent, `worker_execution.py` launches the CLI with literal
stdin and private exclusive files, and `worker_recovery.py` correlates persisted
responses before publication. Existing interrupted dispatches are recovered before
considering new work and never automatically resubmitted. Recovery recognizes
historical transport markers so old uncertain records are not discarded.
The shared App Server experiment moved to `legacy_shared_worker.py` for historical
tests; it is no longer an available service transport or imported by the CLI loop.
Private output mode is explicit even when invoking execution outside launchd.
The queue remains in `web_client.Queue`; deeper queue decomposition and graceful
service lifecycle work are still outstanding. Source changes do not restart a
running service; deploy these modules together at an idle checkpoint.


## First deployed refactoring release

Release `a80f8c2853de944fec09da9a61f9f642f29882f1508c684b31159d5b591f57ab`
was installed through SSH with archive SHA-256 verification. The installer made
a consistent private database backup, rehearsed migration and legacy restoration,
and only then switched the service. Post-release checks confirmed schema 1,
SQLite integrity, no foreign-key errors, no duplicate access fields in the
residual mailbox, preserved history/session tables and healthy active service.
Validation: 169 Python tests and 21 browser tests passed; production browser
login/member acceptance and iOS push are separate outstanding checks.
The local CLI worker has not been restarted to load its refactored modules yet.
