#!/bin/sh
set -eu
# The release directory contains source/static files and non-secret settings.
release=$1
cd "$release"
id codex-workspace >/dev/null 2>&1 || useradd --system --home-dir /var/lib/codex-workspace --shell /usr/sbin/nologin codex-workspace
mkdir -p /opt/codex-workspace /var/lib/codex-workspace
python3 -m venv /opt/codex-workspace/venv
/opt/codex-workspace/venv/bin/pip install --quiet -r "$release/server/requirements.txt"
python3 "$release/server/bootstrap.py" "$release/settings.json"
if [ -f "$release/migration.json" ] && [ ! -f /var/lib/codex-workspace/workspace.sqlite3 ]; then
    /opt/codex-workspace/venv/bin/python -c 'import json; from server.store import Store; state=json.load(open("migration.json")); Store("/var/lib/codex-workspace").mutate(lambda target: (target.clear(),target.update(state)))'
fi
chown root:codex-workspace /etc/codex-workspace /etc/codex-workspace/config.json
chmod 750 /etc/codex-workspace
chmod 640 /etc/codex-workspace/config.json
chown -R codex-workspace:codex-workspace /var/lib/codex-workspace
chmod 700 /var/lib/codex-workspace
ln -sfn "$release" /opt/codex-workspace/current
cp "$release/server/codex-workspace.service" /etc/systemd/system/codex-workspace.service
systemctl daemon-reload
systemctl enable codex-workspace >/dev/null
systemctl restart codex-workspace
