import json
from datetime import datetime

import pytest

from kinwatch import dashboard, settings
from kinwatch.dashboard import create_app
from kinwatch.ring_client import parse_history_event
from kinwatch.rules import IST
from kinwatch.store import EventStore


def ms(hhmm):
    h, m = map(int, hhmm.split(":"))
    now = datetime.now(IST)
    return int(now.replace(hour=h, minute=m, second=0, microsecond=0).timestamp() * 1000)


def add(store, eid, hhmm, label, desc, media=None):
    store.add_if_new(parse_history_event({
        "type": "history-events", "id": eid,
        "attributes": {"start": ms(hhmm), "end": ms(hhmm) + 30000, "event_type": "on_demand"},
        "relationships": {"source": {"data": {"id": "dev"}}, "cv_detections": {"data": []}}}),
        "Front Door")
    store.annotate(eid, kw_label=label, description=desc, snapshot_path=media,
                   vision={"label": label, "description": desc,
                           "person_visible": label == "person",
                           "package_visible": label == "package", "concern": False})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "s.json")
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "pkg1.jpg").write_bytes(b"\xff\xd8img")
    store = EventStore(tmp_path / "k.db")
    add(store, "e1", "07:40", "person", "An older woman collects the newspaper.")
    add(store, "e2", "08:00", "package", "A cardboard package on the front steps.",
        "snapshots\\pkg1.jpg")
    add(store, "e3", "08:20", "animal", "Two birds at a feeder.")
    return create_app(str(tmp_path / "k.db")).test_client()


def test_page_and_normal_status(client):
    assert b"KinWatch" in client.get("/").data
    d = client.get("/api/today?at=08:30").get_json()
    assert d["simulated"] and d["status"]["level"] == "ok"
    assert "07:40" in d["status"]["detail"] and "1 camera event ignored" in d["status"]["detail"]
    assert [e["label"] for e in d["events"]] == ["animal", "package", "person"]   # newest first
    assert d["events"][2]["ignored"] is False and d["events"][0]["ignored"] is True
    assert d["events"][1]["image"] == "/media/pkg1.jpg"


def test_package_alert_status_later(client):
    d = client.get("/api/today?at=09:15").get_json()
    assert d["status"]["level"] == "medium"
    assert d["alerts"][0]["rule"] == "package_waiting" and d["alerts"][0]["sent"] is False
    assert any(e["flagged"] for e in d["events"])


def test_events_after_simulated_time_hidden(client):
    d = client.get("/api/today?at=07:50").get_json()
    assert [e["id"] for e in d["events"]] == ["e1"]


def test_bad_time_rejected(client):
    assert client.get("/api/today?at=25:99").status_code == 400


def test_media_served_and_traversal_blocked(client):
    assert client.get("/media/pkg1.jpg").data == b"\xff\xd8img"
    assert client.get("/media/..%2Fk.db").status_code == 404
    assert client.get("/media/k.db").status_code == 404


def test_settings_roundtrip_and_validation(client):
    r = client.post("/api/settings", json={"parent_name": "Ajji", "activity_deadline": "09:00",
                                           "package_minutes": 30})
    assert r.status_code == 200 and r.get_json()["settings"]["parent_name"] == "Ajji"
    d = client.get("/api/today?at=08:40").get_json()
    assert d["alerts"][0]["rule"] == "package_waiting"      # 30-min rule now applies
    bad = client.post("/api/settings", json={"activity_deadline": "nine"})
    assert bad.status_code == 400 and "09:30" in bad.get_json()["error"]


def test_ask_endpoint(client, monkeypatch):
    from kinwatch import agent
    monkeypatch.setattr(agent, "ask", lambda q: ("Amma was seen at 07:40.", "mcp"))
    r = client.post("/api/ask", json={"question": "How is Amma?"})
    body = r.get_json()
    assert r.status_code == 200 and body["answer"] == "Amma was seen at 07:40." and body["via"] == "mcp"
    assert client.post("/api/ask", json={"question": " "}).status_code == 400

    def boom(q):
        raise RuntimeError("AccessDeniedException: Your account is currently being verified")
    monkeypatch.setattr(agent, "ask", boom)
    r = client.post("/api/ask", json={"question": "How is Amma?"})
    assert r.status_code == 502 and "verifying" in r.get_json()["error"]
