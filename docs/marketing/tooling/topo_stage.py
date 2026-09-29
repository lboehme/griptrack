"""Contour-map backdrops for the marketing video, in the app's topo style.

Same recipe as docs/design/topo_generator.py (Gaussian hills + sine
wobble, traced with matplotlib's contour()), but at video frame sizes and
with one <path> per contour level, so the stage can draw the lines in
level by level. Needs numpy + matplotlib (tooling only, never the app).

    python docs/marketing/tooling/topo_stage.py OUT_DIR
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

LEVELS = 26

# (width, height, hills as (x, y, spread, height) in 0..1 frame units)
FRAMES = {
    "topo-16x9.svg": (
        1920,
        1080,
        [
            (0.12, 0.20, 0.13, 1.3),
            (0.70, 0.52, 0.16, 1.5),
            (0.95, 0.10, 0.09, 0.9),
            (0.33, 0.92, 0.12, 1.1),
            (0.52, 0.18, 0.07, 0.6),
        ],
    ),
    "topo-9x16.svg": (
        1080,
        1920,
        [
            (0.80, 0.10, 0.20, 1.4),
            (0.20, 0.40, 0.24, 1.2),
            (0.85, 0.62, 0.18, 1.0),
            (0.25, 0.90, 0.20, 1.3),
        ],
    ),
}


def render(width: int, height: int, hills: list, seed: int) -> str:
    rng = np.random.default_rng(seed)
    x = np.linspace(0, width, 420)
    y = np.linspace(0, height, int(420 * height / width))
    X, Y = np.meshgrid(x, y)
    Z = np.zeros_like(X)
    scale = max(width, height)
    for cx, cy, spread, h in hills:
        Z += h * np.exp(-((X - cx * width) ** 2 + (Y - cy * height) ** 2) / (2 * (spread * scale) ** 2))
    for _ in range(9):
        k = rng.uniform(0.0018, 0.008, 2)
        phase = rng.uniform(0, 6.3, 2)
        Z += 0.26 * np.sin(k[0] * X + phase[0]) * np.cos(k[1] * Y + phase[1])

    contours = plt.contour(X, Y, Z, levels=LEVELS)
    paths = []
    for level, segs in enumerate(contours.allsegs):
        parts = []
        for seg in segs:
            if len(seg) < 16:
                continue
            pts = seg[::2]
            parts.append("M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts))
        if parts:
            paths.append(f'<path data-level="{level}" d="{" ".join(parts)}"/>')
    plt.close("all")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'fill="none" stroke="currentColor" stroke-width="1.2">\n' + "\n".join(paths) + "\n</svg>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--seed", type=int, default=21)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, (width, height, hills) in FRAMES.items():
        (args.out / name).write_text(render(width, height, hills, args.seed))


if __name__ == "__main__":
    main()
