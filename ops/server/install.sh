#!/bin/sh
set -eu
# The release directory contains source/static files and non-secret settings.
release=$1
cd "$release"
id codex-workspace >/dev/null 2>&1 || useradd --system --home-dir /var/lib/codex-workspace --shell /usr/sbin/nologin codex-workspace
mkdir -p /opt/codex-workspace /var/lib/codex-workspace
chmod 700 /var/lib/codex-workspace
python3 -m venv /opt/codex-workspace/venv
/opt/codex-workspace/venv/bin/python -m pip install --quiet --upgrade pip==26.2.1
/opt/codex-workspace/venv/bin/pip install --quiet "$release[relay]"
/opt/codex-workspace/venv/bin/python -m codex_workspace.relay.bootstrap "$release/settings.json"

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
    /opt/codex-workspace/venv/bin/python -m codex_workspace.relay.migration_check /var/lib/codex-workspace/workspace.sqlite3 /var/lib/codex-workspace/migration-backups
fi
ln -sfn "$release" /opt/codex-workspace/current
cp "$release/ops/server/codex-workspace.service" /etc/systemd/system/codex-workspace.service
systemctl daemon-reload
systemctl enable codex-workspace >/dev/null
systemctl restart codex-workspace
