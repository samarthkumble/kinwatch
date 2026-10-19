import json

import pytest

from kinwatch.poller import Labeller, check_rules
from kinwatch.store import EventStore
from kinwatch.vision import Vision, parse_model_json


class FakeBedrock:
    def __init__(self, reply: str):
        self.reply, self.calls = reply, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": self.reply}]}}}


PACKAGE_REPLY = ('```json\n{"label": "package", "description": "A cardboard package on '
                 'the snowy front steps.", "person_visible": false, '
                 '"package_visible": true, "concern": false}\n```')


def test_parse_handles_fenced_json_and_bad_labels():
    d = parse_model_json(PACKAGE_REPLY)
    assert d["label"] == "package" and d["package_visible"] is True
    assert parse_model_json('{"label": "dragon"}')["label"] == "nothing"
    with pytest.raises(ValueError):
        parse_model_json("no json here")


def test_describe_calls_bedrock_once_then_uses_cache(tmp_path):
    img = tmp_path / "snap.jpg"
    img.write_bytes(b"\xff\xd8fake-jpeg")
    fake = FakeBedrock(PACKAGE_REPLY)
    v = Vision(mode="live", cache_dir=tmp_path / "cache", client=fake)

    r1 = v.describe(img)
    assert r1.label == "package" and not r1.cached
    msg = fake.calls[0]["messages"][0]["content"]
    assert msg[0]["image"]["format"] == "jpeg"
    assert msg[0]["image"]["source"]["bytes"] == b"\xff\xd8fake-jpeg"

    r2 = v.describe(img)                       # second time: from cache
    assert r2.cached and len(fake.calls) == 1

    replay = Vision(mode="replay", cache_dir=tmp_path / "cache")
    assert replay.describe(img).label == "package"


def test_replay_without_cache_returns_none(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"new")
    assert Vision(mode="replay", cache_dir=tmp_path / "c").describe(img) is None


def test_labeller_stores_label_and_alerts_once(tmp_path, monkeypatch):
    from kinwatch.ring_client import parse_history_event
    store = EventStore(tmp_path / "k.db")
    ev = parse_history_event({
        "type": "history-events", "id": "p1",
        "attributes": {"start": 1792372800000, "end": 1792372830000,  # 19 Oct 06:50 IST
                       "event_type": "on_demand"},
        "relationships": {"source": {"data": {"id": "dev"}}, "cv_detections": {"data": []}}})
    store.add_if_new(ev, "Front Door")
    img = tmp_path / "p1.jpg"
    img.write_bytes(b"\xff\xd8pkg")
    store.annotate("p1", snapshot_path=str(img))

    lab = Labeller()
    lab.vision = Vision(mode="live", cache_dir=tmp_path / "cache", client=FakeBedrock(PACKAGE_REPLY))
    lab.enabled = True
    lab.label(store, "p1", img)
    row = dict(store.recent()[0])
    assert row["kw_label"] == "package" and json.loads(row["vision"])["package_visible"]

    later = 1792372800000 + 70 * 60000           # 70 min later, 08:00 IST
    first = check_rules(store, now_ms=later)
    assert [a.rule for a in first] == ["package_waiting"]
    assert check_rules(store, now_ms=later + 60000) == []   # deduped: not sent twice


def test_labeller_survives_missing_aws(tmp_path):
    class Boom:
        def converse(self, **kw):
            raise RuntimeError("Unable to locate credentials")
    store = EventStore(tmp_path / "k.db")
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    lab = Labeller()
    lab.vision = Vision(mode="live", cache_dir=tmp_path / "c", client=Boom())
    lab.enabled = True
    lab.label(store, "missing", img)               # must not raise
    assert lab.enabled is False
