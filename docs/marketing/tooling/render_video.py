"""Render the promo video from stage.html and the captured app screens.

    python docs/marketing/tooling/render_video.py CAPTURE_DIR OUT_DIR \
        [--layout landscape|portrait] [--fps 60] [--audio soundtrack.wav]
        [--preview 1.0 4.2 ...] [--poster 4.6]

CAPTURE_DIR is capture_app.py's output. The stage page is rendered in
headless Chromium one frame at a time (renderFrame(t) is a pure function
of t), screenshotted losslessly and piped straight into ffmpeg's x264, so
no intermediate frames touch the disk. --preview writes PNG stills for the
given timestamps instead of a video.

ffmpeg comes from the imageio-ffmpeg wheel (a static build with libx264),
so nothing needs installing system-wide.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FONTS = REPO / "backend" / "static" / "fonts"
SCREEN_WIDTH = 720  # supersampled for a ~390-520 px on-stage screen
SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920)}


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def prepare(capture: Path, build: Path) -> None:
    """Stage page + fonts + downscaled screens, side by side for file://."""
    (build / "fonts").mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "stage.html", build / "index.html")
    for font in FONTS.glob("*.woff2"):
        shutil.copy(font, build / "fonts" / font.name)
    for src in (capture / "screens").rglob("*.png"):
        dst = build / "screens" / src.relative_to(capture / "screens")
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            height = round(im.height * SCREEN_WIDTH / im.width)
            im.convert("RGB").resize((SCREEN_WIDTH, height), Image.LANCZOS).save(dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--layout", choices=SIZES, default="landscape")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--crf", type=int, default=16)
    parser.add_argument("--preview", type=float, nargs="*")
    parser.add_argument("--poster", type=float, help="write a JPEG poster frame (with a play badge) at this time")
    parser.add_argument("--topo-dir", type=Path, required=True, help="topo_stage.py output directory")
    args = parser.parse_args()

    build = args.out / "build"
    prepare(args.capture, build)
    manifest = json.loads((args.capture / "manifest.json").read_text())
    width, height = SIZES[args.layout]
    topo_name = "topo-16x9.svg" if args.layout == "landscape" else "topo-9x16.svg"
    topo_svg = (args.topo_dir / topo_name).read_text()

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.on("pageerror", lambda e: print("stage error:", e, file=sys.stderr))
        page.add_init_script(f"window.MANIFEST = {json.dumps(manifest)};")
        page.goto((build / "index.html").as_uri() + "#" + args.layout)
        page.evaluate("svg => window.stageReady(svg)", topo_svg)
        duration = page.evaluate("window.DURATION")

        if args.poster is not None:
            page.evaluate(f"window.renderFrame({args.poster})")
            page.evaluate("window.showPlayBadge()")
            page.screenshot(path=str(args.out / f"poster-{args.layout}.jpg"), type="jpeg", quality=92)
            browser.close()
            return

        if args.preview is not None:
            for t in args.preview:
                page.evaluate(f"window.renderFrame({t})")
                page.screenshot(path=str(args.out / f"preview-{args.layout}-{t:05.2f}.png"))
            browser.close()
            return

        video = args.out / f"griptrack-promo-{args.layout}.mp4"
        cmd = [
            ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "image2pipe",
            "-framerate",
            str(args.fps),
            "-c:v",
            "png",
            "-i",
            "-",
        ]
        if args.audio:
            cmd += ["-i", str(args.audio), "-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            str(args.crf),
            "-tune",
            "animation",
            "-pix_fmt",
            "yuv420p",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-movflags",
            "+faststart",
            str(video),
        ]
        encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        frames = round(duration * args.fps)
        for i in range(frames):
            page.evaluate(f"window.renderFrame({i / args.fps})")
            encoder.stdin.write(page.screenshot(type="png"))
            if i % args.fps == 0:
                print(f"  {i / args.fps:5.1f}s / {duration}s", flush=True)
        encoder.stdin.close()
        encoder.wait()
        browser.close()
        print("wrote", video)


if __name__ == "__main__":
    main()
