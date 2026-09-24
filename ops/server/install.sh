#!/bin/sh
set -eu
# The release directory contains source/static files and non-secret settings.
release=$1
# Only immutable, digest-named release directories may enter the unit template.
case "$release" in /opt/codex-workspace/releases/*) ;; *) exit 2 ;; esac
digest=${release##*/}
[ "${#digest}" -eq 64 ] || exit 2
case "$digest" in *[!0-9a-f]*) exit 2 ;; esac
[ "$release" = "/opt/codex-workspace/releases/$digest" ] || exit 2
# A repeated deployment of the active artifact must not mutate its environment.
[ "$(readlink /opt/codex-workspace/current || true)" != "$release" ] || exit 0
cd "$release"
# Never replace the interpreter/packages used by the currently running service.
[ ! -L .venv ] || exit 2
id codex-workspace >/dev/null 2>&1 || useradd --system --home-dir /var/lib/codex-workspace --shell /usr/sbin/nologin codex-workspace
mkdir -p /opt/codex-workspace /var/lib/codex-workspace
chmod 700 /var/lib/codex-workspace
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --quiet --upgrade pip==26.2.1
"$release/.venv/bin/pip" install --quiet "$release[relay]"
"$release/.venv/bin/python" -m codex_workspace.relay.bootstrap "$release/settings.json"

chown root:codex-workspace /etc/codex-workspace /etc/codex-workspace/config.json
chmod 750 /etc/codex-workspace
chmod 640 /etc/codex-workspace/config.json
chown -R codex-workspace:codex-workspace /var/lib/codex-workspace
chmod 700 /var/lib/codex-workspace
for database_file in /var/lib/codex-workspace/workspace.sqlite3 /var/lib/codex-workspace/workspace.sqlite3-wal /var/lib/codex-workspace/workspace.sqlite3-shm; do
    [ ! -f "$database_file" ] || chmod 600 "$database_file"
done
# Rehearse against a consistent copy before changing the running release.
if [ -f /var/lib/codex-workspace/workspace.sqlite3 ]; then
    "$release/.venv/bin/python" -m codex_workspace.relay.migration_check /var/lib/codex-workspace/workspace.sqlite3 /var/lib/codex-workspace/migration-backups
fi
ln -sfn "$release" /opt/codex-workspace/current
sed "s|@RELEASE_DIR@|$release|g" "$release/ops/server/codex-workspace.service" > "$release/codex-workspace.service"
install -m 644 "$release/codex-workspace.service" /etc/systemd/system/codex-workspace.service
systemctl daemon-reload
systemctl enable codex-workspace >/dev/null
systemctl restart codex-workspace
