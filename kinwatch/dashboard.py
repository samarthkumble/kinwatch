"""Caregiver dashboard: is Amma okay today?

  python -m kinwatch.dashboard            # then open http://127.0.0.1:8050
  python -m kinwatch.dashboard --port 9000

Reads the same SQLite database, rules and settings as the poller, so it shows
exactly what KinWatch knows. Read-only except for the routine settings form.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from .rules import IST, _at, _local, demo_now, evaluate, summarize
from .settings import config_dict, load_config, save_config
from .store import EventStore

STATIC_DIR = Path(__file__).resolve().parent / "static"
MEDIA_DIR = Path("snapshots")
NOISE = {"animal", "nothing"}
LABEL_TEXT = {"person": "Person", "package": "Package", "vehicle": "Vehicle",
              "animal": "Animal", "nothing": "Nothing", None: "Not labelled yet"}


def _media_name(path: str | None) -> str | None:
    if not path:
        return None
    name = re.split(r"[\\/]", path)[-1]
    return name if name.lower().endswith((".jpg", ".jpeg", ".png")) else None


def _vision(row: dict) -> dict:
    try:
        return json.loads(row.get("vision") or "{}")
    except ValueError:
        return {}


def build_today(store: EventStore, now_ms: int, simulated: bool = False) -> dict:
    cfg = load_config()
    rows = [dict(r) for r in store.recent(500)]
    now = _local(now_ms, IST)
    today = [r for r in rows if _local(r["start_ms"], IST).date() == now.date()
             and r["start_ms"] <= now_ms]
    alerts = evaluate(rows, now_ms, cfg)
    sent_keys = {r["key"] for r in store.alerts(500)}
    alert_events = {a.event_id for a in alerts if a.event_id}

    events = []
    for r in sorted(today, key=lambda r: r["start_ms"], reverse=True):
        label = r.get("kw_label")
        media = _media_name(r.get("snapshot_path"))
        events.append({
            "id": r["id"],
            "time": _local(r["start_ms"], IST).strftime("%H:%M"),
            "label": label,
            "label_text": LABEL_TEXT.get(label, label or "Not labelled yet"),
            "description": r.get("description") or "",
            "ring_type": r.get("event_type"),
            "image": f"/media/{media}" if media else None,
            "ignored": label in NOISE,
            "flagged": r["id"] in alert_events,
            "no_media": r.get("snapshot_path") == "",
        })

    people = [r for r in today if r.get("kw_label") == "person" or _vision(r).get("person_visible")]
    last_seen = _local(max(r["start_ms"] for r in people), IST).strftime("%H:%M") if people else None
    summary = summarize(rows, now_ms, cfg)
    summary.update({"people_seen": len(people), "last_seen": last_seen,
                    "packages": sum(1 for e in events if e["label"] == "package"),
                    "alerts": len(alerts)})

    order = {"high": 0, "medium": 1, "info": 2}
    alerts.sort(key=lambda a: order.get(a.severity, 3))
    if alerts:
        top = alerts[0]
        status = {"level": top.severity, "title": top.title, "detail": top.message}
    else:
        name = cfg.parent_name
        if last_seen:
            detail = f"{name} was last seen at the front door at {last_seen}."
        elif now < _at(now, cfg.activity_deadline):
            detail = (f"Nobody has been at the front door yet. That's expected before "
                      f"{cfg.activity_deadline}.")
        else:
            detail = "Nothing needs your attention right now."
        noise = summary.get("ignored_as_noise", 0)
        if noise:
            detail += f" {noise} camera event{'s' if noise != 1 else ''} ignored as noise."
        status = {"level": "ok", "title": f"{name}'s day looks normal", "detail": detail}

    return {
        "now": now.strftime("%H:%M"),
        "date": now.strftime("%A %d %B").replace(" 0", " "),
        "simulated": simulated,
        "status": status,
        "summary": summary,
        "events": events,
        "alerts": [{"key": a.key, "rule": a.rule, "severity": a.severity, "title": a.title,
                    "message": a.message, "sent": a.key in sent_keys} for a in alerts],
        "settings": config_dict(cfg),
    }


def create_app(db_path: str = "kinwatch.db") -> Flask:
    app = Flask(__name__, static_folder=None)

    def store() -> EventStore:
        return EventStore(db_path)

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    @app.get("/media/<name>")
    def media(name):
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(jpg|jpeg|png)", name):
            abort(404)
        return send_from_directory(MEDIA_DIR.resolve(), name)

    @app.get("/api/today")
    def today():
        at = request.args.get("at")
        if at and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
            return jsonify({"error": "Use a time like 10:05."}), 400
        now_ms = demo_now(at) if at else int(time.time() * 1000)
        return jsonify(build_today(store(), now_ms, simulated=bool(at)))

    @app.post("/api/ask")
    def ask():
        q = str((request.get_json(force=True) or {}).get("question", "")).strip()[:300]
        if not q:
            return jsonify({"error": "Type a question first."}), 400
        try:
            from .agent import ask as agent_ask
            answer, path = agent_ask(q)
        except Exception as exc:   # Bedrock key missing, account not verified, ...
            msg = str(exc)
            if "AccessDenied" in msg or "verif" in msg:
                hint = "Bedrock refused the request. If your AWS account is new, it may still be verifying."
            elif "credential" in msg.lower() or "token" in msg.lower():
                hint = "No Bedrock API key found. Set AWS_BEARER_TOKEN_BEDROCK before starting the dashboard."
            else:
                hint = "KinWatch couldn't answer right now."
            return jsonify({"error": f"{hint} ({type(exc).__name__})"}), 502
        return jsonify({"answer": answer, "via": path})

    @app.post("/api/settings")
    def settings():
        try:
            cfg = save_config(request.get_json(force=True) or {})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"settings": config_dict(cfg)})

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="KinWatch caregiver dashboard")
    ap.add_argument("--db", default="kinwatch.db")
    ap.add_argument("--port", type=int, default=8050)
    args = ap.parse_args()
    print(f"KinWatch dashboard: http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    create_app(args.db).run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
