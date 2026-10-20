import pytest

from kinwatch import agent, mcp_server, settings
from kinwatch.store import EventStore


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from test_dashboard import add
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "s.json")
    db = tmp_path / "k.db"
    store = EventStore(db)
    add(store, "e1", "07:40", "person", "An older woman collects the newspaper.")
    add(store, "e2", "08:00", "package", "A cardboard package on the front steps.")
    add(store, "e3", "08:20", "animal", "Birds at a feeder.")
    monkeypatch.setattr(mcp_server, "DB_PATH", str(db))
    return db


def test_mcp_tools_answer_from_the_database(seeded):
    s = mcp_server.get_today_status("09:15")
    assert s["status"]["level"] == "medium" and s["open_alerts"] == 1
    assert [e["label"] for e in mcp_server.list_events(at="09:15")] == ["animal", "package", "person"]
    assert mcp_server.list_events(label="person", at="09:15")[0]["time"] == "07:40"
    assert mcp_server.get_alerts("09:15")[0]["title"].startswith("A delivery")
    assert mcp_server.get_routine()["parent_name"] == "Ajji"
    with pytest.raises(ValueError):
        mcp_server.get_today_status("9am")


def test_mcp_server_registers_four_tools():
    import asyncio
    names = sorted(t.name for t in asyncio.run(mcp_server.mcp.list_tools()))
    assert names == ["get_alerts", "get_routine", "get_today_status", "list_events"]


def test_agent_local_path_wires_tools_and_prompt(seeded, monkeypatch):
    built = {}

    class FakeAgent:
        def __init__(self, model, tools, system_prompt, callback_handler):
            built.update(tools=tools, prompt=system_prompt)

        def __call__(self, q):
            return "Ajji was seen at 07:40. A delivery has been waiting since 08:00."

    monkeypatch.setattr(agent, "Agent", FakeAgent)
    monkeypatch.setattr(agent, "_model", lambda kind="bedrock": kind)
    answer, path = agent.ask("How is Ajji doing today?", use_mcp=False, model="bedrock")
    assert path == "local" and "07:40" in answer
    assert len(built["tools"]) == 4 and "never invent" in built["prompt"]
    assert "Ajji" in built["prompt"]


def test_agent_falls_back_to_ollama_when_bedrock_refused(seeded, monkeypatch, capsys):
    used = []

    class FakeAgent:
        def __init__(self, model, tools, system_prompt, callback_handler):
            self.model = model

        def __call__(self, q):
            used.append(self.model)
            if self.model == "bedrock":
                raise RuntimeError("ValidationException: Operation not allowed")
            return "Ajji was seen at 07:40."

    monkeypatch.setattr(agent, "Agent", FakeAgent)
    monkeypatch.setattr(agent, "_model", lambda kind="bedrock": kind)
    answer, _ = agent.ask("How is Ajji?", use_mcp=False, model="auto")
    assert used == ["bedrock", "ollama"] and agent.ask.last_model == "ollama"
    assert "using local Ollama model" in capsys.readouterr().out
    with pytest.raises(RuntimeError):
        agent.ask("How is Ajji?", use_mcp=False, model="bedrock")


def test_status_facts_are_plain_and_correct(seeded):
    f = mcp_server.get_today_status("09:15")["facts"]
    assert f[0].startswith("The current time is 09:15")
    assert any("last seen at the front door at 07:40" in x for x in f)
    assert any(x.startswith("Open alert: A delivery") for x in f)
    assert mcp_server.get_today_status("07:30")["facts"][1] == \
        "Ajji has not been seen at the front door yet today."
