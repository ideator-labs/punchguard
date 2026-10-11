# AGENTS.md - PunchGuard

Cold-start handoff for a coding agent with no prior context.

## What it is and the one claim

Cafe and restaurant managers approve payroll from clock punches. Many shops
trust punches alone. Early clock-ins, late outs, forgotten clock-outs, and
quiet overtime slip into the check before anyone compares the published
schedule.

PunchGuard joins each punch to the matching Shift for the same employee on
the same local day, then classifies before approve. Two policies:

- `trust_punches` (control): never compares to schedule. Every closed or open
  punch is primary `ok`. Pays everything.
- `punchguard`: compare to Shift and week hours. Flags:
  - `ok` within grace of scheduled shift and under OT cap
  - `early_in` clock-in before `shift.start - early_grace_min`
  - `late_out` clock-out after `shift.end + late_grace_min`
  - `missed_clockout` has `in_at`, no `out_at`, and `as_of` is past
    `shift.end + late_grace_min`
  - `ot_risk` if accepting this punch's paid minutes would push the
    employee's Mon-Sun week hours over `ot_weekly_hours` (default 40)

A punch can carry multiple flags. `primary` is the highest severity:
`missed_clockout` > `ot_risk` > `early_in` / `late_out` > `ok`.

The claim `bash demo.sh` proves. On SAMPLE Harbor Brew Cafe fixtures with
`as_of=2026-10-11T19:00:00`, `trust_punches` marks Ava, Ben, Cara, and Dee
all `ok`. `punchguard` marks Ava `early_in`, Ben `late_out`, Cara
`missed_clockout`, Dee `ot_risk` (38h prior + 8h today = 46h > 40).

All fixture data is SAMPLE / fictional. Shop and employees are made up.

Note on `as_of`: the product brief floated `14:00`, but Cara's shift ends at
`18:00`. Demo uses `19:00` so `missed_clockout` is past `end + grace`. That
keeps the stated Cara classification true.

## Status: real vs stubbed

Real:

- Shift and Punch load from JSON (`fixture_to_models`).
- Policies `punchguard` and `trust_punches` with flags + primary above.
- Week OT from prior punches in the Mon-Sun week containing `as_of`.
- Text render and JSON run output via `src/cli.py`.
- Self-checking `demo.sh` with five checks and `demo.sh --break`.

Stubbed or not built:

- No live POS, 7shifts, When I Work, or Homebase connector.
- No payroll export. Flags are classification only.
- No manager approve UI. No SMS alert.
- No geofence or biometric anti-buddy-punch.
- No Hivemind OS, Workflow Core, or dbl-entry integration.

## Data shape (with paths)

Frozen dataclasses live at the top of `src/punchguard.py`.

| Type | Fields | Notes |
|------|--------|-------|
| `Shift` | `employee_id`, `employee_name`, `start`, `end` | ISO local datetimes. |
| `Punch` | `employee_id`, `in_at`, `out_at` | `out_at` null if still open. |
| `Policy` | `name`, `early_grace_min`, `late_grace_min`, `ot_weekly_hours` | Defaults 5 / 5 / 40. |
| `Flagged` | `employee_id`, `punch_in`, `primary`, `flags`, `paid_minutes`, `reasons`, optional `scheduled_*`, `employee_name` | One row per today's punch. |
| `Run` | `policy`, `as_of`, `shop`, `flagged` | Helpers: `primaries`, `exception_count`, `to_dict`. |

Matching: same `employee_id` and same local calendar day as `punch.in_at`.
If several shifts that day, closest `start` to punch-in wins.

Paid minutes: `out_at - in_at` when closed; else `as_of - in_at` (floor 0).

Fixtures:

- `fixtures/harbor_brew.json` (SAMPLE Harbor Brew Cafe)
- `fixtures/expected.json` (expected primaries for both policies)

## Repo map

```
punchguard/
  AGENTS.md
  README.md
  LICENSE
  requirements.txt   # empty on purpose; stdlib only
  sources.md
  demo.sh
  .gitignore
  src/
    punchguard.py    # types, classify, render
    cli.py           # check entrypoint
  fixtures/          # SAMPLE shifts + punches + expected
  data/              # gitignored run output from demo.sh
```

## Verified run steps

Fresh clone:

```bash
cd /path/to/punchguard
bash demo.sh
```

Expect five PASS lines, then `SUMMARY: 5 passed, 0 failed` and `ALL CLAIMS PASSED`,
exit 0.

Break check (must fail, then restore by running without `--break`):

```bash
bash demo.sh --break
# expect non-zero exit; CHECK 2 FAIL (Ava early_in skipped); SUMMARY includes failed
bash demo.sh
# expect exit 0 again
```

`--break` passes `--skip-early` to the punchguard CLI run so Ava is no longer
`early_in`. That sabotages CHECK 2 on purpose.

Manual one-shot:

```bash
PYTHONPATH=src python3 src/cli.py check \
  --fixture fixtures/harbor_brew.json \
  --policy punchguard \
  --out data/punchguard.json
```

## Design decisions

1. `trust_punches` is the control. It shows what payroll looks like when
   nobody joins punches to the published schedule.
2. Classification is pure and `as_of`-driven. No live clock side effects.
3. OT uses a fixed Mon-Sun week containing `as_of`, summing other punches for
   that employee plus this punch's paid minutes.
4. Stdlib only. No pip install step for the demo.
5. Demo classifies today's punches only (same local day as `as_of`). Prior
   week punches feed OT only.

## Limits

- No live timeclock or schedule sync.
- Open punches use `as_of` for paid minutes; real payroll may use scheduled
  end or a different cut.
- One shop fixture. Multi-location and roles are out of scope.
- Grace and OT thresholds are fixture defaults, not per-employee rules.
- `early_in` and `late_out` can both fire; `primary` picks highest severity.
  There is no separate `late_in` flag in this POC.

## Prioritized next steps

1. Add a `late_in` flag (clock-in after start + grace).
   Done when: fixture Ben-like late arrival classifies `late_in` and a demo
   check covers it.
2. Export a payroll exception CSV (employee, primary, paid_minutes, reasons).
   Done when: `cli.py export-csv` writes a file and demo asserts row count 4
   under punchguard.
3. Import a 7shifts or When I Work schedule CSV plus a timeclock CSV.
   Done when: `cli.py import-csv` writes fixture JSON and `bash demo.sh`
   still passes on SAMPLE data.

## Working rules

- Keep prose short. No em-dashes. Label SAMPLE data clearly.
- Prove changes with `bash demo.sh`. Run `--break` once when changing checks.
- Do not add pip dependencies unless the claim needs them.
- Commit as `danielgerlag <daniel@gerlag.ca>`.

## Sources

See `sources.md`. Only those three real URLs are cited.
