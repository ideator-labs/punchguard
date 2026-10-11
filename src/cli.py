#!/usr/bin/env python3
"""CLI for PunchGuard check runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from punchguard import (
    fixture_to_models,
    load_fixture,
    render_run,
    run_policy,
    write_run,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PunchGuard schedule-vs-punch classify")
    sub = p.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="Classify today's punches under a policy")
    check.add_argument("--fixture", type=Path, required=True)
    check.add_argument(
        "--policy",
        choices=("trust_punches", "punchguard"),
        required=True,
    )
    check.add_argument("--out", type=Path, required=True)
    check.add_argument("--quiet", action="store_true")
    check.add_argument(
        "--skip-early",
        action="store_true",
        help="Sabotage path: do not flag early_in (used by demo.sh --break)",
    )

    args = p.parse_args(argv)
    raw = load_fixture(args.fixture)
    shop, as_of, shifts, punches, base = fixture_to_models(raw)

    if args.cmd == "check":
        run = run_policy(
            shifts,
            punches,
            as_of=as_of,
            policy_name=args.policy,
            shop=shop,
            early_grace_min=base.early_grace_min,
            late_grace_min=base.late_grace_min,
            ot_weekly_hours=base.ot_weekly_hours,
        )
        if args.skip_early and args.policy == "punchguard":
            # Intentional sabotage for demo.sh --break: clear early_in.
            from punchguard import Flagged, pick_primary

            fixed = []
            for f in run.flagged:
                if "early_in" not in f.flags:
                    fixed.append(f)
                    continue
                new_flags = [x for x in f.flags if x != "early_in"]
                if not new_flags:
                    new_flags = ["ok"]
                new_reasons = [r for r in f.reasons if not r.startswith("early_in:")]
                new_reasons.append("sabotage:skip_early")
                primary = pick_primary(new_flags)
                fixed.append(
                    Flagged(
                        employee_id=f.employee_id,
                        punch_in=f.punch_in,
                        primary=primary,
                        flags=new_flags,
                        paid_minutes=f.paid_minutes,
                        reasons=new_reasons,
                        scheduled_start=f.scheduled_start,
                        scheduled_end=f.scheduled_end,
                        employee_name=f.employee_name,
                    )
                )
            run.flagged = fixed

        write_run(run, args.out)
        if not args.quiet:
            print(render_run(run))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
