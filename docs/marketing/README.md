# Marketing assets

| File | What |
|---|---|
| [`griptrack-promo.mp4`](griptrack-promo.mp4) | 18.5 s promo, 1920×1080, 60 fps, with soundtrack |
| [`griptrack-promo-portrait.mp4`](griptrack-promo-portrait.mp4) | The same cut at 1080×1920 for Reels / Shorts / Stories |
| [`griptrack-promo-poster.jpg`](griptrack-promo-poster.jpg) | Poster frame (Today beat + a "Watch" badge), used as the README thumbnail |
| [`video-script.md`](video-script.md) | Script: beat sheet, copy deck, demo data, soundtrack notes |
| [`../screenshots/app/`](../screenshots/app/) | Current app screenshots (2×, 824×1830) |

Everything is generated from the real app: nothing inside a phone frame is
mocked up. The pipeline lives in [`tooling/`](tooling/) and needs no system
installs beyond the dev requirements (`requirements-dev.txt`), plus
`numpy`, `matplotlib` and `imageio-ffmpeg` (a static ffmpeg with x264), all
pip-installable into a throwaway env.

## Regenerating

From the repo root:

```bash
W=/tmp/griptrack-marketing   # any scratch directory

# 1. Serve the on-device build on a freshly seeded demo database
#    (Alex, 16 weeks of history, "today" = Sat 26 Sep 2026).
docs/marketing/tooling/demo_server.sh $W/demo &

# 2. Capture every screen, the rest-ring and scroll flipbooks, and the tap
#    targets (runs one real session, so restart step 1 before re-running).
python docs/marketing/tooling/capture_app.py $W/capture $W/demo/demo.db

# 3. Repo screenshots.
python docs/marketing/tooling/export_screenshots.py $W/capture docs/screenshots/app

# 4. Backdrops, soundtrack, video (landscape and portrait).
python docs/marketing/tooling/topo_stage.py $W/topo
python docs/marketing/tooling/soundtrack.py $W/soundtrack.wav
python docs/marketing/tooling/render_video.py $W/capture $W/out --topo-dir $W/topo --audio $W/soundtrack.wav
python docs/marketing/tooling/render_video.py $W/capture $W/out --topo-dir $W/topo --audio $W/soundtrack.wav --layout portrait
python docs/marketing/tooling/render_video.py $W/capture $W/out --topo-dir $W/topo --poster 4.6
```

The videos land in `$W/out` as `griptrack-promo-{landscape,portrait}.mp4`
and the poster as `poster-landscape.jpg`; copy them over the files in this
directory.

`render_video.py --preview 4.3 9.5 13.8` writes stills at those timestamps
instead of a video, which is the quick way to check a layout change.

## How it works

- **`seed_demo.py`** writes the demo account straight through the SQLModel
  models into a migrated SQLite file, so the app renders it exactly like real
  data (every number on screen is computed by the app).
- **`capture_app.py`** drives the WebView build in headless Chromium at a
  Pixel-class viewport (412×915 CSS px, DPR 3), signs in with the device
  token as the Android shell does, and steps through Today → session play →
  summary → Progress. The rest ring is captured with `Date.now` pinned to
  each second of the rest, so the countdown frames are the app's own
  rendering.
- **`stage.html`** is the composition: phone frame, copy, callouts and
  backdrop, all a pure function of time (`renderFrame(t)`), so every frame is
  deterministic. The beat sheet at the bottom of its script mirrors
  `video-script.md`.
- **`render_video.py`** renders the stage frame by frame and pipes lossless
  PNGs straight into x264 (CRF 16, `yuv420p`, BT.709, `+faststart`).
- **`soundtrack.py`** synthesises the music from scratch and normalises it
  to −16 LUFS (two-pass `loudnorm`).
