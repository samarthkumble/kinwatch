Devpost submission draft for KinWatch

Paste each part into the matching Devpost field. Section titles below match Devpost's default "About the project" template, so you can make them headings in the editor if you like. Read it once and change anything that doesn't sound like you.

PROJECT NAME
KinWatch: Ring Caretaking Agent for Parents Living Alone

ELEVATOR PITCH
A Ring-powered AI agent that watches an elderly parent's daily routine and alerts family when something's wrong, even when something that should have happened didn't.

TRACK
Ring

MINI CHALLENGE
AWS Builder

------------------------------------------------------------

Inspiration

My Ajji (grandmother) lives alone in Mangalore. I'm studying in Bengaluru, about 350 km away. Most days the only way I know she's okay is if I happen to call.

When I looked at what a doorbell camera could do for someone like her, I realised the normal alerts are the wrong way round. "Motion detected" fifty times a day doesn't help anyone. What actually matters to a family is the stuff that doesn't happen: she hasn't come out by ten, the parcel with her medicines has been sitting outside for an hour, or she was out in the morning and then nothing for half the day. I wanted something that tells me those things, and stays quiet otherwise.

What it does

KinWatch watches a Ring doorbell's events and turns them into the one thing a family member wants to know: is Ajji okay today?

- It reads devices, event history, snapshots and clips from the Ring Partner API.
- Ring's event history doesn't say what an event was (in the Playground every event is "on_demand" with no detections), so KinWatch grabs a snapshot for each event and has Amazon Rekognition label it: person, package, vehicle, animal or nothing.
- A small routine engine checks the day against what the family set up:
  - nobody seen at the door by the morning deadline
  - a package left outside longer than N minutes (one alert per parcel, cleared when someone takes it in)
  - seen in the morning, then the door is quiet for too many daytime hours
  - a person at the door at night
- Birds, empty frames and other noise are kept in the timeline but never alert.
- Alerts go to the family on Telegram with the Ring snapshot attached. Each alert is sent once.
- A caregiver dashboard shows today in one sentence, a timeline with snapshots, open alerts, and the routine settings.
- "Ask KinWatch": a Strands agent that answers questions like "How is Ajji doing today?" by calling KinWatch's MCP server (Streamable HTTP, protocol 2025-11-25). Any MCP client can use the same tools, which is how I'd connect it to Alexa+ next.

How I built it

- Python. No Ring SDK exists, so I wrote a small Ring client: OAuth bearer token, 429 / Retry-After backoff, JSON:API parsing, image and video downloads. It has a record mode and a replay mode, so anyone can run the project from the repo without a Ring token, using the real responses I recorded from the Playground.
- Snapshots come from the image download endpoint. If there's no snapshot, KinWatch downloads a short clip and pulls a frame out with OpenCV.
- Vision is pluggable: Amazon Bedrock (Nova 2 Lite) or Amazon Rekognition DetectLabels, with automatic fallback. Results are cached by image hash.
- SQLite stores events and sent alerts. The rules are plain, deterministic Python, so they're easy to test and explain.
- Flask for the dashboard (one page, no framework), Telegram Bot API for alerts.
- The MCP server uses the official MCP Python SDK. The agent uses the Strands Agents SDK with MCPClient to load those tools.
- About 50 automated tests, including tests built from real Ring and Rekognition responses.

AWS services used (AWS Builder)

- Amazon Rekognition (DetectLabels) labels every Ring snapshot. This is what turns "on_demand" into "a package has been left at the front door".
- Strands Agents SDK powers "Ask KinWatch", loading its tools from the KinWatch MCP server.
- Amazon Bedrock (Nova 2 Lite) is fully integrated as the preferred vision model and agent model. My new AWS India account gets "ValidationException: Operation not allowed" on every Bedrock call (support case open), so KinWatch falls back automatically: Rekognition for vision, and a local model through Ollama for the agent. The moment Bedrock is enabled on the account, KinWatch uses it with no code changes.

Challenges I ran into

- Ring's image download endpoint needs fields the docs don't mention (timestamp, and type = at_timestamp or latest_in_range). I worked them out from three error messages in a row.
- In the Playground, a Package event and a Motion event look identical in event history. That's what pushed me to label snapshots myself, and it ended up being the core of the product.
- Short simulated events sometimes have no recording at all (416 MEDIA_NOT_FOUND), so KinWatch marks them and moves on.
- My AWS account couldn't use Bedrock at all, so I had to make every AI part swappable without making the code messy.
- Making alerts not annoying: yesterday's parcel shouldn't alert today, and three sightings of the same parcel should be one alert, not three.

Accomplishments I'm proud of

- It works end to end on real Ring API data: a Playground event comes in, gets a snapshot, gets labelled by Rekognition, and an alert with the photo lands on my phone.
- The "absence" alerts. A camera app that tells you when nothing happened is the part I'd actually want for Ajji.
- Anyone can clone the repo and run it in replay mode with no accounts.

What I learned

- How the Ring Partner API and the Developers Playground work, and where the docs and the API disagree (all written up in my friction log).
- MCP and Strands: exposing tools once and reusing them from an agent, and how version details like MCP protocol 2025-11-25 matter.
- Designing alerts is mostly about what not to send.

What's next for KinWatch

- Connect the MCP server to Alexa+ so Ajji's family can just ask Alexa.
- Use real Ring Smart Alert sub-types (human, package_delivery, vehicle) when running on real devices, and only call vision when they're missing.
- Learn the routine automatically from a few weeks of events instead of setting times by hand.
- A daily summary message for the family, and a way for Ajji herself to tap "I'm okay" on the doorbell chime.

Built with
python, ring-partner-api, ring-developers-playground, amazon-rekognition, amazon-bedrock, strands-agents, model-context-protocol, ollama, flask, sqlite, opencv, telegram-bot-api

Links
GitHub: https://github.com/samarthkumble/kinwatch
Demo video: (add the YouTube link)

------------------------------------------------------------

Product feedback field: paste the "Product feedback" part of FRICTION_LOG.md.
Friction log field: paste the numbered entries from FRICTION_LOG.md.
Did the project exist before the hackathon? No. Everything was built from 19 Oct 2026, inside the submission window.
