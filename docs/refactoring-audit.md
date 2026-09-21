# Refactoring completion audit

This is an incomplete audit, not a completion claim. Baseline: `4dd1710`.
The current GitHub Tests workflow completed successfully for that revision,
covering Ubuntu/Python 3.12 and the production web build/browser suite. Local
Python 3.14 validation collected 217 cases (including inherited API tests).
Counts alone do not establish end-to-end acceptance.

| Requirement | Inspected evidence | Result / remaining scope |
| --- | --- | --- |
| Preserve React/TypeScript, FastAPI and SQLite | web build, server/app.py, server/store.py, running VM | Preserved; no additional service architecture introduced |
| Remove retired transports from active paths | runtime_support.py, workspace_client.py, test_runtime_boundaries.py, test_vm_api.py | Current services import without bot/cloud runtime/shared-server modules; archived code remains explicitly isolated |
| Separate backend policy and domains | cloud/access.py, catalog.py, requests.py, responses.py, views.py; injected server/api.py | Domains separated; HTTP routing remains in the application adapter |
| Normalize storage with versioned recovery | migrations.py, catalog_store.py, request_store.py, test_migrations.py, install.sh | Schema 3 stores access/catalog/request domains separately; residual operational/auth metadata stays JSON intentionally during gradual migration |
| Verify deployment and restoration | release_vm.py digest checks; installer rehearses backup/migrate/legacy restore before symlink switch | Implemented and exercised by releases; migration tests cover rollback/interruption/post-migration data, not general disaster recovery of the whole VM |
| Central access and approval | access.py and API/browser tests | Owner, project/task grants, task deny precedence, owner autoapproval and member policy covered automatically; real second-member acceptance absent |
| Separate queue and preserve execution rights | local_queue.py, queue_transport.py, queue_downloads.py, cli_session.py, worker_execution.py | Durable intent, checksums, original settings and no shell interpolation; archived recovery markers accepted without reactivating old transports |
| Correlate response and recover uncertainty | worker_recovery.py, worker_dispatch.py, rollout_response.py, queue tests and real-child fixture | Exact new-turn correlation and no automatic redispatch; journal failures are isolated per retained request (see recovery checkpoint below) |
| Independent history/quota | history_sync.py, history_watch.py, versioned rollout reader, tests and fresh live checkpoint | Changed journals and quota retries survive individual-task and pending-endpoint failures |
| Autonomous catalog and desktop activity | generated local protocol schema, read-only daemon probe, exact database/catalog comparison | Incomplete: no accessible authoritative catalog source; static task activity also needs reconciliation independent of request result status |
| Decompose frontend | API domain files; session/navigation/composer hooks; conversation/login/access/project components | Stateful boundaries extracted; sidebar/header still composed in App, without requiring another runtime framework |
| Preserve shared history, quota, scroll and PWA | history policy/reader tests; browser regression suite; live history count | Automatic behavior covered; live participant and installed iPhone tests remain separate |
| Deduplicate private notifications | push tests and intent-before-I/O implementation | Turn identity shared across response/history; uncertain sends not retried; provider mocks/encryption tests are not device delivery |
| Actionable diagnostics | worker_health.py, cloud/worker_status.py, owner diagnostics, live report | Content-free waiting/reconciliation counters received on VM; last-pass timestamp explicitly distinguished from live execution |
| Safe operational update | idle queue lock check, launchctl state, live VM service and database probes | Both local services running, fresh checkpoints; desktop not restarted |

## Runtime checkpoint

The SSH probe of the deployed VM reported schema 3, `quick_check=ok`, zero
foreign-key violations and an active web service. History contained 5,260 public
message rows. There was one bound member identity and zero push subscriptions;
those observations do not support claiming brother-login or iPhone acceptance.
The request service's actual report was idle with zero waiting/unresolved counts.
Both local launchd services were running and their checkpoints were fresh.
These are point-in-time observations, not continuous availability guarantees.

## Remaining work, without narrowing the goal

1. Verify recovery behavior in future real uncertainty incidents; automatic tests
   now cover isolated missing/malformed journals without resubmission.
2. Reconcile ordinary desktop task activity independently of the static catalog.
   Do not equate a stored active label or an old final message with a live process.
3. Obtain an accessible authoritative project/task catalog source. Preserve exact
   app project identity; do not infer grants from cwd or replace the working
   catalog with the mismatched local state database.
4. Complete real participant login, scoped access, approval and attachment round
   trip, plus installed iPhone permission and delivery of approval/answer pushes.
5. Re-audit the full objective after the above changes, including deployed state.

The catalog limitation and external acceptance do not prevent work on recovery
isolation or activity reconciliation. The goal therefore remains active.

## Recovery isolation checkpoint

`worker_recovery.collect` now treats recognized journal read/format failures as
an unresolved result before any queue mutation. Database/queue transition errors
are not swallowed. Tests retain an uncertain request, enqueue a later request
for the same task and an independent valid task, then perform repeated passes:
only the independent task executes once; original intent is unchanged and the
same-task request remains pending. Missing and malformed journals are covered.
The full suite passes 219 collected Python cases.
