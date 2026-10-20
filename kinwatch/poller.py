"""KinWatch poller: pulls Ring devices + event history, stores new events,
grabs a snapshot (or a short clip as fallback) for each new event.

Usage:
  python -m kinwatch.poller --once              # one pass, then exit
  python -m kinwatch.poller --interval 15       # keep polling every 15 s
  python -m kinwatch.poller --retry-media       # re-try snapshots for stored events
  KINWATCH_MODE=record python -m kinwatch.poller --once   # also save fixtures
  KINWATCH_MODE=replay python -m kinwatch.poller --once   # no token needed
  python -m kinwatch.poller --label             # Bedrock-label stored pictures
  KINWATCH_VISION=off                            # skip the Bedrock step
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import os
from dataclasses import asdict

from .frames import extract_frame
from .notify import Notifier, TelegramError
from .ring_client import RingAPIError, RingClient, _ext_for
from .rules import RoutineConfig, evaluate
from .store import EventStore
from .vision import Vision

IST = timezone(timedelta(hours=5, minutes=30))
MEDIA_DIR = Path("snapshots")


def fmt_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=IST).strftime("%d %b %H:%M:%S IST")


def moment_of(start_ms: int, end_ms: int | None) -> int:
    """Middle of the event: the frame most likely to show what triggered it."""
    return start_ms + (end_ms - start_ms) // 2 if end_ms else start_ms + 2000


def fetch_media(client: RingClient, store: EventStore, event_id: str, device_id: str,
                start_ms: int, end_ms: int | None) -> Path | None:
    ts = moment_of(start_ms, end_ms)
    whole = (end_ms - start_ms + 2000) if end_ms else 10_000
    MEDIA_DIR.mkdir(exist_ok=True)
    attempts = (
        ("snapshot", lambda: client.download_image(device_id, ts)),
        ("clip", lambda: client.download_clip(device_id, ts, 3000)),
        # Ring can answer 416 "no media in time range" for a mid-event window,
        # so fall back to the whole event from its start.
        ("full clip", lambda: client.download_clip(device_id, start_ms, whole)),
    )
    for kind, call in attempts:
        try:
            data, ctype = call()
        except (RingAPIError, FileNotFoundError) as exc:
            print(f"      {kind} unavailable: {str(exc)[:220]}")
            continue
        path = MEDIA_DIR / f"{event_id[-12:]}{_ext_for(ctype)}"
        path.write_bytes(data)
        print(f"      {kind} saved -> {path} ({len(data)} bytes, {ctype})")
        picture = path
        if path.suffix == ".mp4":
            frame = extract_frame(path)
            if frame:
                picture = frame
                print(f"      frame extracted -> {frame}")
        store.annotate(event_id, snapshot_path=str(picture))
        return picture if picture.suffix != ".mp4" else None
    # Nothing recorded for this event (Ring answers 416 MEDIA_NOT_FOUND): mark it
    # with an empty path so --retry-media doesn't keep asking.
    if client.mode != "replay":
        store.annotate(event_id, snapshot_path="")
        print("      no media recorded for this event; marked and skipped")
    return None


class Labeller:
    """Wraps the Bedrock vision step so a missing key never crashes the poller."""

    def __init__(self):
        self.enabled = os.environ.get("KINWATCH_VISION", "live").lower() != "off"
        self.vision = Vision() if self.enabled else None

    def label(self, store: EventStore, event_id: str, picture: Path | str | None) -> None:
        if not (self.enabled and picture):
            return
        try:
            result = self.vision.describe(picture)
        except Exception as exc:  # no AWS key, no model access, network...
            print(f"      vision unavailable: {type(exc).__name__}: {str(exc)[:160]}")
            if self.vision.backend == "rekognition" or "DetectLabels" in str(exc):
                print("      (check AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are your real keys,"
                      " or set KINWATCH_VISION=off to skip)")
            else:
                print("      (set AWS_BEARER_TOKEN_BEDROCK, or KINWATCH_VISION=off to skip)")
            self.enabled = False
            return
        if result is None:
            print("      vision: no cached label (replay mode)")
            return
        data = asdict(result)
        store.annotate(event_id, kw_label=result.label, description=result.description,
                       vision=data)
        flag = "  !concern" if result.concern else ""
        src = "cache" if result.cached else result.model
        print(f"      vision [{result.label}]{flag}: {result.description}  ({src})")


def check_rules(store: EventStore, now_ms: int | None = None,
                cfg: RoutineConfig | None = None, notifier: Notifier | None = None) -> list:
    now_ms = now_ms or int(time.time() * 1000)
    if cfg is None:
        from .settings import load_config
        cfg = load_config()
    events = [dict(r) for r in store.recent(500)]
    fresh = [a for a in evaluate(events, now_ms, cfg) if store.record_alert(a)]
    for a in fresh:
        print(f"  >> ALERT [{a.severity.upper()}] {a.title}: {a.message}")
        if notifier and notifier.enabled:
            row = store.get(a.event_id) if a.event_id else None
            photo = row["snapshot_path"] if row and row["snapshot_path"] else None
            try:
                notifier.send_alert(a, photo=photo)
                print("     sent to Telegram" + (" with snapshot" if photo else ""))
            except (TelegramError, OSError) as exc:
                print(f"     Telegram failed: {exc}")
    return fresh


def poll_once(client: RingClient, store: EventStore, grab_snapshots: bool = True,
              labeller: "Labeller | None" = None) -> int:
    new_count = 0
    for dev in client.list_devices():
        events = client.history_events(dev.id)
        for ev in sorted(events, key=lambda e: e.start_ms):
            if not store.add_if_new(ev, dev.name):
                continue
            new_count += 1
            dur = f"{(ev.end_ms - ev.start_ms) / 1000:.0f}s" if ev.end_ms else "ongoing"
            labels = ", ".join(ev.cv_labels) or "no Ring CV labels"
            print(f"[NEW] {fmt_time(ev.start_ms)}  {dev.name}  type={ev.event_type}"
                  f"  ({dur}, {labels})")
            if grab_snapshots:
                picture = fetch_media(client, store, ev.id, dev.id, ev.start_ms, ev.end_ms)
                if labeller:
                    labeller.label(store, ev.id, picture)
    return new_count


def retry_media(client: RingClient, store: EventStore, labeller: "Labeller | None" = None) -> None:
    rows = store.without_media()
    print(f"retrying media for {len(rows)} stored event(s)")
    for r in rows:
        print(f"[RETRY] {fmt_time(r['start_ms'])}  {r['device_name']}  type={r['event_type']}")
        picture = fetch_media(client, store, r["id"], r["device_id"], r["start_ms"], r["end_ms"])
        if labeller:
            labeller.label(store, r["id"], picture)


def refetch_media(client: RingClient, store: EventStore) -> None:
    """Re-download media for every stored event (use with KINWATCH_MODE=record to
    build per-event replay fixtures for judges)."""
    rows = [r for r in store.recent(500) if r["snapshot_path"] != ""]
    print(f"re-fetching media for {len(rows)} event(s)")
    for r in sorted(rows, key=lambda r: r["start_ms"]):
        print(f"[REFETCH] {fmt_time(r['start_ms'])}  {r['device_name']}")
        fetch_media(client, store, r["id"], r["device_id"], r["start_ms"], r["end_ms"])


def label_stored(store: EventStore, labeller: "Labeller") -> None:
    rows = store.unlabelled_pictures()
    backend = labeller.vision.backend if labeller.vision else "off"
    print(f"labelling {len(rows)} stored picture(s) (vision backend: {backend})")
    for r in rows:
        print(f"[LABEL] {fmt_time(r['start_ms'])}  {r['snapshot_path']}")
        labeller.label(store, r["id"], r["snapshot_path"])


def main() -> None:
    ap = argparse.ArgumentParser(description="KinWatch Ring poller")
    ap.add_argument("--once", action="store_true", help="poll once and exit")
    ap.add_argument("--interval", type=float, default=15, help="seconds between polls")
    ap.add_argument("--db", default="kinwatch.db")
    ap.add_argument("--no-snapshots", action="store_true")
    ap.add_argument("--retry-media", action="store_true",
                    help="fetch snapshots for stored events that have none, then exit")
    ap.add_argument("--refetch-media", action="store_true",
                    help="download media again for all stored events (to record fixtures)")
    ap.add_argument("--label", action="store_true",
                    help="run Bedrock vision on stored pictures without a label, then exit")
    args = ap.parse_args()

    store = EventStore(args.db)
    labeller = Labeller()
    notifier = Notifier()
    if args.label:
        label_stored(store, labeller)
        check_rules(store, notifier=notifier)
        return
    client = RingClient()
    print(f"KinWatch poller started (mode={client.mode}, vision={'on' if labeller.enabled else 'off'},"
          f" telegram={'on' if notifier.enabled else 'off'}, db={args.db})")
    if args.retry_media:
        retry_media(client, store, labeller)
        return
    if args.refetch_media:
        refetch_media(client, store)
        return
    while True:
        try:
            n = poll_once(client, store, grab_snapshots=not args.no_snapshots, labeller=labeller)
            print(f"poll done: {n} new event(s)")
            check_rules(store, notifier=notifier)
        except RingAPIError as exc:
            print(f"Ring API error: {exc}")
            if exc.status == 401:
                print("Generate a fresh Playground token and set RING_ACCESS_TOKEN again.")
                break
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
