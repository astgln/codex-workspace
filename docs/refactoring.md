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
This checkpoint has not yet been deployed to production.
