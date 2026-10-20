"""Ask KinWatch: a Strands agent on Amazon Bedrock that answers a family member's
questions ("How is Amma doing today?") by calling the KinWatch MCP server.

  python -m kinwatch.mcp_server                       # terminal 1
  python -m kinwatch.agent "How is Amma doing today?"  # terminal 2

If the MCP server isn't running, the agent uses the same tools in-process, so
it still works (and says which path it used).

Model (KINWATCH_AGENT_MODEL):
  bedrock  Amazon Nova 2 Lite on Bedrock (AWS_BEARER_TOKEN_BEDROCK or AWS credentials)
  ollama   a local model through Ollama (default qwen2.5:3b), nothing leaves the laptop
  auto     (default) Bedrock, and if this AWS account refuses Bedrock, Ollama
"""
from __future__ import annotations

import argparse
import os

from strands import Agent, tool
from strands.models import BedrockModel

from . import mcp_server
from .settings import load_config
from .vision import MODEL_ID, REGION

MCP_URL = os.environ.get("KINWATCH_MCP_URL",
                         f"http://{mcp_server.HOST}:{mcp_server.PORT}/mcp")


def system_prompt() -> str:
    name = load_config().parent_name
    return (
        f"You are KinWatch, a calm, caring assistant for a family member whose parent, "
        f"{name}, lives alone. You can see {name}'s Ring front-door camera through tools. "
        "Always call tools before answering; never invent events or times. "
        "Answer in 2 to 4 short sentences a busy person can read on a phone: first the "
        "direct answer, then the evidence (times, what the camera saw), then one "
        "suggestion only if something needs attention (for example, 'consider calling "
        f"{name}'). Mention ignored noise (birds, empty frames) only if it reassures. "
        "Times are in IST, 24-hour format.")


AGENT_MODEL = os.environ.get("KINWATCH_AGENT_MODEL", "auto").lower()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("KINWATCH_OLLAMA_MODEL", "qwen2.5:3b")
_REFUSED = ("Operation not allowed", "AccessDenied", "currently being verified",
            "Unable to locate credentials", "not authorized")


def _model(kind: str = "bedrock"):
    if kind == "ollama":
        from strands.models.ollama import OllamaModel
        return OllamaModel(OLLAMA_HOST, model_id=OLLAMA_MODEL, temperature=0.2)
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2,
                        api_key=os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or None)


def model_label(kind: str) -> str:
    return f"Ollama {OLLAMA_MODEL} (local)" if kind == "ollama" else f"Bedrock {MODEL_ID}"


# In-process fallback: the same functions the MCP server exposes.
@tool
def get_today_status(at: str | None = None) -> dict:
    """How is the parent's day going? Optional at="HH:MM" to check another time."""
    return mcp_server.get_today_status(at)


@tool
def list_events(label: str | None = None, limit: int = 20, at: str | None = None) -> list:
    """Today's front-door events, newest first; optional label filter."""
    return mcp_server.list_events(label, limit, at)


@tool
def get_alerts(at: str | None = None) -> list:
    """Alerts that need the family's attention right now."""
    return mcp_server.get_alerts(at)


@tool
def get_routine() -> dict:
    """The parent's expected routine (name, usual wake time, package wait, night hours)."""
    return mcp_server.get_routine()


LOCAL_TOOLS = [get_today_status, list_events, get_alerts, get_routine]


def _mcp_reachable(url: str) -> bool:
    import requests
    try:
        # any HTTP answer (even 4xx for a bare GET) means the server is up
        requests.get(url, timeout=2)
        return True
    except requests.RequestException:
        return False


def _run(question: str, kind: str, use_mcp: bool) -> str:
    if use_mcp:
        from mcp.client.streamable_http import streamablehttp_client
        from strands.tools.mcp import MCPClient
        client = MCPClient(lambda: streamablehttp_client(MCP_URL))
        with client:
            agent = Agent(model=_model(kind), tools=client.list_tools_sync(),
                          system_prompt=system_prompt(), callback_handler=None)
            return str(agent(question)).strip()
    agent = Agent(model=_model(kind), tools=LOCAL_TOOLS, system_prompt=system_prompt(),
                  callback_handler=None)
    return str(agent(question)).strip()


def ask(question: str, use_mcp: bool | None = None,
        model: str | None = None) -> tuple[str, str]:
    """Return (answer, path). path is 'mcp' or 'local'; the model used is in
    ask.last_model ('bedrock' or 'ollama')."""
    if use_mcp is None:
        use_mcp = _mcp_reachable(MCP_URL)
    path = "mcp" if use_mcp else "local"
    kind = (model or AGENT_MODEL).lower()
    if kind in ("bedrock", "auto"):
        try:
            ask.last_model = "bedrock"
            return _run(question, "bedrock", use_mcp), path
        except Exception as exc:
            if kind == "bedrock" or not any(m in str(exc) for m in _REFUSED):
                raise
            print(f"(Bedrock refused this account: {str(exc)[:80]}; using local Ollama model)")
    ask.last_model = "ollama"
    return _run(question, "ollama", use_mcp), path


ask.last_model = "bedrock"


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask KinWatch a question")
    ap.add_argument("question", nargs="*", default=["How is Amma doing today?"])
    ap.add_argument("--local", action="store_true", help="skip the MCP server")
    ap.add_argument("--model", choices=["auto", "bedrock", "ollama"],
                    help="which model to use (default: KINWATCH_AGENT_MODEL or auto)")
    args = ap.parse_args()
    q = " ".join(args.question)
    answer, path = ask(q, use_mcp=False if args.local else None, model=args.model)
    via = "MCP " + MCP_URL if path == "mcp" else "in-process"
    print(f"\nQ: {q}\nA: {answer}\n\n(model {model_label(ask.last_model)}, tools via {via})")


if __name__ == "__main__":
    main()
