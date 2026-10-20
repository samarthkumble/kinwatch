KinWatch demo video script (target 2:45, hard limit 3:00)

Read the voiceover slowly. Every line in quotes is what you say. Everything in brackets is what's on screen. Check every personal line is true for you and change anything that isn't. It has to be your story, in your words.

BEFORE RECORDING (same morning, so the events count as "today")
- In the Ring Playground: click Package and let it finish. Wait a minute. Click Motion (the bird feeder clip) and let it finish.
- Terminal: run the poller once with your Ring token and AWS keys so both events get snapshots and Rekognition labels.
- Don't simulate a person. Nobody visiting is the story.
- Dashboard open at http://127.0.0.1:8050, browser zoom 110-125% so text is readable on video.
- Telegram open on your phone (or Telegram Desktop) with the alerts visible.
- Turn off other notifications. Close tabs with personal stuff.

0:00 - 0:20  The hook
[Your phone buzzing with the Telegram alert "No sign of Ajji yet this morning". Hold it to the camera or screen-record it.]
"My Ajji lives alone in Mangalore. I'm studying in Bengaluru, about 350 kilometres away. Most days, the only way I know she's okay is if I happen to call."

0:20 - 0:40  The problem
[Dashboard, top section, red status "No sign of Ajji yet this morning".]
"Smart doorbells already send you an alert every time something moves. But for someone like my grandmother, the scary moments aren't when something happens. It's when something that should happen, doesn't. So I built KinWatch, on Ring."

0:40 - 1:15  Real Ring events, understood
[Ring Developers Playground: click Package. Then the terminal: the poller printing the new event, "snapshot saved", "vision [package]: A package has been left at the front door."]
"KinWatch reads Ring events through the Ring API. Here I'm using Ring's Developers Playground, because Ring isn't sold in India yet. The API reports every event the same way. It doesn't say what it saw. So KinWatch pulls the snapshot and asks Amazon Rekognition what's actually there."
[Dashboard timeline: the package with its photo and "Package" tag, the bird clip dimmed with "Ignored".]
"This one is a parcel, maybe her medicines. This one is just birds at the feeder, so it's ignored. No alert spam."

1:15 - 1:50  Alerts about what didn't happen
[Dashboard: type 12:15 into "Check a different time" and click "Check this time". Status changes to "A delivery is still waiting at the door". Point at the routine settings.]
"I set her routine once. When she's usually up and about, how long a delivery should sit outside, what counts as night. If the parcel is still there after an hour, or nobody has been seen by ten, or she was out in the morning and then the door goes quiet for hours in the middle of the day, I get a message."
[Phone: Telegram alert with the package snapshot attached.]
"With the photo, so I know exactly what's going on before I call her."

1:50 - 2:20  Just ask
[Dashboard: type "How is Ajji doing today?" into Ask KinWatch, click Ask, wait for the answer. Cut the waiting time in editing.]
"I can also just ask. This is a Strands agent. It calls KinWatch's own MCP server to check today's events and answers in plain words, without making anything up. Because it's a standard MCP server, the same tools can plug into any assistant, including Alexa plus."

2:20 - 2:40  How it's built
[One slide: the architecture diagram. Ring Partner API -> poller -> snapshot -> Amazon Rekognition (or Bedrock) -> routine rules -> Telegram, dashboard, MCP server -> Strands agent.]
"Under the hood: the Ring Partner API for devices, event history, snapshots and clips. Amazon Rekognition for vision, with Bedrock support built in. A rules engine for the routine. And a Strands agent over an MCP server. The repo also has a replay mode, so you can run the whole thing without a Ring token."

2:40 - 2:55  Close
[Back to the dashboard, status green "Ajji's day looks normal" (check a time like 09:30 if you have a morning event, otherwise just the dashboard).]
"Ring's own app store already has an elder care category. KinWatch is my attempt at what that should feel like: not a camera feed, just the one thing I actually want to know. Is Ajji okay today?"
[Title card: KinWatch. github.com/samarthkumble/kinwatch]

RECORDING TIPS
- Record the screen with OBS Studio (free) or Windows Xbox Game Bar (Win+G). 1080p.
- Record the voice separately, in a quiet room, phone close to your mouth. It sounds much better than the laptop mic.
- Record each section as its own clip. Edit them together in Clipchamp (comes with Windows) or CapCut.
- Cut all waiting (loading, the agent thinking). Judges won't watch past 3:00.
- No background music unless it's royalty free (rules forbid copyrighted music).
- Upload to YouTube as Public (the rules require a public video, in English), title "KinWatch - a Ring caretaking agent for grandparents who live alone".
