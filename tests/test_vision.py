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


PACKAGE_LABELS = [
    {"Name": "Cardboard", "Confidence": 98.1, "Parents": [{"Name": "Box"}]},
    {"Name": "Box", "Confidence": 97.5, "Parents": []},
    {"Name": "Snow", "Confidence": 95.0, "Parents": [{"Name": "Outdoors"}]},
    {"Name": "Staircase", "Confidence": 90.0, "Parents": []},
]
BIRD_LABELS = [
    {"Name": "Bird", "Confidence": 99.0, "Parents": [{"Name": "Animal"}]},
    {"Name": "Bird Feeder", "Confidence": 92.0, "Parents": []},
    {"Name": "Snow", "Confidence": 90.0, "Parents": []},
]


class FakeRekognition:
    def __init__(self, labels):
        self.labels, self.calls = labels, 0

    def detect_labels(self, **kw):
        self.calls += 1
        assert kw["Image"]["Bytes"]
        return {"Labels": self.labels}


def test_rekognition_labels_map_to_kinwatch_labels():
    from kinwatch.vision import rekognition_to_result
    pkg = rekognition_to_result(PACKAGE_LABELS)
    assert pkg.label == "package" and pkg.package_visible and not pkg.person_visible
    assert pkg.description.startswith("A package has been left")
    assert "snow" in pkg.description
    bird = rekognition_to_result(BIRD_LABELS)
    assert bird.label == "animal" and "bird" in bird.description
    person = rekognition_to_result([{"Name": "Person", "Confidence": 99}] + PACKAGE_LABELS)
    assert person.label == "person" and person.package_visible   # person outranks package
    assert rekognition_to_result([{"Name": "Snow", "Confidence": 90}]).label == "nothing"


def test_auto_falls_back_to_rekognition_when_bedrock_refused(tmp_path, capsys):
    class Refused:
        calls = 0

        def converse(self, **kw):
            Refused.calls += 1
            raise RuntimeError("An error occurred (ValidationException) when calling the "
                               "Converse operation: Operation not allowed")

    rek = FakeRekognition(PACKAGE_LABELS)
    v = Vision(mode="live", cache_dir=tmp_path / "c", client=Refused(),
               rekognition_client=rek, backend="auto")
    for i in range(2):
        img = tmp_path / f"{i}.jpg"
        img.write_bytes(b"img%d" % i)
        r = v.describe(img)
        assert r.label == "package" and r.model == "amazon-rekognition-detectlabels"
    assert Refused.calls == 1 and rek.calls == 2        # Bedrock not retried
    assert "using Amazon Rekognition" in capsys.readouterr().out


def test_bedrock_only_mode_does_not_fall_back(tmp_path):
    class Refused:
        def converse(self, **kw):
            raise RuntimeError("Operation not allowed")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"x")
    v = Vision(mode="live", cache_dir=tmp_path / "c", client=Refused(),
               rekognition_client=FakeRekognition(PACKAGE_LABELS), backend="bedrock")
    with pytest.raises(RuntimeError):
        v.describe(img)


def test_rekognition_on_real_playground_package_frame():
    # labels Rekognition returned in the console for our real Ring package snapshot
    from kinwatch.vision import rekognition_to_result
    real = [{"Name": "Outdoors", "Confidence": 99.9}, {"Name": "Nature", "Confidence": 99.9},
            {"Name": "Weather", "Confidence": 99.5}, {"Name": "Box", "Confidence": 79.1},
            {"Name": "Snow", "Confidence": 62.9}, {"Name": "Hot Tub", "Confidence": 62.4}]
    r = rekognition_to_result(real)
    assert r.label == "package" and r.package_visible
    assert r.description == "A package has been left at the front door."   # no noise
