"""Family alerts over Telegram (with the Ring snapshot attached).

Setup:
  1. Create a bot with @BotFather, copy the token.
  2. Open your bot in Telegram, tap Start and send it any message.
  3. $env:TELEGRAM_BOT_TOKEN="123:ABC..."   then   python -m kinwatch.notify --test
     The first run finds your chat id automatically and remembers it in
     .kinwatch_telegram (git-ignored). TELEGRAM_CHAT_ID overrides it.

Without a token, alerts are printed to the console instead, so the rest of
KinWatch never depends on Telegram being set up.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
STATE_FILE = Path(".kinwatch_telegram")
SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "info": "🔵"}


class TelegramError(RuntimeError):
    pass


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None,
                 session: requests.Session | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID") or self._load_chat_id()
        self.session = session or requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    # ------------------------------------------------------------- plumbing
    def _call(self, method: str, **kwargs) -> dict:
        resp = self.session.post(API.format(token=self.token, method=method),
                                 timeout=30, **kwargs)
        try:
            body = resp.json()
        except ValueError:
            raise TelegramError(f"{method}: HTTP {resp.status_code}")
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'unknown error')}")
        return body["result"]

    @staticmethod
    def _load_chat_id() -> str | None:
        try:
            return json.loads(STATE_FILE.read_text()).get("chat_id")
        except (OSError, ValueError):
            return None

    def discover_chat_id(self) -> str:
        """Find the chat of whoever last messaged the bot (you, after tapping Start)."""
        updates = self._call("getUpdates", data={"limit": 50})
        for upd in reversed(updates):
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat") or {}
            if chat.get("id") is not None:
                self.chat_id = str(chat["id"])
                STATE_FILE.write_text(json.dumps({"chat_id": self.chat_id,
                                                  "name": chat.get("first_name")}))
                return self.chat_id
        raise TelegramError("No messages found. Open your bot in Telegram, tap Start, "
                            "send it 'hi', then try again.")

    def _ensure_chat(self) -> str:
        return self.chat_id or self.discover_chat_id()

    # ---------------------------------------------------------------- send
    def send_text(self, text: str) -> None:
        if not self.enabled:
            print(f"[console alert] {text}")
            return
        self._call("sendMessage", data={"chat_id": self._ensure_chat(), "text": text,
                                        "parse_mode": "HTML",
                                        "disable_web_page_preview": True})

    def send_alert(self, alert, photo: str | Path | None = None) -> None:
        """alert: kinwatch.rules.Alert. Attaches the Ring snapshot when available."""
        icon = SEVERITY_ICON.get(alert.severity, "🔔")
        caption = (f"{icon} <b>{html.escape(alert.title)}</b>\n"
                   f"{html.escape(alert.message)}\n\n<i>KinWatch · Ring front door</i>")
        if not self.enabled:
            print(f"[console alert] {alert.title}: {alert.message}")
            return
        chat = self._ensure_chat()
        photo = Path(photo) if photo else None
        if photo and photo.exists() and photo.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            with photo.open("rb") as fh:
                self._call("sendPhoto", data={"chat_id": chat, "caption": caption[:1024],
                                              "parse_mode": "HTML"},
                           files={"photo": (photo.name, fh)})
        else:
            self._call("sendMessage", data={"chat_id": chat, "text": caption,
                                            "parse_mode": "HTML"})


def main() -> None:
    ap = argparse.ArgumentParser(description="KinWatch Telegram alerts")
    ap.add_argument("--test", action="store_true", help="send a test message")
    ap.add_argument("--photo", help="attach this image to the test alert")
    args = ap.parse_args()
    n = Notifier()
    if not n.enabled:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN first (from @BotFather).")
    try:
        me = n._call("getMe")
        print(f"Bot token OK: @{me.get('username')}")
        chat = n._ensure_chat()
    except TelegramError as exc:
        raise SystemExit(f"Telegram: {exc}")
    print(f"Telegram chat id: {chat} (saved to {STATE_FILE})")
    if args.test or args.photo:
        from .rules import Alert
        n.send_alert(Alert(key="test", rule="test", severity="info",
                           title="KinWatch is connected",
                           message="You'll get alerts here when something at the door needs you."),
                     photo=args.photo)
        print("Test alert sent. Check Telegram.")


if __name__ == "__main__":
    main()
