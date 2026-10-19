import json

from kinwatch import notify
from kinwatch.notify import Notifier
from kinwatch.rules import Alert


class FakeResp:
    def __init__(self, body):
        self.body, self.status_code = body, 200

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, updates=None):
        self.calls, self.updates = [], updates or []

    def post(self, url, timeout=None, data=None, files=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, data, files))
        if method == "getUpdates":
            return FakeResp({"ok": True, "result": self.updates})
        return FakeResp({"ok": True, "result": {"message_id": 1}})


ALERT = Alert(key="k", rule="package_waiting", severity="medium",
              title="A delivery is still waiting <at> the door", message="Package & co.")


def test_discovers_chat_id_and_saves_it(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "STATE_FILE", tmp_path / "state")
    sess = FakeSession(updates=[{"message": {"chat": {"id": 4242, "first_name": "Samarth"}}}])
    n = Notifier(token="t", chat_id=None, session=sess)
    n.chat_id = None
    n.send_alert(ALERT)
    method, data, _ = sess.calls[-1]
    assert method == "sendMessage" and data["chat_id"] == "4242"
    assert "&lt;at&gt;" in data["text"] and "&amp;" in data["text"]   # HTML-escaped
    assert json.loads((tmp_path / "state").read_text())["chat_id"] == "4242"


def test_sends_photo_when_snapshot_exists(tmp_path):
    img = tmp_path / "snap.jpg"
    img.write_bytes(b"\xff\xd8")
    sess = FakeSession()
    Notifier(token="t", chat_id="1", session=sess).send_alert(ALERT, photo=img)
    method, data, files = sess.calls[-1]
    assert method == "sendPhoto" and "photo" in files and data["chat_id"] == "1"


def test_console_fallback_without_token(capsys, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    n = Notifier(token=None, chat_id=None)
    n.token = None
    n.send_alert(ALERT)
    assert "[console alert]" in capsys.readouterr().out
