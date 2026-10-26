#!/usr/bin/env bash
# Starts the real server with each installed module turned off in turn (and once with all
# off), on fake demo data, and checks the core still serves while the module's data stays
# untouched (ADR 0007). The module list comes from the registry, so new modules are covered.
set -euo pipefail

port=8000
work=$(mktemp -d)
server_pid=""
stop_server() {
  if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; fi
  server_pid=""
}
trap 'stop_server; rm -rf "$work"' EXIT

if curl -s -o /dev/null "http://127.0.0.1:$port/"; then
  echo "Port $port is already in use; stop the running server first." >&2
  exit 1
fi

db="$work/demo.db"
# Fake data only: the demo set, loaded into a throwaway database.
uv run python - "$db" <<'PY'
import sys
from brain_dock.core.db import get_engine, migrate
from brain_dock.modules.job_search.importer import DEMO_JSON, load_applications, rebuild_db
engine = get_engine(f"sqlite:///{sys.argv[1]}")
migrate(engine)
rebuild_db(engine, load_applications(DEMO_JSON), locked=False)
from sqlmodel import Session
from brain_dock.modules.job_search.models import Company
with Session(engine) as session:
    # The company page probe below must point at real data, so its 404 means "module off".
    assert session.get(Company, 1) is not None, "demo data has no company 1"
engine.dispose()
PY

# Pages with an id in the path: the manifest only lists path prefixes, so these are added
# by hand per module, on ids that exist in the demo data above.
probes() {  # module name
  case "$1" in
    job_search) echo "/companies/1" ;;
  esac
}

# One line per installed module: "name|path,path|nav label,nav label"
modules=$(uv run python -c "
from brain_dock import registry
for m in registry.installed():
    print(m.name + '|' + ','.join(m.paths) + '|' + ','.join(e.label for e in m.nav))
")
all_names=$(printf '%s\n' "$modules" | cut -d'|' -f1)

failed=0
check() {  # description, condition result
  if [ "$2" = "yes" ]; then echo "    ok: $1"; else echo "    FAILED: $1" >&2; failed=1; fi
}

run_with() {  # label, BRAIN_DOCK_MODULES value, the disabled modules' lines
  local label="$1" enabled="$2" disabled="$3"
  echo "== $label (BRAIN_DOCK_MODULES=\"$enabled\")"
  local before
  before=$(shasum -a 256 "$db" | cut -d' ' -f1)
  BRAIN_DOCK_DB="$db" BRAIN_DOCK_MODULES="$enabled" \
    uv run uvicorn brain_dock.main:app --host 127.0.0.1 --port "$port" > "$work/server.log" 2>&1 &
  server_pid=$!
  local up=no
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:$port/"; then up=yes; break; fi
    sleep 0.5
  done
  check "server started" "$up"
  if [ "$up" != "yes" ]; then cat "$work/server.log" >&2; stop_server; return; fi

  local home
  home=$(curl -s -L -D "$work/headers" "http://127.0.0.1:$port/")
  check "/ answers" "$(grep -q ' 200' "$work/headers" && echo yes || echo no)"
  check "CSP on /" "$(grep -qi '^content-security-policy:' "$work/headers" && echo yes || echo no)"
  while IFS='|' read -r name paths labels; do
    [ -z "$name" ] && continue
    IFS=',' read -ra path_list <<< "$paths"
    for probe in $(probes "$name"); do path_list+=("$probe"); done
    for path in "${path_list[@]}"; do
      local code
      code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port$path")
      check "$name off: $path is 404" "$([ "$code" = "404" ] && echo yes || echo no)"
    done
    IFS=',' read -ra label_list <<< "$labels"
    for nav_label in "${label_list[@]}"; do
      check "$name off: nav has no \"$nav_label\"" "$(printf '%s' "$home" | grep -qF ">$nav_label</a>" && echo no || echo yes)"
    done
  done <<< "$disabled"
  stop_server
  check "database file unchanged" "$([ "$(shasum -a 256 "$db" | cut -d' ' -f1)" = "$before" ] && echo yes || echo no)"
}

while IFS= read -r line; do
  name=${line%%|*}
  others=$(printf '%s\n' "$all_names" | grep -vx "$name" | paste -sd, - || true)
  run_with "$name turned off" "$others" "$line"
done <<< "$modules"
run_with "all modules turned off" "" "$modules"

if [ "$failed" -ne 0 ]; then
  echo "Modules-off check FAILED." >&2
  exit 1
fi
echo "Modules-off check passed."
