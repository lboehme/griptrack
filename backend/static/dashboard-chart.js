// Dashboard TrainingVolume trend charts (issue #88) and Asymmetry trend
// charts (issue #46): draws uPlot charts into container divs rendered by
// the server, fed by JSON-in-DOM payloads (#volume-trend-data and
// #asymmetry-chart-data).
//
// Mark specs and both theme palettes match the design system: 2px
// round-capped line, 8px markers with a 2px surface-color ring, ~10%-opacity
// area wash (for volume), hairline solid recessive grid, endpoint direct-
// labeled, axis text in muted "ink" token.
// Asymmetry charts display signed series, zero line at y=0, and shaded
// ±10-15% reference bands.
// Requires uPlot vendored at /static/uplot.iife.min.js.
document.addEventListener("DOMContentLoaded", () => {
  if (typeof uPlot === "undefined") return;

  const THEMES = {
    light: {
      surface: "#ffffff",
      mark: "#e8532c",
      ink: "#68727f",
      grid: "#eef0f3",
      text: "#14181f",
      band: "rgba(232, 161, 60, 0.15)",
      zeroLine: "#93a4b4",
    },
    dark: {
      surface: "#14171e",
      mark: "#ef5a30",
      ink: "#93a4b4",
      grid: "#262c37",
      text: "#eceef1",
      band: "rgba(243, 185, 95, 0.15)",
      zeroLine: "#68727f",
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

  function asymmetryBandsPlugin() {
    return {
      hooks: {
        drawAxes: [
          (u) => {
            const ctx = u.ctx;
            const { left, top, width, height } = u.bbox;
            ctx.save();
            ctx.beginPath();
            ctx.rect(left, top, width, height);
            ctx.clip();

            // Draw reference bands: +10% to +15% and -10% to -15%
            ctx.fillStyle = palette.band;

            // Upper band (+10% to +15%)
            const y15 = u.valToPos(15, "y", true);
            const y10 = u.valToPos(10, "y", true);
            ctx.fillRect(left, y15, width, y10 - y15);

            // Lower band (-10% to -15%)
            const yNeg10 = u.valToPos(-10, "y", true);
            const yNeg15 = u.valToPos(-15, "y", true);
            ctx.fillRect(left, yNeg10, width, yNeg15 - yNeg10);

            // Zero line at y = 0
            const y0 = u.valToPos(0, "y", true);
            ctx.strokeStyle = palette.zeroLine;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(left, y0);
            ctx.lineTo(left + width, y0);
            ctx.stroke();

            ctx.restore();
          },
        ],
      },
    };
  }

  function asymmetryEndpointLabelPlugin(gaps) {
    return {
      hooks: {
        draw: [
          (u) => {
            if (!gaps.length) return;
            const lastIndex = gaps.length - 1;
            const xPos = u.valToPos(u.data[0][lastIndex], "x", true);
            const yPos = u.valToPos(gaps[lastIndex], "y", true);
            const ctx = u.ctx;
            ctx.save();
            ctx.fillStyle = palette.text;
            ctx.font = "bold 11px system-ui, sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "bottom";
            const val = gaps[lastIndex];
            const formatted =
              (val > 0 ? "+" : "") +
              (val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)) +
              "%";
            ctx.fillText(formatted, xPos, yPos - 14);
            ctx.restore();
          },
        ],
      },
    };
  }

  const charts = [];

  // 1. TrainingVolume trend charts
  const dataEl = document.getElementById("volume-trend-data");
  if (dataEl) {
    let combos;
    try {
      combos = JSON.parse(dataEl.textContent);
    } catch (e) {
      combos = [];
    }
    if (Array.isArray(combos) && combos.length) {
      const targetsByCombo = new Map();
      document.querySelectorAll(".trend-chart[data-chart-combo]").forEach((el) => {
        targetsByCombo.set(el.dataset.chartCombo, el);
      });

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
    }
  }

  // 2. Strength gap asymmetry trend charts
  const asymmetryDataEl = document.getElementById("asymmetry-chart-data");
  if (asymmetryDataEl) {
    let asymmetryPairs;
    try {
      asymmetryPairs = JSON.parse(asymmetryDataEl.textContent);
    } catch (e) {
      asymmetryPairs = [];
    }
    if (Array.isArray(asymmetryPairs) && asymmetryPairs.length) {
      const targetsByAsymmetry = new Map();
      document
        .querySelectorAll(".asymmetry-chart[data-chart-asymmetry]")
        .forEach((el) => {
          targetsByAsymmetry.set(el.dataset.chartAsymmetry, el);
        });

      asymmetryPairs.forEach((pair) => {
        const target = targetsByAsymmetry.get(pair.combo);
        if (!target || !pair.dates.length) return;

        const xs = pair.dates.map(toUnixSeconds);
        const ys = pair.gaps;

        const opts = {
          width: target.clientWidth || 320,
          height: 220,
          padding: [24, 12, 8, 8],
          scales: {
            x: { time: true },
            y: {
              range: (u, dataMin, dataMax) => [
                Math.min(dataMin != null ? dataMin - 2 : 0, -20),
                Math.max(dataMax != null ? dataMax + 2 : 0, 20),
              ],
            },
          },
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
              values: (u, vals) => vals.map((v) => (v > 0 ? `+${v}%` : `${v}%`)),
            },
          ],
          plugins: [asymmetryBandsPlugin(), asymmetryEndpointLabelPlugin(ys)],
        };

        const chart = new uPlot(opts, [xs, ys], target);
        chart.root.style.background = palette.surface;
        chart.root.style.borderRadius = "10px";
        charts.push({ chart, target });
      });
    }
  }

  // uPlot sizes off the container's width at construction time; a resize
  // (orientation change, layout shift) leaves it stale, so keep every chart
  // in sync the same lightweight way the rest of the app avoids a
  // ResizeObserver dependency. One shared listener iterates all charts
  // rather than registering (and firing) a separate handler per combo.
  if (charts.length) {
    window.addEventListener("resize", () => {
      charts.forEach(({ chart, target }) => {
        chart.setSize({ width: target.clientWidth || 320, height: 220 });
      });
    });
  }
});
