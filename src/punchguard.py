"""PunchGuard: join schedules to clock punches before payroll approve.

Policies: trust_punches (control, all ok) vs punchguard (compare to Shift).
Pure stdlib. SAMPLE / fictional fixtures only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

PolicyName = Literal["trust_punches", "punchguard"]
Flag = Literal["ok", "early_in", "late_out", "missed_clockout", "ot_risk"]

# Highest severity first for primary selection.
SEVERITY: tuple[Flag, ...] = (
    "missed_clockout",
    "ot_risk",
    "early_in",
    "late_out",
    "ok",
)

DEFAULT_EARLY_GRACE_MIN = 5
DEFAULT_LATE_GRACE_MIN = 5
DEFAULT_OT_WEEKLY_HOURS = 40.0


@dataclass(frozen=True)
class Shift:
    employee_id: str
    employee_name: str
    start: str  # ISO datetime local
    end: str


@dataclass(frozen=True)
class Punch:
    employee_id: str
    in_at: str  # ISO datetime local
    out_at: str | None


@dataclass(frozen=True)
class Policy:
    name: PolicyName
    early_grace_min: int = DEFAULT_EARLY_GRACE_MIN
    late_grace_min: int = DEFAULT_LATE_GRACE_MIN
    ot_weekly_hours: float = DEFAULT_OT_WEEKLY_HOURS


@dataclass(frozen=True)
class Flagged:
    employee_id: str
    punch_in: str
    primary: Flag
    flags: list[str]
    paid_minutes: int
    reasons: list[str]
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    employee_name: str | None = None


@dataclass
class Run:
    policy: PolicyName
    as_of: str
    shop: str
    flagged: list[Flagged] = field(default_factory=list)

    def by_employee(self) -> dict[str, Flagged]:
        return {f.employee_id: f for f in self.flagged}

    def primaries(self) -> dict[str, str]:
        return {f.employee_id: f.primary for f in self.flagged}

    def exception_count(self) -> int:
        return sum(1 for f in self.flagged if f.primary != "ok")

    def paid_minutes_total(self) -> int:
        return sum(f.paid_minutes for f in self.flagged)

    def to_dict(self) -> dict:
        return {
            "policy": self.policy,
            "as_of": self.as_of,
            "shop": self.shop,
            "flagged": [asdict(f) for f in self.flagged],
            "primaries": self.primaries(),
            "exception_count": self.exception_count(),
            "paid_minutes_total": self.paid_minutes_total(),
        }


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def minutes_between(a: datetime, b: datetime) -> int:
    """Whole minutes from a to b (b - a). Negative if b before a."""
    return int((b - a).total_seconds() // 60)


def punch_paid_minutes(punch: Punch, as_of: datetime) -> int:
    start = parse_dt(punch.in_at)
    if punch.out_at:
        end = parse_dt(punch.out_at)
    else:
        end = as_of
    return max(0, minutes_between(start, end))


def local_day(dt: datetime) -> str:
    return dt.date().isoformat()


def week_bounds_containing(as_of: datetime) -> tuple[datetime, datetime]:
    """Mon 00:00 through Sun end-of-day for the week containing as_of."""
    # Monday = 0
    monday = as_of.date() - timedelta(days=as_of.weekday())
    week_start = datetime.combine(monday, datetime.min.time())
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def match_shift(punch: Punch, shifts: list[Shift]) -> Shift | None:
    pin = parse_dt(punch.in_at)
    day = local_day(pin)
    candidates = [
        s
        for s in shifts
        if s.employee_id == punch.employee_id and local_day(parse_dt(s.start)) == day
    ]
    if not candidates:
        return None
    # Prefer shift whose start is closest to punch-in.
    candidates.sort(key=lambda s: abs(minutes_between(parse_dt(s.start), pin)))
    return candidates[0]


def week_minutes_before_punch(
    punch: Punch,
    all_punches: list[Punch],
    as_of: datetime,
) -> int:
    """Sum paid minutes of other punches in the same Mon-Sun week before this punch."""
    week_start, week_end = week_bounds_containing(as_of)
    pin = parse_dt(punch.in_at)
    total = 0
    for p in all_punches:
        if p.employee_id != punch.employee_id:
            continue
        other_in = parse_dt(p.in_at)
        if other_in == pin and p.out_at == punch.out_at:
            continue  # skip the punch under review
        if other_in < week_start or other_in >= week_end:
            continue
        total += punch_paid_minutes(p, as_of)
    return total


def pick_primary(flags: list[str]) -> Flag:
    for sev in SEVERITY:
        if sev in flags:
            return sev
    return "ok"


def classify_punch(
    punch: Punch,
    shifts: list[Shift],
    all_punches: list[Punch],
    policy: Policy,
    as_of: datetime,
) -> Flagged:
    paid = punch_paid_minutes(punch, as_of)
    shift = match_shift(punch, shifts)
    name = shift.employee_name if shift else None
    sched_start = shift.start if shift else None
    sched_end = shift.end if shift else None

    if policy.name == "trust_punches":
        reasons = ["policy:trust_punches", "no_schedule_compare"]
        return Flagged(
            employee_id=punch.employee_id,
            punch_in=punch.in_at,
            primary="ok",
            flags=["ok"],
            paid_minutes=paid,
            reasons=reasons,
            scheduled_start=sched_start,
            scheduled_end=sched_end,
            employee_name=name,
        )

    # punchguard
    flags: list[str] = []
    reasons: list[str] = ["policy:punchguard"]

    if shift is None:
        reasons.append("no_matching_shift")
        # Still check OT against week punches.
    else:
        start = parse_dt(shift.start)
        end = parse_dt(shift.end)
        pin = parse_dt(punch.in_at)
        early_cutoff = start - timedelta(minutes=policy.early_grace_min)
        late_cutoff = end + timedelta(minutes=policy.late_grace_min)

        if pin < early_cutoff:
            flags.append("early_in")
            early_by = minutes_between(pin, start)
            reasons.append(
                f"early_in:{early_by}min_before_start_grace={policy.early_grace_min}"
            )

        if punch.out_at is None:
            if as_of > late_cutoff:
                flags.append("missed_clockout")
                reasons.append(
                    f"missed_clockout:as_of>{late_cutoff.isoformat()}"
                )
            else:
                reasons.append("open_punch_within_shift_window")
        else:
            pout = parse_dt(punch.out_at)
            if pout > late_cutoff:
                flags.append("late_out")
                late_by = minutes_between(end, pout)
                reasons.append(
                    f"late_out:{late_by}min_after_end_grace={policy.late_grace_min}"
                )

    prior = week_minutes_before_punch(punch, all_punches, as_of)
    week_total = prior + paid
    ot_limit_min = int(policy.ot_weekly_hours * 60)
    if week_total > ot_limit_min:
        flags.append("ot_risk")
        reasons.append(
            f"ot_risk:week_minutes={week_total}>{ot_limit_min}"
            f"(prior={prior}+paid={paid})"
        )

    if not flags:
        flags = ["ok"]
        reasons.append("within_grace")

    primary = pick_primary(flags)
    return Flagged(
        employee_id=punch.employee_id,
        punch_in=punch.in_at,
        primary=primary,
        flags=flags,
        paid_minutes=paid,
        reasons=reasons,
        scheduled_start=sched_start,
        scheduled_end=sched_end,
        employee_name=name,
    )


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


def fixture_to_models(raw: dict) -> tuple[str, str, list[Shift], list[Punch], Policy]:
    shop = raw["shop"]
    as_of = raw["as_of"]
    shift_keys = {"employee_id", "employee_name", "start", "end"}
    punch_keys = {"employee_id", "in_at", "out_at"}
    shifts = [Shift(**{k: s[k] for k in shift_keys}) for s in raw["shifts"]]
    punches = [Punch(**{k: p[k] for k in punch_keys}) for p in raw["punches"]]
    pol = raw.get("policy_defaults", {})
    # policy name filled by caller
    base = Policy(
        name="punchguard",
        early_grace_min=int(pol.get("early_grace_min", DEFAULT_EARLY_GRACE_MIN)),
        late_grace_min=int(pol.get("late_grace_min", DEFAULT_LATE_GRACE_MIN)),
        ot_weekly_hours=float(pol.get("ot_weekly_hours", DEFAULT_OT_WEEKLY_HOURS)),
    )
    return shop, as_of, shifts, punches, base


def today_punches(punches: list[Punch], as_of: datetime) -> list[Punch]:
    day = local_day(as_of)
    return [p for p in punches if local_day(parse_dt(p.in_at)) == day]


def run_policy(
    shifts: list[Shift],
    punches: list[Punch],
    as_of: str,
    policy_name: PolicyName,
    shop: str,
    early_grace_min: int = DEFAULT_EARLY_GRACE_MIN,
    late_grace_min: int = DEFAULT_LATE_GRACE_MIN,
    ot_weekly_hours: float = DEFAULT_OT_WEEKLY_HOURS,
) -> Run:
    policy = Policy(
        name=policy_name,
        early_grace_min=early_grace_min,
        late_grace_min=late_grace_min,
        ot_weekly_hours=ot_weekly_hours,
    )
    as_of_dt = parse_dt(as_of)
    run = Run(policy=policy_name, as_of=as_of, shop=shop)
    # Classify today's punches only (payroll approve surface).
    for punch in today_punches(punches, as_of_dt):
        run.flagged.append(
            classify_punch(punch, shifts, punches, policy, as_of_dt)
        )
    return run


def render_run(run: Run) -> str:
    lines = [
        f"shop={run.shop} policy={run.policy} as_of={run.as_of}",
        "SAMPLE / fictional cafe punches vs schedule",
        "",
    ]
    for f in run.flagged:
        name = f.employee_name or f.employee_id
        sched = ""
        if f.scheduled_start and f.scheduled_end:
            sched = f" sched={f.scheduled_start[11:16]}-{f.scheduled_end[11:16]}"
        lines.append(
            f"  {name:<6} {f.employee_id:<10} primary={f.primary:<16} "
            f"flags={f.flags} paid_min={f.paid_minutes}{sched}"
        )
        for r in f.reasons:
            lines.append(f"           {r}")
    lines.append("")
    lines.append(
        f"exceptions (primary!=ok): {run.exception_count()} "
        f"paid_minutes_today={run.paid_minutes_total()}"
    )
    return "\n".join(lines)


def write_run(run: Run, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.to_dict(), indent=2) + "\n")
