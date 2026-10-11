#!/usr/bin/env bash
# PunchGuard self-proving demo. SAMPLE / fictional Harbor Brew Cafe data.
# Usage: bash demo.sh [--break]
# --break sabotage early_in detection so SUMMARY fails (exit 1).
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

BREAK=0
if [ "${1:-}" = "--break" ]; then
  BREAK=1
fi

rm -rf data
mkdir -p data

passed=0
failed=0

record() {
  if [ "$1" -eq 0 ]; then
    echo "$2: PASS"
    passed=$((passed + 1))
  else
    echo "$2: FAIL"
    failed=$((failed + 1))
  fi
}

CLI=(python3 src/cli.py)
FIXTURE=fixtures/harbor_brew.json

echo "PunchGuard demo. SAMPLE / fictional cafe: Harbor Brew Cafe."
echo "Join published shifts to clock punches before payroll approve."
echo "Control policy trust_punches never compares to schedule (all ok)."
echo "Policy punchguard flags early_in, late_out, missed_clockout, ot_risk."
echo "as_of from fixture (2026-10-11T19:00:00 local)."
if [ "$BREAK" -eq 1 ]; then
  echo "BREAK MODE: early_in check is intentionally skipped on punchguard run."
fi
echo

SKIP_EARLY=()
if [ "$BREAK" -eq 1 ]; then
  SKIP_EARLY=(--skip-early)
fi

echo "=== trust_punches ==="
"${CLI[@]}" check \
  --fixture "$FIXTURE" \
  --policy trust_punches \
  --out data/trust_punches.json
echo

echo "=== punchguard ==="
"${CLI[@]}" check \
  --fixture "$FIXTURE" \
  --policy punchguard \
  --out data/punchguard.json \
  "${SKIP_EARLY[@]}"
echo

echo "=== checks ==="

rc=0
python3 - <<'PY' || rc=1
import json
exp = json.load(open("fixtures/expected.json"))["trust_punches"]
run = json.load(open("data/trust_punches.json"))
by = run["primaries"]
ok = (
    by["emp_ava"] == exp["emp_ava"]
    and by["emp_ben"] == exp["emp_ben"]
    and by["emp_cara"] == exp["emp_cara"]
    and by["emp_dee"] == exp["emp_dee"]
    and run["exception_count"] == exp["exception_count"]
)
# No exception flags under trust
for row in run["flagged"]:
    if row["primary"] != "ok" or row["flags"] != ["ok"]:
        ok = False
print(f"  trust primaries={by} exceptions={run['exception_count']}")
raise SystemExit(0 if ok else 1)
PY
record $rc "CHECK 1 (trust_punches: all primary ok, 0 exceptions)"

rc=0
python3 - <<'PY' || rc=1
import json
exp = json.load(open("fixtures/expected.json"))["punchguard"]
run = json.load(open("data/punchguard.json"))
by = run["primaries"]
ok = by.get("emp_ava") == exp["emp_ava"]
print(f"  Ava primary={by.get('emp_ava')} expected={exp['emp_ava']}")
raise SystemExit(0 if ok else 1)
PY
record $rc "CHECK 2 (punchguard: Ava primary early_in)"

rc=0
python3 - <<'PY' || rc=1
import json
exp = json.load(open("fixtures/expected.json"))["punchguard"]
run = json.load(open("data/punchguard.json"))
by = run["primaries"]
ok = by.get("emp_ben") == exp["emp_ben"]
print(f"  Ben primary={by.get('emp_ben')} expected={exp['emp_ben']}")
raise SystemExit(0 if ok else 1)
PY
record $rc "CHECK 3 (punchguard: Ben primary late_out)"

rc=0
python3 - <<'PY' || rc=1
import json
exp = json.load(open("fixtures/expected.json"))["punchguard"]
run = json.load(open("data/punchguard.json"))
by = run["primaries"]
ok = by.get("emp_cara") == exp["emp_cara"]
print(f"  Cara primary={by.get('emp_cara')} expected={exp['emp_cara']}")
raise SystemExit(0 if ok else 1)
PY
record $rc "CHECK 4 (punchguard: Cara primary missed_clockout)"

rc=0
python3 - <<'PY' || rc=1
import json
exp = json.load(open("fixtures/expected.json"))["punchguard"]
run = json.load(open("data/punchguard.json"))
by = run["primaries"]
ok = (
    by.get("emp_dee") == exp["emp_dee"]
    and run["exception_count"] == exp["exception_count"]
)
dee = next(f for f in run["flagged"] if f["employee_id"] == "emp_dee")
ok = ok and "ot_risk" in dee["flags"]
print(
    f"  Dee primary={by.get('emp_dee')} flags={dee['flags']} "
    f"exceptions={run['exception_count']}"
)
raise SystemExit(0 if ok else 1)
PY
record $rc "CHECK 5 (punchguard: Dee primary ot_risk; 4 exceptions)"

echo
echo "SUMMARY: ${passed} passed, ${failed} failed"
if [ "$failed" -ne 0 ]; then
  exit 1
fi
echo "ALL CLAIMS PASSED"
