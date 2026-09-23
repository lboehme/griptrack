"""Regenerate docs/design/topo-map.svg, the contour-line motif from the
2026-09 redesign prototype (see docs/ui-review-2026-09.md, "Visual language").

A one-off design tool, not part of the app or the dev loop: it needs numpy
and matplotlib, which the runtime deliberately doesn't ship (#89). Run it in
a throwaway env, then commit the SVG it writes.

    python docs/design/topo_generator.py            # writes topo-map.svg
    python docs/design/topo_generator.py --seed 5   # a different landscape

The map is contour lines of a smooth height field: a few Gaussian "hills"
plus low-frequency sine noise, traced with matplotlib's contour() and
decimated to keep the path small (~55 KB). The SVG uses stroke="currentColor"
so the page decides colour and opacity.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

WIDTH, HEIGHT = 390, 900  # one phone screen (CSS px), a little taller than 844
HILLS = [  # (x, y, spread, height)
    (310, 110, 75, 1.4),
    (70, 360, 95, 1.2),
    (330, 560, 70, 1.0),
    (90, 800, 80, 1.3),
    (380, 880, 50, 0.7),
]
LEVELS = 22


def contour_path(seed: int) -> str:
    rng = np.random.default_rng(seed)
    x = np.linspace(0, WIDTH, 220)
    y = np.linspace(0, HEIGHT, int(220 * HEIGHT / WIDTH))
    X, Y = np.meshgrid(x, y)
    Z = np.zeros_like(X)
    for cx, cy, spread, height in HILLS:
        Z += height * np.exp(-((X - cx) ** 2 + (Y - cy) ** 2) / (2 * spread**2))
    for _ in range(9):  # organic wobble so rings aren't perfect ellipses
        k = rng.uniform(0.004, 0.018, 2)
        phase = rng.uniform(0, 6.3, 2)
        Z += 0.28 * np.sin(k[0] * X + phase[0]) * np.cos(k[1] * Y + phase[1])

    contours = plt.contour(X, Y, Z, levels=LEVELS)
    parts = []
    for segs in contours.allsegs:
        for seg in segs:
            if len(seg) < 12:
                continue
            pts = seg[::3] if len(seg) > 60 else seg[::2]
            parts.append("M" + " L".join(f"{px:.0f} {py:.0f}" for px, py in pts))
    plt.close("all")
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=21)
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).with_name("topo-map.svg")
    )
    args = parser.parse_args()
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        'fill="none" stroke="currentColor" stroke-width="1">\n'
        f'<path d="{contour_path(args.seed)}"/>\n</svg>\n'
    )
    args.out.write_text(svg)
    print(f"wrote {args.out} ({len(svg) // 1024} KB)")


if __name__ == "__main__":
    main()
