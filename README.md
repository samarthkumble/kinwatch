# KinWatch

A Ring caretaking agent for parents who live alone. Built for the Amazon Developer Hackathon 2026 (Ring track + AWS Builder).

> Status: Ring data layer, Bedrock vision, routine rules, Telegram alerts and the caregiver dashboard work. Strands agent and MCP server are next.

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt

# Option A: no token needed (replays recorded Playground data)
#   Windows PowerShell:  $env:KINWATCH_MODE="replay"
#   Mac/Linux:           export KINWATCH_MODE=replay
python -m kinwatch.poller --once

# Option B: live Ring Playground
#   1. Open https://developer.amazon.com/ring/console/playground and generate a token (30 min)
#   2. Set it:  PowerShell  $env:RING_ACCESS_TOKEN="..."   Mac/Linux  export RING_ACCESS_TOKEN=...
#   3. Set KINWATCH_MODE=record to also save responses as replay fixtures
python -m kinwatch.poller --interval 15

python -m pytest -q
```

## Vision (Amazon Bedrock) and routine rules

```powershell
$env:AWS_BEARER_TOKEN_BEDROCK="your-bedrock-api-key"   # Bedrock console -> API keys
python -m kinwatch.poller --label          # label stored snapshots with Nova 2 Lite
python -m kinwatch.rules --at 10:05        # demo clock: evaluate rules as if it's 10:05
python -m kinwatch.rules --advance 65      # or fast-forward 65 minutes
```

Rules: **no activity** by the morning deadline, **package waiting** more than 60 min, **person at the door at night**. Animals and empty frames never alert. Vision answers are cached in `fixtures/vision/`, so replay mode works without AWS.

## Caregiver dashboard

```powershell
python -m kinwatch.dashboard        # open http://127.0.0.1:8050
```

Answers "is Amma okay today?" in one sentence, shows the day's Ring events with snapshots (birds and empty frames dimmed as ignored), current alerts, an editable routine, and a "check a different time" control for demos.

## Telegram alerts

```powershell
$env:TELEGRAM_BOT_TOKEN="from @BotFather"
python -m kinwatch.notify --test    # after sending your bot a message
```

## What we learned about the Playground (feeds the friction log)

- Simulated Package / Vehicle / Motion events show up in event history as `event_type: "on_demand"` with an empty `cv_detections` list, so the API alone can't tell you *what* happened.
- KinWatch fills that gap: it grabs a snapshot for each event and labels it itself (Bedrock vision, next step). On real devices with Smart Alerts on, motion events carry `sub_type` (`human`, `vehicle`, `package_delivery`, `other_motion`), and KinWatch will use those when present.
