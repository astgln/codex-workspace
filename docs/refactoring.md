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
The local CLI worker was subsequently updated at an idle checkpoint under the
queue lock. launchd and a fresh heartbeat confirmed the new process running idle.


## Cooperative worker lifecycle

SIGTERM/SIGINT request a stop, wake an idle wait and prevent dispatch after
preflight. The loop finishes an already accepted synchronous CLI call and its
publication cycle before exiting. External force-kill/service-manager deadlines
can still interrupt a process; durable intent remains necessary for recovery.
Updates must still take the transport lock and reject an active dispatch before
restarting the service. Desktop is not restarted. Validation: 171 Python tests.

## Schema 2 catalog checkpoint

Projects and tasks now use typed rows with stable ordering and an indexed project
reference. Optional field presence and unknown extension fields are preserved for
compatibility with older catalogs; authorization still validates actual catalog
membership through the domain policy. Empty projects remain visible to owners.
The migration supports schema 0 and 1, verifies state parity before commit, and
removes catalog/project copies from the residual mailbox. The rollback copy
reconstructs the legacy catalog alongside access state. Request and upload data
remain in the residual mailbox pending subsequent domain migrations.

## Schema 3 request checkpoint

Requests and uploads now have typed relational rows, with indexes for status,
task and upload idempotency lookup. Request attachments and response events use
ordered child tables with foreign keys. State reconstruction preserves leases,
approvals, delivered/completed states, response revisions and file associations.
Existing immutable uploaded bytes stay in their directories; migration touches
metadata only. Optional and legacy fields remain lossless. Request/upload copies
are removed from the residual mailbox, and rollback reconstructs all domains.
Tests cover a delivered request with a completed response and attachment through
schema-2 upgrade and legacy restoration, in addition to existing lifecycle tests.

## Storage writes and journal compatibility

Store transactions compare the original state with domain mutations. Read-only
polls issue no data writes; a collector heartbeat updates residual metadata only,
without rewriting access, catalog or request tables. Mutations remain atomic.
History checkpoints carry an explicit checkpoint format and reader version.
A reader change or an old unversioned checkpoint triggers a replay from offset
zero using stable message IDs; failed publication does not advance the checkpoint.
The reader version describes our supported public-record interpretation, not an
assumed upstream Codex schema guarantee. Format support remains explicitly limited
to the journal records recognized by the reader and its regression fixtures.

## Notification identity and uncertain delivery

New collector response publications and history messages carry the Codex turn ID.
Both sources identify answer notifications as `answer:<task>:<turn>`, deduplicating
one turn even when the two paths arrive separately. Older records without a turn
ID retain their legacy event identity; they cannot be reliably cross-correlated.
A push attempt commits its intent before network I/O under an immediate SQLite
transaction. `push_deliveries.done=2` means outcome unknown and is never retried
automatically, including after a process crash or a network exception without a
provider response. Explicit retryable provider responses use bounded backoff;
terminal responses use done=1. This avoids duplicate retries at the cost of a
possibly missed notification on uncertain delivery; website history remains the
source of truth. Real device delivery still requires the iPhone acceptance test.

## Composer boundary

`workspace/useComposer.ts` owns per-task drafts and files, upload progress,
submission state and retry identity. `workspace/Composer.tsx` renders the form.
Targets are captured before asynchronous work, so changing the selected task
does not redirect a file upload or submitted message. A failed unchanged request
retains its draft and idempotency key; browser tests cover retry and navigation.

## Owner operational diagnostics

The owner can expand “Состояние сервиса” in the sidebar to fetch an authenticated,
CSRF-protected diagnostic snapshot. It exposes schema version, collector and
history freshness, queue totals and push device/retry/uncertain counts only.
Message bodies, file paths, credentials and subscription endpoints are excluded.
Members are denied by the backend regardless of UI visibility. Collector freshness
is a recent-poll indicator, not proof that a long-running CLI turn is stalled.

## Consolidated release checkpoint

Release `4c1e68197cc74a9c` includes owner diagnostics, uncertain push delivery
handling, shared turn-based answer identity and the extracted composer.
The full suite passed: 183 Python tests and 27 browser tests. The VM release was
verified over SSH. The request service was restarted under the queue lock with
no active dispatch, and the history service was restarted to load versioned
checkpoints. Desktop was not restarted.

## Remaining implementation work

- Autonomous catalog discovery and activity updates beyond the explicit snapshot;
  preserve installation scope and project/task access rules.
- Finish frontend navigation/session boundaries and expose actionable waiting or
  reconciliation diagnostics without leaking request contents.
- Audit active dependencies, setup and current runtime against the final design;
  historical checkpoints below are evidence, not current operating instructions.
- Complete real member/attachment and iOS push acceptance checks listed above.

## History failure isolation

`history_sync.py` owns per-task history work and separate quota publication;
`history_watch.py` remains the scheduling/checkpoint service. Catalog scope is
validated in full before any publication. Missing or malformed task journals
leave that task's cursor unchanged while other tasks continue. Successfully
published history commits its checkpoint even when quota delivery fails; the
pending quota sample survives in the private checkpoint and retries without
rereading the journal. Partial passes persist successful cursors and log only
aggregate failure counts; one-shot execution returns failure for partial passes.

## Local queue separation

The service imports `local_queue.Queue` directly; `web_client.py` is now an
administrative command adapter with compatibility imports. `queue_downloads.py`
owns verified attachment downloads and `queue_transport.py` owns receipts,
claims and publication. The SQLite queue format is unchanged. Administrative
commands close connections through the queue context manager. Ready responses
are published before inbox/network/download work, so a failing inbox cannot
starve already completed output. Recovery and immutable dispatch checks remain
in the queue and execution adapters; no controller task is involved.

## Correlated in-progress execution

The production CLI executor polls the child process with a bounded communicate
wait. It sends prompt stdin only once and checks the journal between waits.
A running response is published only after the exact prompt is matched to one new
turn after the saved baseline in the correct task. Ambiguous matching still fails
closed. Repeated running snapshots retain their revision; accepted publications
refresh collector freshness so long turns do not appear disconnected. The final
response retains the same turn identity and advances the response revision.
Network/recovery failures during polling preserve the active process and durable
intent; they never trigger a new CLI execution. Unit tests cover pre-completion
publication, stable revisions and process polling without repeated stdin.

## Conversation and login views

`workspace/Conversation.tsx` owns the merged history/request timeline, attachment
downloads, approval actions, response events and correlated activity indicator.
`workspace/LoginPage.tsx` renders session preparation and cancellable login.
The application shell retains session effects, navigation and the scroll container
so extracting views does not reset reading positions or change authentication.
The production build and all 27 browser regressions pass, including shimmer,
reduced motion, login origin checks, approval snapshots and history anchoring.

## Operating documentation and manual history parity

The active collector runbook now describes the CLI and history services only.
Controller/shared-server experiments are explicitly archived. Deployment docs
match uncertain push semantics and link to the current runbook. Manual history
sync delegates to the same implementation as the service, validating the entire
catalog before any publication and continuing unrelated tasks after journal
failures. Its aggregate output reports partial failures with exit code 1.
