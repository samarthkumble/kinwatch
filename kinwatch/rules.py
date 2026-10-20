"""Routine engine: deterministic caregiver rules over labelled Ring events.

KinWatch alerts on what DIDN'T happen as well as what did:
  R1 no_activity    - no sign of the parent at the door by the morning deadline
  R2 package_waiting - a delivery (e.g. medicines) left uncollected for N minutes
  R3 night_visitor  - a person at the door during night hours
  R4 long_quiet     - seen earlier today, but nobody at the door for too long in the daytime
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
NOISE_LABELS = ("animal", "nothing")


@dataclass
class RoutineConfig:
    parent_name: str = "Ajji"
    tz: timezone = IST
    day_start: str = "05:00"          # activity before this counts as night
    activity_deadline: str = "10:00"  # expect to see the parent by this time
    package_minutes: int = 60         # alert if a package sits this long
    night_start: str = "22:00"
    night_end: str = "05:00"
    camera_name: str = "front door"   # how alerts refer to the Ring camera
    quiet_hours: int = 4              # daytime gap after which a silent door is worth a call
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


def fmt_duration(minutes: float) -> str:
    m = int(minutes)
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if m else f"{h} h"


# Template sentences from the Rekognition backend: repeating them in an alert adds nothing.
_TEMPLATE_STARTS = ("A package has been left", "Someone is at the front door",
                    "A vehicle is outside", "An animal is near", "Something moved")


def _detail(v: dict) -> str:
    """Extra detail worth adding to an alert message ('' if it would just repeat it)."""
    desc = (v.get("description") or "").strip()
    if desc.startswith(_TEMPLATE_STARTS):
        _, _, rest = desc.partition(". ")
        return rest.strip()
    return desc


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
                message=(f"It's {now:%H:%M} and {cfg.parent_name} hasn't been seen at the "
                         f"{cfg.camera_name} yet today. She's usually up and about before "
                         f"{cfg.activity_deadline}. Maybe give her a call?"),
                at_ms=now_ms))

    # R2: package left uncollected (today only, one alert per waiting parcel)
    today = [e for e in evs if _local(e["start_ms"], cfg.tz).date() == now.date()
             and e["start_ms"] <= now_ms]
    by_device: dict[str, list[dict]] = {}
    for e in today:
        by_device.setdefault(e.get("device_id") or e.get("device_name") or "", []).append(e)
    for dev_events in by_device.values():
        waiting_since = None          # first sighting of the parcel that is still there
        for x in dev_events:
            vx = _vision(x)
            if x.get("kw_label") == "package" or vx.get("package_visible"):
                waiting_since = waiting_since or x
            elif vx and (x.get("kw_label") or vx.get("label")) not in NOISE_LABELS:
                # a meaningful frame without the parcel means it was taken in; birds
                # or empty-motion frames (often a different angle) say nothing about it
                waiting_since = None
        if not waiting_since:
            continue
        waited = (now_ms - waiting_since["start_ms"]) / 60000
        if waited >= cfg.package_minutes:
            t = _local(waiting_since["start_ms"], cfg.tz)
            extra = _detail(_vision(waiting_since))
            alerts.append(Alert(
                key=f"package_waiting:{waiting_since['id']}", rule="package_waiting",
                severity="medium",
                title="A delivery is still waiting at the door",
                message=(f"A package arrived at {t:%H:%M} and has been at the "
                         f"{cfg.camera_name} for {fmt_duration(waited)}. "
                         f"{cfg.parent_name} may not have seen it. {extra}").strip(),
                event_id=waiting_since["id"], at_ms=now_ms))

    # R3: person at the door at night
    for e in evs:
        t = _local(e["start_ms"], cfg.tz)
        # only last night (within 12 h), not every night ever recorded
        if t > now or now_ms - e["start_ms"] > 12 * 3600_000 or not _in_night(t, cfg):
            continue
        v = _vision(e)
        if e.get("kw_label") == "person" or v.get("person_visible"):
            alerts.append(Alert(
                key=f"night_visitor:{e['id']}", rule="night_visitor", severity="high",
                title="Someone at the door at night",
                message=(f"At {t:%H:%M} a person was seen at the {cfg.camera_name}. "
                         f"{_detail(v)}").strip(),
                event_id=e["id"], at_ms=e["start_ms"]))
    # R4: long daytime quiet after being seen. A doorbell can't see a fall inside the
    # house, but the routine stopping (no door activity for hours) is the earliest
    # signal it can give.
    day_end = _at(now, cfg.night_start)
    if today_start <= now < day_end:
        people = [e for e in evs
                  if today_start <= _local(e["start_ms"], cfg.tz) <= now
                  and (e.get("kw_label") in cfg.activity_labels
                       or _vision(e).get("person_visible"))]
        if people:
            last = people[-1]
            quiet = (now_ms - last["start_ms"]) / 60000
            if quiet >= cfg.quiet_hours * 60:
                t = _local(last["start_ms"], cfg.tz)
                alerts.append(Alert(
                    key=f"long_quiet:{last['id']}", rule="long_quiet", severity="high",
                    title=f"{cfg.parent_name} hasn't been seen for {fmt_duration(quiet)}",
                    message=(f"{cfg.parent_name} was last seen at the {cfg.camera_name} at "
                             f"{t:%H:%M}. Nobody has been there since, which is longer than "
                             f"the {cfg.quiet_hours} h you set for the daytime. "
                             f"Maybe give her a call?"),
                    event_id=last["id"], at_ms=now_ms))
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
    ap.add_argument("--deadline", help="morning activity deadline (default: saved settings)")
    ap.add_argument("--package-minutes", type=int, help="default: saved settings")
    ap.add_argument("--notify", action="store_true",
                    help="send new alerts to Telegram (each alert only once)")
    args = ap.parse_args()

    from .settings import load_config
    cfg = load_config()
    if args.deadline:
        cfg.activity_deadline = args.deadline
    if args.package_minutes:
        cfg.package_minutes = args.package_minutes
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
