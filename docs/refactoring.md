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
