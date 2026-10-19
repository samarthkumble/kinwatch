from kinwatch.poller import poll_once
from kinwatch.ring_client import RingClient, parse_history_event
from kinwatch.store import EventStore


def replay_client():
    return RingClient(mode="replay")


def test_list_devices_from_playground_fixture():
    devices = replay_client().list_devices()
    assert len(devices) == 1
    assert devices[0].name == "Playground Device"
    assert devices[0].id.startswith("ava1.ring.device.")


def test_history_events_parse_playground_shape():
    client = replay_client()
    dev = client.list_devices()[0]
    events = client.history_events(dev.id)
    # record mode refreshes this fixture, so don't pin an exact count
    assert len(events) >= 1
    assert all(e.event_type == "on_demand" for e in events)
    assert all(e.cv_labels == [] for e in events)       # Playground gives no CV labels
    assert all(e.device_id == dev.id for e in events)
    assert all(e.end_ms > e.start_ms for e in events)


def test_parse_handles_missing_end_and_detections():
    ev = parse_history_event({
        "type": "history-events", "id": "x",
        "attributes": {"start": 1000, "event_type": "motion"},
        "relationships": {"source": {"data": {"id": "dev1"}},
                          "cv_detections": {"data": [{"attributes": {"label": "human"}}]}},
    })
    assert ev.end_ms is None and ev.cv_labels == ["human"]


def test_poll_once_dedupes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client, store = replay_client(), EventStore(tmp_path / "t.db")
    n = len(client.history_events(client.list_devices()[0].id))
    assert poll_once(client, store, grab_snapshots=False) == n
    assert poll_once(client, store, grab_snapshots=False) == 0   # nothing new 2nd time
    assert len(store.recent()) == n


def test_playground_capabilities():
    client = replay_client()
    dev = client.list_devices()[0]
    assert client.supports_snapshot(dev.id) is True
    assert client.supports_chime_audio(dev.id) is False   # audio.supported_actions is null


def test_image_download_sends_timestamp(monkeypatch):
    sent = {}

    class FakeResp:
        status_code, ok, content = 200, True, b"\xff\xd8jpeg"
        headers = {"Content-Type": "image/jpeg"}
        text = ""

    def fake_request(self, method, url, headers=None, json=None, params=None, timeout=None):
        sent.update(method=method, url=url, body=json)
        return FakeResp()

    import requests
    monkeypatch.setattr(requests.Session, "request", fake_request)
    client = RingClient(token="t", mode="live")
    data, ctype = client.download_image("dev1", 1792391915000)
    assert sent["method"] == "POST" and sent["url"].endswith("/v1/devices/dev1/media/image/download")
    assert sent["body"] == {"timestamp": 1792391915000, "type": "at_timestamp"}
    assert data.startswith(b"\xff\xd8") and ctype == "image/jpeg"


def test_image_type_probe_skips_rejected_values(monkeypatch):
    import requests
    tried = []

    class Resp:
        def __init__(self, ok):
            self.ok, self.status_code = ok, 200 if ok else 400
            self.content = b"\x89PNG" if ok else b"{}"
            self.headers = {"Content-Type": "image/png"}
            self.text = "" if ok else '{"detail":"type is required","pointer":"type"}'

    def fake_request(self, method, url, headers=None, json=None, params=None, timeout=None):
        tried.append(json["type"])
        return Resp(json["type"] == "latest_in_range")

    monkeypatch.setattr(requests.Session, "request", fake_request)
    client = RingClient(token="t", mode="live")
    client.download_image("dev1", 1000)
    assert tried == ["at_timestamp", "latest_in_range"]
    tried.clear()
    client.download_image("dev1", 2000)      # remembers the working type
    assert tried == ["latest_in_range"]
