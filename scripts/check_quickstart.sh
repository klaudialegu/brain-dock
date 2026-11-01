#!/usr/bin/env bash
# Follows the README quick start on a fresh clone of the committed code, so a broken
# demo can't come back. The commands are read from the README itself (between the
# quickstart markers), so the README and this check can't drift apart.
# The last command is the server; it runs in the background while the page is checked.
set -euo pipefail

repo=$(git rev-parse --show-toplevel)
port=8000
work=$(mktemp -d)
server_pid=""
cleanup() {
  if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

if curl -s -o /dev/null "http://127.0.0.1:$port/"; then
  echo "Port $port is already in use; stop the running server first." >&2
  exit 1
fi

# Committed files only, like a reviewer cloning from GitHub.
git clone --quiet --no-local "$repo" "$work/brain-dock"
cd "$work/brain-dock"

commands=()
while IFS= read -r line; do
  commands+=("$line")
done < <(sed -n '/<!-- quickstart:start -->/,/<!-- quickstart:end -->/p' README.md \
  | sed -n '/^```/,/^```/p' | grep -v '^```' | grep -v '^\s*$')

if [ "${#commands[@]}" -lt 2 ]; then
  echo "No quick start found in README.md (between the quickstart markers)." >&2
  exit 1
fi
echo "Quick start from README.md (${#commands[@]} commands):"

last=$((${#commands[@]} - 1))
for i in "${!commands[@]}"; do
  echo "  \$ ${commands[$i]}"
  if [ "$i" -lt "$last" ]; then
    bash -c "${commands[$i]}" > "$work/step-$i.log" 2>&1 || {
      echo "Step failed: ${commands[$i]}" >&2
      cat "$work/step-$i.log" >&2
      exit 1
    }
  else
    # `env` lets the README write VAR=value before the command; exec keeps one process to stop.
    bash -c "exec env ${commands[$i]}" > "$work/server.log" 2>&1 &
    server_pid=$!
  fi
done

up=0
for _ in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$port/"; then up=1; break; fi
  sleep 0.5
done
if [ "$up" -ne 1 ]; then
  echo "The server didn't start within 30 seconds. Server log:" >&2
  cat "$work/server.log" >&2
  exit 1
fi

page=$(curl -s -L "http://127.0.0.1:$port/")
failed=0
check() {
  if printf '%s' "$page" | grep -qF -- "$2"; then
    echo "  ok: $1"
  else
    echo "  MISSING: $1" >&2
    failed=1
  fi
}
check "home lands on the applications page" "<h1>Career Radar</h1>"
check "demo banner" "You're looking at fake demo data"
check "demo data" "Acme Analytics"
check "pipeline chart data" 'id="pipeline-data"'
check "stats row" "Response rate"

if [ "$failed" -ne 0 ]; then
  echo "Quick start check FAILED. Server log:" >&2
  cat "$work/server.log" >&2
  exit 1
fi
echo "Quick start check passed."
