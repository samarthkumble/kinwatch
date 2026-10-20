KinWatch demo video script (target 2:50, hard limit 3:00)

How this script is built, from what past winners and judges did:
- Open with a real person and the problem in your own words, before any tech (EcoLafaek, 1st place, and Drishti both open this way).
- Show the product working within the first 15 seconds, not after a long intro.
- Show the old frustration next to the new version, so the difference is obvious.
- One flow, one "oh, this is possible now" moment: an alert about something that DIDN'T happen.
- Use a real number for impact, say plainly what's simulated, and stay under 3:00 (judges may stop there).

Lines in quotes are what you say. Lines in brackets are what's on screen. Text marked CAPTION goes on screen as large text, so it works with the sound off. Change any line that isn't true for you. It has to be your story.

------------------------------------------------------------

0:00 - 0:15  Ajji (the person, and the product already working)

[Close-up of your phone. Telegram buzzes: "🔴 No sign of Ajji yet this morning". Tap it so the message and the Ring snapshot are readable.]
CAPTION: My Ajji lives alone in Mangalore.

"My Ajji lives alone in Mangalore. I study in Bengaluru, three hundred and fifty kilometres away. This is the message I'd want, the morning something isn't right."

0:15 - 0:35  The old way vs what families actually need

[Screen: Ring event history JSON in the Playground API explorer, scrolling. Every event says "on_demand". Then cut to the KinWatch dashboard.]
CAPTION: Motion alerts are table stakes.

"A doorbell camera knows one thing: something moved. Again. And again. But one in four Americans over sixty-five lives alone, and for their families the scary moment isn't motion. It's when nothing happens. Ajji not out by ten. Her medicines left outside."
CAPTION (small, bottom): Pew Research Center, 2023 data

0:35 - 1:05  One real Ring event, understood

[Ring Developers Playground: click Package. Cut to the terminal running the poller: the new event, "snapshot saved", then "vision [package]: A package has been left at the front door."]
"KinWatch reads Ring events through the Ring API. Ring isn't sold in India yet, so this is Ring's Developers Playground: the real API, a simulated doorbell. Ring reports every event the same way, so KinWatch grabs the snapshot and asks Amazon Rekognition what's in it."

[Dashboard timeline: the package with its photo and a "Package" tag. Below it, the bird-feeder clip greyed out and tagged "Ignored".]
"A parcel. Maybe her medicines. This one, same 'on_demand' from Ring, is just birds at the feeder. So KinWatch stays quiet."
CAPTION: Same Ring event. Different meaning.

1:05 - 1:40  The moment: an alert about what didn't happen

[Dashboard: type 12:15 into "Check a different time", click it. The header turns to "A delivery is still waiting at the door". Scroll a little to show "No sign of Ajji yet this morning" in "Needs your attention".]
"I set Ajji's routine once: when she's usually up, how long a delivery should wait outside, how many quiet hours is too many in the daytime. KinWatch checks every Ring event against it. And it tells me when something that should have happened, didn't."

[Phone: the Telegram alert "A delivery is still waiting at the door" with the package photo attached.]
"With the photo, so I know what I'm calling her about. One message per problem, never fifty."
CAPTION: Alerts for what didn't happen.

1:40 - 2:05  Just ask

[Dashboard: type "How is Ajji doing today?" into Ask KinWatch, click Ask. Cut the waiting in editing. Show the answer.]
"When I'm worried, I just ask. This Strands agent checks today's Ring events through KinWatch's own MCP server and answers in plain words, without guessing. It runs on my laptop, so nothing about Ajji leaves home. And as a standard MCP server, it can plug into Alexa plus next."

2:05 - 2:30  How it's built (and what's real)

[One slide: the architecture diagram. Ring Partner API (devices, event history, snapshots, clips) -> KinWatch poller -> Amazon Rekognition (Bedrock-ready) -> routine rules -> Telegram alerts, dashboard, MCP server -> Strands agent.]
"Under the hood: the Ring Partner API for events, snapshots and clips; Amazon Rekognition for vision, with Bedrock built in for when my account allows it; a small rules engine; and a Strands agent over MCP. It's open source, with a replay mode, so you can run it from GitHub without a Ring token."

2:30 - 2:50  Why it matters, and close

[Back to the dashboard, the whole page in view.]
"Ring's own app store already has an elder care category. KinWatch is what I think that should feel like: not another camera feed, just the one answer a family needs every day."
[Title card: KinWatch. A Ring caretaking agent for grandparents who live alone. github.com/samarthkumble/kinwatch]
"Is Ajji okay today? Now I'd know."

------------------------------------------------------------

BEFORE RECORDING (on the recording day, so all events are "today")
- Ring Playground: click Package, let it finish. Wait a minute. Click Motion (the bird-feeder clip), let it finish. Don't simulate a person: nobody coming to the door is the story.
- Terminal: set your Ring token, AWS keys, KINWATCH_VISION_BACKEND=rekognition and TELEGRAM_BOT_TOKEN, then run "python -m kinwatch.poller --once". Check both events got labels.
- Check that the "No sign of Ajji yet this morning" Telegram message arrived (record after 10:00 am).
- For the 1:05 phone shot, the package alert fires 60 minutes after the package. Either wait, or set "Package wait" to 5 minutes in the dashboard's Routine and run the poller again after 5 minutes.
- Dashboard at 110-125% browser zoom so text is readable. Close other tabs. Mute notifications. Use Telegram Desktop if filming the phone is awkward.
- The architecture slide: I'll make it.

RECORDING
- Record each section as its own clip. Screen: OBS Studio or Xbox Game Bar (Win+G), 1080p.
- Voice: record separately in a quiet room, phone close to your mouth. Speak a little slower than normal. Sound like you mean it; judges notice when someone is just reading.
- Edit in Clipchamp (built into Windows) or CapCut: put the clips in order, lay the voice over them, add the CAPTION text, and cut every loading pause.
- Time it. If it's over 2:55, cut a sentence. Don't speed up your voice.
- No copyrighted music. YouTube, Public, in English. Title: "KinWatch: a Ring caretaking agent for grandparents who live alone".

Sources behind the structure:
- EcoLafaek (AWS AI Agent Hackathon 1st place): https://devpost.com/software/ecolafaek
- Drishti AI Navigator (category winner): https://devpost.com/software/drishti-ai-navigator
- AgentShell (Best Strands SDK, closest to a Ring caretaking agent): https://devpost.com/software/agent-shell
- Judges' advice: https://blog.jetbrains.com/ai/2026/06/how-to-win-a-hackathon-notes-from-the-judging-table/
- Organizers on the Ring track: https://amazonappdev2026.devpost.com/updates/46456-got-an-idea
- Older adults living alone: https://www.pewresearch.org/short-reads/2025/12/04/a-smaller-share-of-older-us-adults-live-alone-today-than-in-1990/
