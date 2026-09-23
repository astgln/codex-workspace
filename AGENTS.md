# Codex Workspace

## Scope and references

This repository owns the web/PWA client, ciphertext relay and outbound local
collectors for existing Codex tasks. Telegram supplies login only.
Task-coordination authorization belongs in the user's global AGENTS.md; do not
copy it here. Do not import unrelated workspace rules or game-specific paths.

Read the relevant maintained reference before changing its subsystem:
- [Architecture](docs/architecture.md)
- [E2EE protocol and limitations](docs/e2ee.md)
- [Security](docs/security.md)
- [Deployment](docs/deployment.md)
- [Collectors and recovery](docs/collector-routing.md)

Keep host addresses, resource IDs, PIDs, release hashes and operational procedures
out of this file. Procedures belong in the references above; installation-specific
values belong in private configuration and concise private verification records.
Never copy secret configuration values into documentation.

## Branches and source control

- Verify the actual Git root, branch and working-tree status before edits. Use an
  explicit working directory; do not recreate a retired checkout or switch another
  task's branch. The experimental checkout is `worktrees/experimental` under the
  main checkout and is a registered Git worktree.
- `main` is strictly single-user. Keep participant management, approval workflows
  and their product wording in `experimental/multi-user` only.
- Put shared fixes in `main`, then rebase the experimental branch onto it, retaining
  the experimental extension. Review conflict resolutions and verify the affected
  behavior in both variants.
- Use Conventional Commits and SSH GitHub remotes. Preserve unrelated changes.
  Honor existing authorization to commit/push; do not create empty commits.
- When a rebase requires rewriting an authorized experimental remote branch, read
  its actual remote commit and use an explicit `--force-with-lease` for that ref.
  Never guess the lease value or use unconditional force.
- The existing Yandex Cloud installation deploys **experimental/multi-user only**.
  Verify the configured destination and branch. Do not deploy merely because a
  change is committed or another task asks; preserve the user's authorized scope.

## Encryption and trust boundaries

- Preserve mandatory E2EE once the local/server/browser mode is pinned. Missing
  keys, invalid signatures, damaged pins or network errors must fail closed;
  never enable plaintext fallback to make a feature work.
- The relay does not receive decryption keys or establish execution permissions.
  Telegram login alone does not enroll a trusted device. Verify signed intent,
  target, attachments, replay protection and local authorization before execution.
- In experimental, enforce task/project grants, task exclusions and approvals at
  the trusted endpoint. A server-controlled role cannot widen cryptographic access.
- Never output tokens, cookies, private/recovery keys, pairing secrets, `.env` or
  whole secret configurations. Programs may consume required private values;
  diagnostics should project only necessary non-secret fields or counters.
- Do not reset keys, enroll devices, discard data or rerun a fresh-start operation
  as a troubleshooting shortcut. Such changes need authorization within the task.
- Keep the documented threat model honest: a compromised web client can expose
  browser keys; E2EE is not proof of corporate approval or an independent audit.

## Running services and request safety

- Inspect current queue state and active consumers before changing collectors.
  Prefer graceful shutdown of the specific collector; do not interrupt execution
  on the strength of an old status file. Never run duplicate collectors for one queue.
- Do not delete writer locks or clear/requeue uncertain dispatches. Reconcile the
  original request with its exact turn; an exit code alone does not prove delivery.
- Preserve the selected task's saved filesystem, network and execution settings.
  Missing settings are a reason to wait, not to invent broader permissions.
- Do not restart Codex or modify its settings, corporate controls, VPN, TLS or
  sandbox to resolve a bridge problem without separate applicable authorization.
- Coordinate shared-host deployment windows and leave unrelated services alone.
  Verify installed release identity and health after an authorized deployment.

## Verification and completion

- Scale checks to the change. Documentation-only edits need link/diff checks,
  not application test suites or a deployment.
- For protocol/auth/transport changes, check affected paths across catalog/history,
  sending/replies, attachments, quota, diagnostics and push. Auxiliary features
  must not retain plaintext API calls after E2EE activation.
- Exercise relevant failure cases: tampering, replay, revocation, partial batches,
  lost acknowledgements and concurrent collection. Verify experimental ACL behavior
  separately from the single-user baseline.
- For frontend changes, build the client and service worker and run relevant
  browser tests. Report real iOS/PWA verification separately from browser automation.
- Distinguish source tests, deployed revision, collector health and a real browser
  round trip. A verified request waiting for a desktop lock is not a completed reply.
  Report remaining limitations without presenting them as completed checks.
- Reuse working dependencies and keep disposable files in OS temporary storage or
  a task-owned ignored directory. Remove verified task-owned scratch at completion;
  preserve live keys, queues, user data and other tasks' files.
