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
| Autonomous catalog and desktop activity | desktop_catalog.py, lifecycle checkpoints, writer-lock probe and live 22-task comparison | Implemented via read-only desktop persistence; see limitations and live verification below |
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

## Remaining acceptance work

The owner has confirmed installed iPhone navigation and notification delivery.
The later request for message previews was implemented and deployed; observation
of that new presentation on the phone is still pending. The brother's real login,
scoped access, approval and attachment round trip remain unverified. Automated
tests do not replace these actions. The full goal is not yet complete.

Autonomous catalog discovery and turn-activity reconciliation, previously listed
as blockers here, are implemented and verified as described below. Subsequent
entries record historical checkpoints; their older device/source limitations
are superseded by the explicit acceptance follow-ups at the end of this audit.

## Recovery isolation checkpoint

`worker_recovery.collect` now treats recognized journal read/format failures as
an unresolved result before any queue mutation. Database/queue transition errors
are not swallowed. Tests retain an uncertain request, enqueue a later request
for the same task and an independent valid task, then perform repeated passes:
only the independent task executes once; original intent is unchanged and the
same-task request remains pending. Missing and malformed journals are covered.
The full suite passes 219 collected Python cases.

## Explicit aborted turns

Journal inspection confirmed `turn_aborted` records carry exact turn identity.
Recovery now accepts this as terminal failure only after matching the approved
prompt to one new turn after baseline in the correct task. A fixed public error
replaces internal abort reason/details. Conflicting completed/aborted records
remain unresolved. Queue publication closes a failed result without redispatch.
Tests cover another turn's abort, conflicting terminal records, withheld private
reason and repeated recovery after abort publication. Full suite: 223 cases.

Lifecycle records alone still do not prove current process liveness after a crash;
a stored task_started is not sufficient for authoritative live activity. Real
member and iPhone checks remain unavailable according to the owner's latest reply.

## Authoritative catalog refresh checkpoint

A fresh app-tool listing returned complete available sources/hosts and preserved
the existing app project IDs. The local state database uses different IDs even
for identically named projects; name-based reconciliation remains invalid.
The bounded listing discovered one additional project task. A whitelisted snapshot
(ID, title, exact project ID and status only) was published successfully, then
atomically installed as the common catalog for both local services. Existing
read-only restrictions and entries absent from the bounded listing were retained.
The catalog now contains 22 tasks. This is an explicit maintenance refresh, not
an autonomous discovery implementation and not a replacement for that requirement.

## Autonomous desktop catalog and turn activity

The previous catalog-source blocker is resolved by a read-only desktop adapter.
The installed desktop bundle explicitly uses `local-projects` and
`thread-project-assignments` in its persisted global state. These exact identities,
joined with nonarchived named task rows in SQLite, reproduce all 22 tasks and six
projects in the app-tool snapshot, including titles. SQLite project IDs, cwd and
raw first-message titles are deliberately not used to infer membership.

The existing history service now refreshes this catalog automatically. Successful
publication precedes atomic replacement of the shared worker snapshot. Existing
read-only flags survive refresh. Archived/projectless tasks are removed; explicit
project moves follow desktop assignments and server access rules. Unknown schemas,
unresolved identities, concurrent state changes and publication errors preserve
the last good snapshot. This adapter depends on private desktop persistence and
fails closed if an app update changes its schema; it is not a supported public API.

Journal reader version 2 checkpoints turn lifecycle evidence independently of
public messages. A running turn is marked active only while its writer lock is
held. Matching completion/abort clears activity; unrelated turn completion cannot
clear a newer turn. Missing evidence or a released writer produces unknown, not a
stale active claim. This represents observed turn execution, not an overarching
goal's status or an authoritative desktop process-status API.

Validation: 228 Python tests pass, including explicit project movement, archive
and projectless exclusion, preserved restrictions, publication/schema failure and
incremental activity identity. Live read-only discovery matched all existing
catalog identities and names. Only the history launchd service was restarted;
Codex desktop and its running tasks were not restarted. Participant and installed
iPhone push acceptance remain pending because both testers are unavailable.

Live follow-up: the service completed replay of all 22 version-2 checkpoints;
its pass reported 5,358 messages, zero failed tasks and zero failed services,
then incremental publication resumed. The initial partial pass recovered without
restarting the worker or resending any user request.

## PWA navigation acceptance follow-up

The owner reported an installed PWA could not switch tasks and had not shown
notifications. The header lacked the top safe-area inset even though the app uses
`viewport-fit=cover` and a translucent iOS status bar. The workspace now reserves
that inset, has an explicit mobile Tasks button with a 44px target, and keeps the
navigation/settings scrollable on short screens. Notification settings display
current permission/subscription state and explain the required enable action.

Production build passes. Browser coverage now has 34 cases: 33 passed together,
and the remaining installation-copy test passed after updating its renamed
settings locator. New cases cover cold phone layout with a simulated 59px inset,
two-way task switching, short-screen settings access, and subscription after a
user-activated permission tap. These are browser simulations, not verification
of an actual iOS push delivery; the owner's device check remains open.

PWA deployment follow-up: after the owner explicitly authorized direct SSH outside
VPN, binding SSH/SCP to the existing Wi-Fi interface succeeded. No VPN or system
route was changed. The VM's single SSH `/32` rule was updated to the verified
direct egress address. Release `806c604d1f3bfcee` was installed with archive hash,
migration/restore rehearsal and SSH health verification; the public site's asset
names match the local production build. CI for `b4d9593` passed unit and all 34
browser cases. A read-only server query found zero push subscriptions and zero
deliveries: actual device enablement/delivery remains unverified, not a provider
failure diagnosis.


## Confirmed iPhone acceptance and requested notification previews

The owner confirmed that the PWA menu and notifications work on the phone. This
closes those previously unverified device checks; the brother's access/attachment
round trip is still pending. The owner then requested task names and message text
in notifications. Push payloads now contain the task title and a bounded preview
of the exact request/answer, with current-access checks and existing event
deduplication unchanged. The service worker displays these fields as plain text.
Automated validation: 232 Python tests, production build, and focused worker/PWA
checks; the changed preview presentation still needs observation on the phone.
