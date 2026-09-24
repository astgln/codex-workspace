#!/usr/bin/env bash
# Run from repository root. Creates/removes only a unique disposable Compose project.
set -euo pipefail
scratch=$(mktemp -d)
project="cw-check-$$"
export WORKSPACE_ORIGIN="https://localhost:${TEST_TLS_PORT:-18443}"
export WORKSPACE_PORT="${TEST_RELAY_PORT:-18081}"
export WORKSPACE_RELAY_CONFIG="$scratch/agent/relay/relay.json"
python_bin=${CRYPTO_TEST_PYTHON:-python3}
image=${WORKSPACE_TEST_IMAGE:-codex-workspace:$project}
built=0
compose=(docker compose -p "$project" -f compose.yaml -f "$scratch/override.yaml" --profile https)
cleanup() {
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  if [ "$built" = 1 ]; then docker image rm "$image" >/dev/null 2>&1 || true; fi
  rm -rf "$scratch"
}
trap cleanup EXIT
"$python_bin" -m codex_workspace setup --target docker --state "$scratch/agent" --origin "$WORKSPACE_ORIGIN"
cat > "$scratch/Caddyfile" <<'EOF'
https://localhost {
    tls internal
    reverse_proxy relay:8080
}
EOF
cat > "$scratch/override.yaml" <<EOF
services:
  relay:
    image: $image
  https:
    ports: !override ['127.0.0.1:${TEST_TLS_PORT:-18443}:443']
    volumes:
      - $scratch/Caddyfile:/etc/caddy/Caddyfile:ro
EOF
if [ -z "${WORKSPACE_TEST_IMAGE:-}" ]; then
  docker build -t "$image" -f ops/docker/Dockerfile .
  built=1
fi
"${compose[@]}" up -d --no-build --wait --wait-timeout 90
for attempt in $(seq 1 10); do
  if "${compose[@]}" cp https:/data/caddy/pki/authorities/local/root.crt "$scratch/root.crt" 2>/dev/null; then break; fi
  sleep 1
done
export SSL_CERT_FILE="$scratch/root.crt"
"$python_bin" tests/containers/smoke.py --disposable-state "$scratch/agent" --ca "$scratch/root.crt"
"${compose[@]}" up -d --no-build --force-recreate --wait --wait-timeout 90
"$python_bin" tests/containers/smoke.py --disposable-state "$scratch/agent" --ca "$scratch/root.crt" --expect-existing
