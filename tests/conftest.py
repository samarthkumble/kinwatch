import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))   # lets tests share helpers


import pytest

# Settings a developer may have exported in their terminal (keys, backends,
# record mode...). Tests must never pick these up or call real services.
_ENV_TO_CLEAR = (
    "KINWATCH_VISION_BACKEND", "KINWATCH_VISION", "KINWATCH_AGENT_MODEL", "KINWATCH_MODE",
    "KINWATCH_OLLAMA_MODEL", "KINWATCH_VISION_MODEL", "RING_ACCESS_TOKEN", "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK", "AWS_PROFILE",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
