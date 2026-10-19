"""Thin client for the Ring Partner API (https://api.amazonvision.com).

Ring has no official SDK, so this module is the only place that talks HTTP.

Three modes:
  live    - call the real API with RING_ACCESS_TOKEN (Playground token, 30 min)
  record  - call the real API AND save every JSON/image response to fixtures/
  replay  - never touch the network; serve responses from fixtures/
            (lets judges run KinWatch without a Ring token)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

BASE_URL = os.environ.get("RING_API_BASE", "https://api.amazonvision.com")
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "playground"
# Undocumented in the public docs, discovered from Ring's 400 responses:
# body needs "timestamp" (epoch ms) and "type", whose valid values are
# "at_timestamp" and "latest_in_range".
IMAGE_TYPE_CANDIDATES = ["at_timestamp", "latest_in_range"]


class RingAPIError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, body: str):
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:300]}")
        self.status = status


@dataclass
class Device:
    id: str
    name: str
    image_url: str | None


@dataclass
class HistoryEvent:
    id: str
    device_id: str
    event_type: str          # e.g. "on_demand" in the Playground; "motion"/"ding" on real devices
    start_ms: int
    end_ms: int | None
    cv_labels: list[str]     # Ring's own CV detections, often empty in the Playground
    raw: dict[str, Any]


def _ext_for(ctype: str | None) -> str:
    ctype = (ctype or "").lower()
    if "png" in ctype:
        return ".png"
    if "mp4" in ctype or "video" in ctype:
        return ".mp4"
    return ".jpg"


def _fixture_name(method: str, path: str) -> str:
    """Legacy (day-1) fixture name: the full path, e.g. GET__v1_devices."""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/"))
    return f"{method.upper()}__{clean}"


def _short(seg: str) -> str:
    """Ring ids are ~120 chars; keep fixture paths well under Windows' 260 limit."""
    if len(seg) <= 32:
        return seg
    return f"{seg.split('.')[2] if seg.count('.') >= 3 else 'id'}-{hashlib.sha1(seg.encode()).hexdigest()[:8]}"


def fixture_key(method: str, path: str, json_body: Any = None) -> str:
    """Short, stable fixture name. POST bodies are part of the key, so each
    event's snapshot (different timestamp) gets its own recorded file."""
    parts = [_short(p) for p in path.strip("/").split("/")]
    name = f"{method.upper()}__" + "_".join(re.sub(r"[^A-Za-z0-9._-]+", "_", p) for p in parts)
    if json_body is not None:
        digest = hashlib.sha1(json.dumps(json_body, sort_keys=True).encode()).hexdigest()[:10]
        name += f"__{digest}"
    return name


class RingClient:
    def __init__(
        self,
        token: str | None = None,
        mode: str | None = None,
        fixture_dir: Path | str | None = None,
        max_retries: int = 4,
    ):
        self.mode = (mode or os.environ.get("KINWATCH_MODE", "live")).lower()
        if self.mode not in {"live", "record", "replay"}:
            raise ValueError(f"unknown mode {self.mode!r}")
        self.token = token or os.environ.get("RING_ACCESS_TOKEN")
        if self.mode != "replay" and not self.token:
            raise SystemExit(
                "RING_ACCESS_TOKEN is not set. Generate one in the Ring Developers "
                "Playground, or run with KINWATCH_MODE=replay."
            )
        self.fixture_dir = Path(fixture_dir or DEFAULT_FIXTURE_DIR)
        self.max_retries = max_retries
        self.session = requests.Session()
        self._image_type: str | None = os.environ.get("RING_IMAGE_TYPE")

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, *, json_body: Any = None,
                 params: dict | None = None, expect_binary: bool = False):
        name = fixture_key(method, path, json_body)
        if self.mode == "replay":
            try:
                return self._load_fixture(name, expect_binary)
            except FileNotFoundError:
                if json_body is not None:
                    raise           # never reuse another event's media
                return self._load_fixture(_fixture_name(method, path), expect_binary)

        url = BASE_URL + path
        headers = {"Authorization": f"Bearer {self.token}"}
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            resp = self.session.request(method, url, headers=headers, json=json_body,
                                        params=params, timeout=30)
            if resp.status_code == 429 and attempt < self.max_retries:
                # Ring docs: honour Retry-After, else exponential backoff from 1s
                wait = float(resp.headers.get("Retry-After", delay))
                time.sleep(wait)
                delay *= 2
                continue
            break
        if resp.status_code == 401:
            raise RingAPIError(401, method, path,
                               "token rejected or expired (Playground tokens last 30 min)")
        if not resp.ok:
            raise RingAPIError(resp.status_code, method, path, resp.text)

        if expect_binary:
            data, ctype = resp.content, resp.headers.get("Content-Type", "image/jpeg")
            if self.mode == "record":
                self._save_fixture(name, data, ctype)
            return data, ctype
        data = resp.json() if resp.content else {}
        if self.mode == "record":
            self._save_fixture(name, data)
        return data

    # -------------------------------------------------------------- fixtures
    def _save_fixture(self, name: str, data: Any, ctype: str | None = None) -> None:
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (bytes, bytearray)):
            ext = _ext_for(ctype)
            (self.fixture_dir / f"{name}{ext}").write_bytes(data)
        else:
            (self.fixture_dir / f"{name}.json").write_text(json.dumps(data, indent=2))

    def _load_fixture(self, name: str, expect_binary: bool):
        if expect_binary:
            for ext, ctype in ((".jpg", "image/jpeg"), (".png", "image/png"),
                               (".mp4", "video/mp4")):
                p = self.fixture_dir / f"{name}{ext}"
                if p.exists():
                    return p.read_bytes(), ctype
            raise FileNotFoundError(f"no media fixture for {name}")
        p = self.fixture_dir / f"{name}.json"
        if not p.exists():
            raise FileNotFoundError(f"no fixture {p.name} (run once with KINWATCH_MODE=record)")
        return json.loads(p.read_text())

    # ------------------------------------------------------------- endpoints
    def list_devices(self) -> list[Device]:
        body = self._request("GET", "/v1/devices")
        return [
            Device(
                id=d["id"],
                name=d.get("attributes", {}).get("name", "Ring device"),
                image_url=d.get("attributes", {}).get("image_url"),
            )
            for d in body.get("data", [])
            if d.get("type") == "devices"
        ]

    def history_events(self, device_id: str) -> list[HistoryEvent]:
        body = self._request("GET", f"/v1/history/devices/{device_id}/events")
        return [parse_history_event(e) for e in body.get("data", [])
                if e.get("type") == "history-events"]

    def download_image(self, device_id: str, timestamp_ms: int,
                       components: list | None = None):
        """Snapshot at a moment in time. Returns (bytes, content_type).

        Ring rejects an empty body with 403 "missing required timestamp fields",
        so we always send `timestamp` in epoch milliseconds (must be <= now).
        """
        ts = min(int(timestamp_ms), int(time.time() * 1000))
        path = f"/v1/devices/{device_id}/media/image/download"
        # Ring also answers 400 "type is required" but does not document the values,
        # so try likely ones once and remember the first that works.
        candidates = [self._image_type] if self._image_type else IMAGE_TYPE_CANDIDATES
        last_exc: Exception | None = None
        for t in candidates:
            body: dict[str, Any] = {"timestamp": ts, "type": t}
            if components is not None:
                body["components"] = components
            try:
                result = self._request("POST", path, json_body=body, expect_binary=True)
            except RingAPIError as exc:
                last_exc = exc
                if exc.status == 400 and "type" in str(exc):
                    if "is required" not in str(exc):
                        # a different 400 often names the allowed values: show it
                        print(f"      image type {t!r} rejected: {str(exc)[-200:]}")
                    continue          # wrong type value, try the next one
                raise
            if self._image_type != t:
                print(f"      (Ring image type that works: {t!r})")
            self._image_type = t
            return result
        raise last_exc or RingAPIError(400, "POST", path, "no image type accepted")

    def download_clip(self, device_id: str, timestamp_ms: int, duration_ms: int = 3000):
        """Short MP4 clip (documented: timestamp + duration, both ms, duration <= 900000)."""
        ts = min(int(timestamp_ms), int(time.time() * 1000))
        body = {"timestamp": ts, "duration": min(int(duration_ms), 900_000)}
        return self._request("POST", f"/v1/devices/{device_id}/media/video/download",
                             json_body=body, expect_binary=True)

    def device_status(self, device_id: str) -> dict:
        return self._request("GET", f"/v1/devices/{device_id}/status")

    def capabilities(self, device_id: str) -> dict:
        """Raw capabilities attributes (snapshot support, audio actions, video...)."""
        body = self._request("GET", f"/v1/devices/{device_id}/capabilities")
        return body.get("data", {}).get("attributes", {})

    def supports_snapshot(self, device_id: str) -> bool:
        img = self.capabilities(device_id).get("image_enhancements") or {}
        return "snapshot" in (img.get("configurations") or [])

    def supports_chime_audio(self, device_id: str) -> bool:
        audio = self.capabilities(device_id).get("audio") or {}
        return bool(audio.get("supported_actions"))


def parse_history_event(e: dict) -> HistoryEvent:
    attrs = e.get("attributes", {})
    rel = e.get("relationships", {})
    src = rel.get("source", {}).get("data", {}) or {}
    detections = rel.get("cv_detections", {}).get("data", []) or []
    labels = []
    for d in detections:
        label = (d.get("attributes") or {}).get("label") or d.get("type") or d.get("id")
        if label:
            labels.append(str(label))
    return HistoryEvent(
        id=e["id"],
        device_id=src.get("id", ""),
        event_type=attrs.get("event_type", "unknown"),
        start_ms=int(attrs.get("start", 0)),
        end_ms=int(attrs["end"]) if attrs.get("end") is not None else None,
        cv_labels=labels,
        raw=e,
    )
