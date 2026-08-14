// Dashboard TrainingVolume trend charts (issue #88): draws one uPlot chart
// per trained combo into the `.trend-chart` container the server renders,
// fed by the `#volume-trend-data` JSON-in-DOM payload (see worksets.html's
// ladder-data/saved-sets-data precedent). Replaces the old server-rendered
// <picture>/<img> pointing at GET /dashboard/volume.svg
// (backend/charts.py, removed with this change).
//
// Mark specs and both theme palettes are ported verbatim from the retired
// backend/charts.py docstring/THEMES: 2px round-capped line, 8px markers
// with a 2px surface-color ring, ~10%-opacity area wash, hairline solid
// recessive y-grid, endpoint direct-labeled, axis text in the muted "ink"
// token (never the series color). Requires uPlot (vendored at
// /static/uplot.iife.min.js, loaded just before this script) -- this file
// no-ops if that global isn't present, e.g. before the script loads.
document.addEventListener("DOMContentLoaded", () => {
  if (typeof uPlot === "undefined") return;

  const dataEl = document.getElementById("volume-trend-data");
  if (!dataEl) return;

  let combos;
  try {
    combos = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }
  if (!Array.isArray(combos) || !combos.length) return;

  const THEMES = {
    light: {
      surface: "#ffffff",
      mark: "#e8532c",
      ink: "#68727f",
      grid: "#eef0f3",
      text: "#14181f",
    },
    dark: {
      surface: "#14171e",
      mark: "#ef5a30",
      ink: "#93a4b4",
      grid: "#262c37",
      text: "#eceef1",
    },
  };
  const prefersDark =
    window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const palette = prefersDark ? THEMES.dark : THEMES.light;

  // ~10%-opacity area wash under the line, matching the old ax.fill_between
  // alpha=0.10 -- appended as an 8-digit hex alpha suffix.
  const AREA_FILL = palette.mark + "1a";

  function toUnixSeconds(isoDate) {
    return Math.floor(new Date(isoDate + "T00:00:00Z").getTime() / 1000);
  }

  // Selective direct label: the endpoint only, drawn as a small bold value
  // above the last point -- the one bit uPlot's built-in series/legend
  // doesn't give for free, so it's a draw hook rather than a plugin.
  function endpointLabelPlugin(volumes) {
    return {
      hooks: {
        draw: [
          (u) => {
            if (!volumes.length) return;
            const lastIndex = volumes.length - 1;
            const xPos = u.valToPos(u.data[0][lastIndex], "x", true);
            const yPos = u.valToPos(volumes[lastIndex], "y", true);
            const ctx = u.ctx;
            ctx.save();
            ctx.fillStyle = palette.text;
            ctx.font = "bold 11px system-ui, sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "bottom";
            const label =
              volumes[lastIndex] % 1 === 0
                ? String(volumes[lastIndex])
                : volumes[lastIndex].toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
            ctx.fillText(label, xPos, yPos - 14);
            ctx.restore();
          },
        ],
      },
    };
  }

  // Map combo key -> container, built once. Matched by key rather than a
  // quoted attribute selector so grip names never need CSS-escaping.
  const targetsByCombo = new Map();
  document.querySelectorAll(".trend-chart[data-chart-combo]").forEach((el) => {
    targetsByCombo.set(el.dataset.chartCombo, el);
  });

  const charts = [];
  combos.forEach((combo) => {
    const target = targetsByCombo.get(combo.combo);
    if (!target || !combo.dates.length) return;

    const xs = combo.dates.map(toUnixSeconds);
    const ys = combo.volumes;

    const opts = {
      width: target.clientWidth || 320,
      height: 220,
      padding: [24, 12, 8, 8],
      scales: { x: { time: true } },
      cursor: { show: false },
      legend: { show: false },
      series: [
        {},
        {
          stroke: palette.mark,
          width: 2,
          points: {
            show: true,
            size: 8,
            stroke: palette.surface,
            width: 2,
            fill: palette.mark,
          },
          fill: AREA_FILL,
        },
      ],
      axes: [
        {
          stroke: palette.ink,
          grid: { show: false },
          ticks: { show: false },
          font: "10px system-ui, sans-serif",
        },
        {
          stroke: palette.ink,
          grid: { show: true, stroke: palette.grid, width: 1 },
          ticks: { show: false },
          font: "10px system-ui, sans-serif",
        },
      ],
      plugins: [endpointLabelPlugin(ys)],
    };

    const chart = new uPlot(opts, [xs, ys], target);
    chart.root.style.background = palette.surface;
    chart.root.style.borderRadius = "10px";
    charts.push({ chart, target });
  });

  // uPlot sizes off the container's width at construction time; a resize
  // (orientation change, layout shift) leaves it stale, so keep every chart
  // in sync the same lightweight way the rest of the app avoids a
  // ResizeObserver dependency. One shared listener iterates all charts
  // rather than registering (and firing) a separate handler per combo.
  window.addEventListener("resize", () => {
    charts.forEach(({ chart, target }) => {
      chart.setSize({ width: target.clientWidth || 320, height: 220 });
    });
  });
});
