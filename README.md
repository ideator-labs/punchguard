# PunchGuard

Join published work schedules to clock punches before payroll approve.

Two policies:

- `trust_punches` (control): never compares to schedule; every punch is `ok`.
- `punchguard`: flags `early_in`, `late_out`, `missed_clockout`, `ot_risk`
  against the matching Shift and week hours.

All demo data is SAMPLE / fictional (Harbor Brew Cafe).

```bash
bash demo.sh
```

Break one check on purpose (must exit non-zero):

```bash
bash demo.sh --break
```

Full handoff for a coding agent: [AGENTS.md](./AGENTS.md).

Sources: [sources.md](./sources.md).
