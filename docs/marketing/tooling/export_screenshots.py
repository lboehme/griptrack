"""Export the repo's app screenshots from a capture_app.py run.

    python docs/marketing/tooling/export_screenshots.py CAPTURE_DIR docs/screenshots/app

Writes 2x (824 x 1830) palette PNGs of the screens the README and docs show.
"""

import argparse
from pathlib import Path

from PIL import Image

# output name -> captured screen
SCREENS = {
    "today": "today",
    "warmup": "warmup-1",
    "work-set": "workset-2",
    "rest": "rest",
    "summary": "summary",
    "done": "today-done",
    "log-sheet": "log-sheet-7a",
    "progress": "progress-chart",
    "volume": "volume",
    "balance": "balance",
    "maxes": "maxes",
    "timeline": "timeline",
    "settings": "settings",
}
WIDTH = 824


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, src in SCREENS.items():
        with Image.open(args.capture / "screens" / f"{src}.png") as im:
            height = round(im.height * WIDTH / im.width)
            small = im.convert("RGB").resize((WIDTH, height), Image.LANCZOS)
            # A 256-colour palette with dithering is visually lossless on
            # this dark UI and ~2.5x smaller than truecolour PNG.
            small.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(
                args.out / f"{name}.png", optimize=True
            )


if __name__ == "__main__":
    main()
