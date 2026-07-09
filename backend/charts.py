"""Server-rendered SVG charts (no client-side charting library).

Mark specs follow the dataviz guidance: 2px round-capped line, >=8px
markers with a 2px surface ring, ~10%-opacity area wash, hairline solid
recessive grid, endpoint direct-labeled, text in ink tokens (never the
series color for text). Both theme palettes are validator-passing steps
against their surface (light #e8532c / dark #ef5a30 — the bright UI
accent fails the dark lightness band, so the chart uses its own step).
"""

import io
from datetime import date as date_type

from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure

THEMES = {
    "light": {
        "surface": "#ffffff",
        "mark": "#e8532c",
        "ink": "#68727f",
        "grid": "#eef0f3",
        "text": "#14181f",
    },
    "dark": {
        "surface": "#14171e",
        "mark": "#ef5a30",
        "ink": "#93a4b4",
        "grid": "#262c37",
        "text": "#eceef1",
    },
}


def render_volume_chart(
    trend: list[tuple[date_type, float]], theme: str = "light"
) -> str:
    palette = THEMES[theme]
    # Figure (not pyplot) keeps rendering free of global state, so
    # concurrent requests can't trample each other.
    fig = Figure(figsize=(6.4, 2.6), dpi=100)
    fig.patch.set_facecolor(palette["surface"])
    ax = fig.subplots()
    ax.set_facecolor(palette["surface"])

    dates = [date for date, _ in trend]
    volumes = [volume for _, volume in trend]

    ax.grid(axis="y", color=palette["grid"], linewidth=1, zorder=1)
    ax.plot(
        dates,  # type: ignore[arg-type]  # matplotlib stubs don't accept list[date] directly, though it renders correctly
        volumes,
        color=palette["mark"],
        linewidth=2,
        solid_capstyle="round",
        solid_joinstyle="round",
        marker="o",
        markersize=8,
        markerfacecolor=palette["mark"],
        markeredgecolor=palette["surface"],
        markeredgewidth=2,
        zorder=3,
    )
    ax.margins(x=0.06, y=0.22)
    ax.fill_between(
        dates,  # type: ignore[arg-type]  # same matplotlib stub gap as ax.plot above
        volumes, ax.get_ylim()[0],
        color=palette["mark"], alpha=0.10, linewidth=0, zorder=2,
    )
    # Selective direct label: the endpoint only.
    ax.annotate(
        f"{volumes[-1]:g}",
        (dates[-1], volumes[-1]),
        textcoords="offset points",
        xytext=(0, 11),
        ha="center",
        color=palette["text"],
        fontsize=10.5,
        fontweight="bold",
    )

    for spine in ax.spines.values():
        spine.set_visible(False)
    locator = AutoDateLocator(maxticks=6)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    ax.tick_params(colors=palette["ink"], labelsize=8.5, length=0)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color(palette["ink"])

    buffer = io.StringIO()
    fig.savefig(
        buffer, format="svg", bbox_inches="tight", facecolor=palette["surface"]
    )
    return buffer.getvalue()
