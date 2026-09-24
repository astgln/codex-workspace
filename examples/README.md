# Configuration shapes

These are descriptions, not production credentials. `codex-workspace setup`
generates the actual files with private permissions in `CODEX_WORKSPACE_STATE`.
Never copy a working configuration into this directory.

`web.json`:
```json
{"url":"https://YOUR_GATEWAY_DOMAIN.apigw.yandexcloud.net","key_file":"/absolute/private/state/client-key.env","project_id":"generated-installation-id","paused":false}
```

`history-catalog.json` starts empty and is filled from the desktop catalog:
```json
{"project_id":"generated-installation-id","projects":[],"threads":[]}
```

`deployment.json` contains `folder`, `gateway`, `project`, `settings.owner`,
`client_hash` (SHA-256 of the generated bearer), `url` and `release_branch`.
Provisioning adds verified resource IDs and addresses. The bearer itself exists
only in `client-key.env`; do not put it in deployment settings or shell arguments.
`device-auth.json` contains only `workspace` and public `authority`; it is not a
substitute for the vault or recovery material.

Gateway bootstrap uses the [official static-response extension](https://yandex.cloud/en/docs/api-gateway/concepts/extensions/dummy).
