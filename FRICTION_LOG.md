Friction log + product feedback

I'm building KinWatch solo from Bengaluru, with no Ring device, so pretty much everything below happened in the Ring Developers Playground. I started on Mon 19 Oct and wrote these down as they happened.

Severity: High = I was blocked, Medium = cost me real time / needed a workaround, Low = annoying but quick.

RING

1. Snapshot download wants fields the docs don't mention (Medium)

What I was doing: getting a snapshot for an event with `POST /v1/devices/{id}/media/image/download`.

What I tried: the docs only talk about an optional `components` array, so I sent an empty body.

What I expected: a JPEG.

What happened: three errors in a row, each one telling me about one more field:
- `403 REQUEST_FORBIDDEN` - "Cannot authorize: missing required timestamp fields in request body"
- added `timestamp` -> `400` "type is required"
- tried `jpeg`, `png` etc. -> `400` "type not supported, valid values: at_timestamp, latest_in_range"

Workaround: `{"timestamp": <epoch ms>, "type": "at_timestamp"}`. I guessed the timestamp part from the video download docs, which do have an example. Worked after that.

Suggestion: please add the request body + one example to the Image Snapshots section like Media Clips has. Also the 403 threw me off at first. I thought my token was bad, when it was just a missing field. A 400 that names the field would have saved me ~20 min.

2. Package and Motion look identical in event history (Medium)

What I was doing: checking if I could tell a simulated Package event from a Motion event using only the API.

What I tried: clicked Package, then Motion in the Playground, then called `GET /v1/history/devices/{id}/events`.

What I expected: different `event_type` / `sub_type`, or something in `cv_detections`.

What happened: both came back as `event_type: "on_demand"` with empty `cv_detections`. No way to tell them apart.

Workaround: KinWatch grabs a snapshot for each event and asks Amazon Rekognition what's in it (Bedrock Nova 2 Lite was the plan, see #7). Honestly this turned into the main feature of the app, because the package clip and the bird-feeder clip look nothing alike even though the API calls them the same thing.

Suggestion: let simulated events carry the same `sub_type` values real devices send (`package_delivery`, `vehicle`, `human`...), so we can test that path without hardware.

3. Some events just have no media (Low)

What happened: two of my events (5 s and 20 s long) gave `416 MEDIA_NOT_FOUND` even when I asked for the whole event's time range. The ~30-40 s ones always had media. I think the short ones were live views I stopped early, but I'm not sure.

Workaround: KinWatch marks those as "no recording" and stops retrying.

Suggestion: a `has_media` flag on history events, or a line in the docs about what gets recorded.

4. Playground tokens (Low)

Tokens last 30 min, which is fine, but I regenerated a lot during development. The thing that actually confused me: while a token is still valid, the generate button doesn't show, so I sat there wondering where it went. A visible countdown + a "regenerate" button would fix that.

5. Took a while to find the Playground (Low)

The Get Started and Develop pages are all about testing with a real device (and Develop says only US devices are supported), which made me think the Ring track wouldn't work from India. The Playground link was only in the release notes. Once I found it, it worked fine from India. Worth linking it right on the Get Started page for people without hardware.

6. No SDK (Low)

Not a big deal, but I spent the first hour writing my own client (auth header, 429/Retry-After backoff, JSON:API parsing, media downloads). A small official Python or TS SDK would help a lot of people get to the fun part faster.

AWS

7. Bedrock blocked on my new AWS account (High)

What I was doing: first call to Amazon Nova 2 Lite in the Bedrock playground (us-east-1), on an AWS account I created that day (AWS India).

What happened:
- around 1:25 pm: `AccessDeniedException` - "Your account is currently being verified..." (says it usually takes under 2 hours)
- around 2:35 pm: `ValidationException` - "Operation not allowed", for every model I tried (Nova 2 Lite and Nova Micro)
- payment method (UPI AutoPay) was already verified and default, so it wasn't that

Workaround: opened a support case (Account and billing). Meanwhile I built and tested everything that didn't need Bedrock, and the Bedrock code runs against a fake client in my tests so I'd know it was ready.

Update, Thu 22 Oct: still blocked, support case still open. I switched vision to Amazon Rekognition (DetectLabels), which worked on the same account straight away, and kept Bedrock as the first choice in the code with an automatic fallback. The agent runs on a local model through Ollama for now.

Suggestion: "Operation not allowed" doesn't tell you anything. Something like "Bedrock isn't enabled for this account yet" would have saved me an hour of trying different models and regions. And for the hackathon itself, it'd be nice to tell people to create their AWS account early and test one Bedrock call before starting.

PRODUCT FEEDBACK

Ring Developers Playground
- What I used it for: everything Ring: the simulated device, Package/Motion events, event history, snapshots and clips.
- What worked: it worked from India with no device and no subscription, which is the only reason I could do the Ring track at all. The one-click token and the curl commands in the API explorer got my first call working in minutes.
- What needs work: simulated event types (#2), token UX (#4), and how hard it was to find (#5).
- Onboarding: fast once I found it.
- Would I use it again: yes.

Ring Partner API
- What I used it for: devices, capabilities, event history, image and video download.
- What worked: responses are consistent, and the 400 errors that list valid values are what got me unstuck on #1.
- What needs work: the snapshot request docs (#1), knowing whether media exists (#3), an SDK (#6).
- Would I use it again: yes.

Amazon Bedrock (Nova 2 Lite)
- What I used it for: labelling each Ring snapshot (person / package / vehicle / animal / nothing) plus a one-line description a family member can read on their phone.
- How it went: I never got one successful call (see #7), so I can't say anything about label quality yet. The code path is tested against a fake client and turns on by itself once the account is enabled.
- What needs work: new account activation (#7).

Amazon Rekognition (DetectLabels)
- What I used it for: labelling every Ring snapshot after Bedrock was blocked. This is what turns "on_demand" into "a package has been left at the front door".
- What worked: it worked first try on the same account where Bedrock was refused. Trying an image in the console before writing any code was really useful, and calls come back fast.
- What needs work: the labels are very generic for a doorstep. On my clear Playground parcel frame it returned Outdoors 99.9, Nature 99.9, Weather 99.5, then Box only 79.1, and Hot Tub 62.4 for a snowy porch. I had to write my own mapping with thresholds and a list of generic labels to ignore. A doorstep/delivery label set, or a package label tuned for porches, would help a lot.
- Onboarding: very quick, once I had IAM access keys.
- Would I use it again: yes.

Strands Agents SDK
- What I used it for: the "Ask KinWatch" agent. Bedrock is the model, and it gets its tools from my MCP server through `MCPClient` over Streamable HTTP.
- What worked: `MCPClient` + `list_tools_sync()` turned my MCP tools into agent tools in a few lines, and `BedrockModel` taking an `api_key` matched the Bedrock API keys nicely.
- How it went: since Bedrock was blocked, I ran the same agent on a local model with Strands' `OllamaModel` (qwen2.5:7b). Swapping the model was one line, which I really liked.
- What needs work: with a small local model the agent sometimes invented times or answered in bullet lists when my tools returned nested JSON. I fixed it by adding plain one-line "facts" to the tool output and putting the current time in the system prompt. A short note in the docs about tool-output shape for smaller models would help. On a laptop CPU one answer takes about a minute, but that's the model, not Strands.
- Would I use it again: yes.

MCP (Python SDK 1.x, protocol 2025-11-25)
- What I used it for: the KinWatch MCP server (`get_today_status`, `list_events`, `get_alerts`, `get_routine`).
- One gotcha: the newest Python SDK (2.x) defaults to the 2026-07-28 protocol and renamed FastMCP, so my first import failed. I pinned `mcp<2` to stay on 2025-11-25, which is what Alexa+ and Strands use.
