"""Routine engine: deterministic caregiver rules over labelled Ring events.

KinWatch alerts on what DIDN'T happen as well as what did:
  R1 no_activity    - no sign of the parent at the door by the morning deadline
  R2 package_waiting - a delivery (e.g. medicines) left uncollected for N minutes
  R3 night_visitor  - a person at the door during night hours
Animals and empty frames never alert: that's the "smart, not noisy" part.

Rules are pure functions of (events, config, now), so a demo clock can
fast-forward time:   python -m kinwatch.rules --at 10:05
                     python -m kinwatch.rules --advance 65
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class RoutineConfig:
    parent_name: str = "Amma"
    tz: timezone = IST
    day_start: str = "05:00"          # activity before this counts as night
    activity_deadline: str = "10:00"  # expect to see the parent by this time
    package_minutes: int = 60         # alert if a package sits this long
    night_start: str = "22:00"
    night_end: str = "05:00"
    activity_labels: tuple = ("person",)


@dataclass
class Alert:
    key: str                  # stable id so the same alert is only sent once
    rule: str
    severity: str             # "high" | "medium"
    title: str
    message: str
    event_id: str | None = None
    at_ms: int = 0
    extra: dict = field(default_factory=dict)


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _local(ms: int, tz) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=tz)


def _at(day: datetime, hm: str) -> datetime:
    h, m = _hm(hm)
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def _in_night(t: datetime, cfg: RoutineConfig) -> bool:
    start, end = _hm(cfg.night_start), _hm(cfg.night_end)
    cur = (t.hour, t.minute)
    return cur >= start or cur < end if start > end else start <= cur < end


def _vision(ev: dict) -> dict:
    v = ev.get("vision")
    if isinstance(v, str):
        try:
            return json.loads(v) if v else {}
        except json.JSONDecodeError:
            return {}
    return v or {}


def evaluate(events: list[dict], now_ms: int, cfg: RoutineConfig | None = None) -> list[Alert]:
    """events: dicts with id, device_name, start_ms, kw_label, vision (json/dict)."""
    cfg = cfg or RoutineConfig()
    now = _local(now_ms, cfg.tz)
    today_start = _at(now, cfg.day_start)
    evs = sorted(events, key=lambda e: e["start_ms"])
    alerts: list[Alert] = []

    # R1: no activity by the deadline (an absence alert: nothing happened)
    deadline = _at(now, cfg.activity_deadline)
    if now >= deadline:
        seen = [e for e in evs
                if today_start <= _local(e["start_ms"], cfg.tz) <= now
                and (e.get("kw_label") in cfg.activity_labels
                     or _vision(e).get("person_visible"))]
        if not seen:
            alerts.append(Alert(
                key=f"no_activity:{now.date()}", rule="no_activity", severity="high",
                title=f"No sign of {cfg.parent_name} yet this morning",
                message=(f"It's {now:%H:%M} and nobody has been seen at the front door since "
                         f"{cfg.day_start}. {cfg.parent_name} usually starts the day before "
                         f"{cfg.activity_deadline}. Maybe give her a call?"),
                at_ms=now_ms))

    # R2: package left uncollected
    for i, e in enumerate(evs):
        v = _vision(e)
        if not (e.get("kw_label") == "package" or v.get("package_visible")):
            continue
        later = [x for x in evs[i + 1:] if x.get("device_name") == e.get("device_name")]
        collected = any(_vision(x) and not _vision(x).get("package_visible") for x in later)
        waited = (now_ms - e["start_ms"]) / 60000
        if not collected and waited >= cfg.package_minutes:
            t = _local(e["start_ms"], cfg.tz)
            alerts.append(Alert(
                key=f"package_waiting:{e['id']}", rule="package_waiting", severity="medium",
                title="A delivery is still waiting at the door",
                message=(f"A package arrived at {t:%H:%M} and has been sitting at the "
                         f"{e.get('device_name') or 'front door'} for {int(waited)} min. "
                         f"{v.get('description', '')}".strip()),
                event_id=e["id"], at_ms=now_ms))

    # R3: person at the door at night
    for e in evs:
        t = _local(e["start_ms"], cfg.tz)
        if t > now or not _in_night(t, cfg):
            continue
        v = _vision(e)
        if e.get("kw_label") == "person" or v.get("person_visible"):
            alerts.append(Alert(
                key=f"night_visitor:{e['id']}", rule="night_visitor", severity="high",
                title="Someone at the door at night",
                message=(f"At {t:%H:%M} a person was seen at the "
                         f"{e.get('device_name') or 'front door'}. "
                         f"{v.get('description', '')}".strip()),
                event_id=e["id"], at_ms=e["start_ms"]))
    return alerts


def summarize(events: list[dict], now_ms: int, cfg: RoutineConfig | None = None) -> dict:
    """Numbers for the daily summary / dashboard."""
    cfg = cfg or RoutineConfig()
    now = _local(now_ms, cfg.tz)
    today = [e for e in events if _local(e["start_ms"], cfg.tz).date() == now.date()]
    counts: dict[str, int] = {}
    for e in today:
        counts[e.get("kw_label") or "unlabelled"] = counts.get(e.get("kw_label") or "unlabelled", 0) + 1
    ignored = counts.get("animal", 0) + counts.get("nothing", 0)
    return {"date": str(now.date()), "events": len(today), "by_label": counts,
            "ignored_as_noise": ignored}


def demo_now(at: str | None = None, advance_min: float = 0, tz=IST) -> int:
    now = datetime.now(tz)
    if at:
        now = _at(now, at)
    return int((now + timedelta(minutes=advance_min)).timestamp() * 1000)


def main() -> None:
    from .store import EventStore
    ap = argparse.ArgumentParser(description="Evaluate KinWatch routine rules")
    ap.add_argument("--db", default="kinwatch.db")
    ap.add_argument("--at", help="pretend the time is HH:MM today (IST)")
    ap.add_argument("--advance", type=float, default=0, help="fast-forward N minutes")
    ap.add_argument("--deadline", default="10:00", help="morning activity deadline")
    ap.add_argument("--package-minutes", type=int, default=60)
    ap.add_argument("--notify", action="store_true",
                    help="send new alerts to Telegram (each alert only once)")
    args = ap.parse_args()

    cfg = RoutineConfig(activity_deadline=args.deadline, package_minutes=args.package_minutes)
    now_ms = demo_now(args.at, args.advance) if (args.at or args.advance) else int(time.time() * 1000)
    store = EventStore(args.db)
    events = [dict(r) for r in store.recent(500)]
    print(f"Demo clock: {_local(now_ms, IST):%d %b %H:%M IST}  ({len(events)} events)")
    if args.notify:
        from .notify import Notifier
        from .poller import check_rules
        check_rules(store, now_ms=now_ms, cfg=cfg, notifier=Notifier())
    alerts = evaluate(events, now_ms, cfg)
    for a in alerts:
        print(f"[{a.severity.upper()}] {a.title}\n        {a.message}")
    if not alerts:
        print("All normal. No alerts.")
    print("Summary:", json.dumps(summarize(events, now_ms, cfg)))


if __name__ == "__main__":
    main()
