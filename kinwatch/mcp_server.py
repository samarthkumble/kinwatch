"""KinWatch MCP server: lets any MCP-capable assistant ask about the front door.

  python -m kinwatch.mcp_server                 # http://127.0.0.1:8765/mcp
  npx @modelcontextprotocol/inspector           # connect to the URL above to try it

Transport: Streamable HTTP, MCP protocol 2025-11-25 (mcp Python SDK 1.x).
All tools are read-only views of the same database the poller fills.
"""
from __future__ import annotations

import os
import re
import time

from mcp.server.fastmcp import FastMCP

from .dashboard import build_today
from .settings import config_dict, load_config
from .store import EventStore

DB_PATH = os.environ.get("KINWATCH_DB", "kinwatch.db")
HOST = os.environ.get("KINWATCH_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("KINWATCH_MCP_PORT", "8765"))

mcp = FastMCP(
    "KinWatch",
    instructions=(
        "KinWatch watches the Ring front-door camera of an elderly parent who lives "
        "alone. Use these tools to answer a family member's questions about how the "
        "parent's day is going. Times are in IST. Never guess: if a tool says nothing "
        "was seen, say so."),
    host=HOST, port=PORT,
)


def _today(at: str | None = None) -> dict:
    if at and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise ValueError("Use a 24-hour time like 10:05.")
    from .rules import demo_now
    now_ms = demo_now(at) if at else int(time.time() * 1000)
    return build_today(EventStore(DB_PATH), now_ms, simulated=bool(at))


@mcp.tool()
def get_today_status(at: str | None = None) -> dict:
    """How is the parent's day going? Returns a one-line status, the reason, and
    today's counts (camera events, times someone was seen, deliveries, noise).
    `at` (optional, "HH:MM") evaluates the day as if it were that time."""
    d = _today(at)
    return {"time": d["now"], "date": d["date"], "status": d["status"],
            "summary": d["summary"], "open_alerts": len(d["alerts"])}


@mcp.tool()
def list_events(label: str | None = None, limit: int = 20, at: str | None = None) -> list[dict]:
    """Today's front-door camera events, newest first. Optional `label` filter:
    person, package, vehicle, animal or nothing. Each event has the time, what
    KinWatch saw, a one-line description, and whether it was ignored as noise."""
    events = _today(at)["events"]
    if label:
        events = [e for e in events if e["label"] == label.lower()]
    return [{k: e[k] for k in ("time", "label", "description", "ignored", "flagged")}
            for e in events[: max(1, min(limit, 100))]]


@mcp.tool()
def get_alerts(at: str | None = None) -> list[dict]:
    """Alerts that need the family's attention right now (e.g. no sign of the
    parent by the morning deadline, a delivery left outside too long, a person
    at the door at night), and whether each was already sent to their phone."""
    return [{k: a[k] for k in ("severity", "title", "message", "sent")}
            for a in _today(at)["alerts"]]


@mcp.tool()
def get_routine() -> dict:
    """The parent's expected routine that alerts are based on: name, the time
    they're usually up by, how long a package may wait, and night hours."""
    return config_dict(load_config())


def main() -> None:
    print(f"KinWatch MCP server: http://{HOST}:{PORT}/mcp  (Streamable HTTP, Ctrl+C to stop)")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
