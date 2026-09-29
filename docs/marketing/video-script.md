# GripTrack promo — video script

**Length:** 18.5 s · **Formats:** 1920×1080 landscape (README, YouTube, desktop)
and 1080×1920 portrait (Reels, Shorts, Stories, status) · **60 fps**, H.264 +
AAC · **Loudness:** −16 LUFS integrated, −1.5 dBTP.

**Idea:** one real phone, one real session. The viewer watches the app coach a
single pull day, from the plan to the finished workout. Three beats: *it
plans*, *it runs*, *it proves*. Every pixel inside the phone is the
real app (the on-device build on seeded demo data), captured by
`tooling/capture_app.py`. Nothing is mocked up.

**Tone:** calm, confident, gym-quiet. The app's own dark "gym mode" palette,
Barlow / Barlow Condensed type and topographic contour lines carry the
brand, so the film looks like the product.

**Audience:** climbers who already train fingers (block pulls, no-hangs) and
want the numbers to mean something.

## Beat sheet

| Time | Picture | On-screen copy | Sound |
|---|---|---|---|
| 0.0–0.35 | Fade up from black. Contour lines draw themselves in, level by level. | — | Pad swells in (A minor 9). |
| 0.3–2.1 | **GripTrack** rises letter by letter; the orange full stop pops in. | *GripTrack.* / *Finger-strength training for climbers* | Bell pluck + soft sub on the dot (0.85 s). |
| 2.1–2.6 | Wordmark lifts away. The phone sweeps up from below, untilting. | — | Air whoosh; pulse starts at 120 BPM. |
| 2.75–5.4 | **Today.** The home screen: Saturday's plan, per-hand weights (L 37 kg, R 38 kg). A callout lands on the reason line. | **01 Today** — *Today's plan, worked out.* / *Each hand's load comes from your **current max**, rounded to the plates you actually own.* · callout: **Autoregulated** — *+0.5 kg after two easy sessions* | — |
| 5.3 | Finger taps **Start session**. | — | UI tick. |
| 5.45–7.7 | **Session play.** The warmup ladder slides up: 50 % → 65 % → 80 % → 90 %, one tap on **Rung done** per rung. | **02 Session** — *A session that runs itself.* / *Warmup ramp, one set at a time, and a **rest ring** that keeps counting on the lock screen.* · callout: **Warmup ramp** — *50 → 90 % of your max* | Whoosh; a pluck arpeggio starts; a rising tick per tap. |
| 7.7–9.2 | Work set 2 of 3 pushes in. A tap on **＋** walks the left hand from 37.0 to 37.5 kg (the next loadable plate combination); then **Set done**. | callout: **Plate-loadable steps** — *Only weights your plates can make* | Ticks. |
| 9.3–10.95 | The rest ring counts a full 3:00 down in about a second, then flips to **Pull**. | callout: **3:00 rest ring** — *Lock-screen countdown + buzz* | Whoosh. |
| 11.0–14.9 | **Progress.** The Progress tab pushes in and scrolls to the headline chart: strength as % of bodyweight per hand, stepping up with each max test, boulder sends as grade-coloured dots above it. The phone slowly leans in. | **03 Progress** — *See it show up on the wall.* / *Strength as **% of bodyweight**, next to every boulder you send.* · counters: **+25 %** left hand, **+21 %** right hand (3 months), **85** boulder sends logged | Chord moves to G6. |
| 14.95–16.0 | Copy clears. The phone glides to centre, its screen settling on **Done for today.** Two more phones fan out behind it: the work set and the chart. | — | Drums drop out; whoosh. |
| 15.95–18.1 | End card. | **GripTrack.** / *Block-pull training · plans · progress — on your Android phone, offline* | The progression lands on C major 9 with a high shimmer. |
| 18.05–18.5 | Fade to black. | — | Tail fades. |

## Copy deck

Kept short enough to read in one pass at the speed it's on screen; each line
names something the app really does (the numbers are the demo account's, as
the app computes them):

- *Finger-strength training for climbers* — the category, plainly.
- *Today's plan, worked out.* — Today computes the session: sets × reps and
  each hand's load from CurrentMax, rounded to the user's plate inventory,
  nudged by RPE autoregulation (ADR-0011/-0012).
- *A session that runs itself.* — session play (ADR-0014): warmup rungs, one
  Set commit at a time, a stored rest countdown mirrored on the lock screen by
  the native rest bridge (ADR-0015).
- *See it show up on the wall.* — Progress: CurrentMax as % of bodyweight
  beside boulder sends; the story sentences' "+25 % / +21 % in 3 months".
- *On your Android phone, offline* — the on-device build (ADR-0006, #93): no
  server, no account, nothing leaves the phone.

## The demo account

"Alex", kg, 16 weeks of history (`tooling/seed_demo.py`): four half-crimp /
20 mm max tests climbing from 36/38 kg to 44/45 kg, open-hand and pinch tests,
two to three 3 × 5 sessions a week with RPE, one deload week, a weekly
bodyweight log drifting from 70.4 to about 68.5 kg and 85 boulder sends
progressing from 6B to 7A+. Today is Saturday 26 September 2026; the last
session was two days ago, both at RPE 7, so the plan suggests adding weight.

## Soundtrack

Synthesised from scratch by `tooling/soundtrack.py` (numpy only, no samples
or loops), so there is nothing to license. It's cue-locked to the beat sheet
above: the chord changes follow the scenes, a UI tick sits under every
on-screen tap, and an air whoosh marks every scene change. To use licensed
music instead, pass any WAV/MP3 to `render_video.py --audio`.
