// Dashboard TrainingVolume trend charts (issue #88) and Asymmetry trend
// charts (issue #46): draws uPlot charts into container divs rendered by
// the server, fed by JSON-in-DOM payloads (#volume-trend-data and
// #asymmetry-chart-data).
//
// Mark specs match the design system (docs/ui-review-2026-09.md, V2/V7):
// 2px round-capped line, 8px markers with a surface-color ring, ~10%-opacity
// area wash (for volume), hairline solid recessive grid, endpoint direct-
// labeled, axis text in the muted token. The palette is read from the
// page's own CSS custom properties (issue #144's dark-only token set,
// app.css's :root block) rather than picked from prefers-color-scheme, so
// there's exactly one source of truth for colour. The second series in
// each chart (Mean Intensity / Load Gap) is drawn as a dotted chalk line
// rather than a second hue, so it stays distinguishable without colour —
// the same non-colour rule V2 uses for the L/R hand lines.
// Requires uPlot vendored at /static/uplot.iife.min.js.
document.addEventListener("DOMContentLoaded", () => {
  if (typeof uPlot === "undefined") return;

  const style = getComputedStyle(document.documentElement);
  const token = (name, fallback) => {
    const v = style.getPropertyValue(name).trim();
    return v || fallback;
  };

  // Alpha tint of a token colour, for canvas (which can't take var()).
  // Tokens are 6-digit hex today; any other valid colour is used as-is
  // (opaque) rather than falling back to a hard-coded tint.
  function withAlpha(color, alpha) {
    const hex = /^#([0-9a-fA-F]{6})$/.exec(color);
    if (!hex) return color;
    const n = parseInt(hex[1], 16);
    return "rgba(" + (n >> 16) + ", " + ((n >> 8) & 255) + ", " + (n & 255) + ", " + alpha + ")";
  }

  const palette = {
    // Charts sit on strong glass (see app.css's .trend-chart/.asymmetry-chart
    // rules) — deliberately not opaque, so the topo map and card blur keep
    // showing through behind the plotted lines/points.
    surface: "transparent",
    mark: token("--acc", "#FF6A3D"),
    loadMark: token("--tx", "#F4EFE7"),
    intensityMark: token("--tx", "#F4EFE7"),
    ink: token("--mu", "#A89F92"),
    grid: token("--line", "#383229"),
    text: token("--tx", "#F4EFE7"),
    band: withAlpha(token("--warn", "#F2B24C"), 0.15),
    zeroLine: token("--mu", "#A89F92"),
    // The point ring needs a genuinely opaque colour (not the transparent
    // "surface" above) so markers read as solid dots over the glass/topo
    // background rather than punching a hole in the line.
    pointRing: token("--s1", "#1D1A16"),
  };

  // ~10%-opacity area wash under the line, matching the old ax.fill_between
  // alpha=0.10 -- derived from the --acc token like every chart colour.
  const AREA_FILL = withAlpha(palette.mark, 0.1);

  function toUnixSeconds(isoDate) {
    return Math.floor(new Date(isoDate + "T00:00:00Z").getTime() / 1000);
  }

  // Selective direct label: the endpoint only, drawn as a small bold value
  // above the last point -- the one bit uPlot's built-in series/legend
  // doesn't give for free, so it's a draw hook rather than a plugin.
  function trendEndpointLabelPlugin() {
    return {
      hooks: {
        draw: [
          (u) => {
            const ctx = u.ctx;
            const endpoints = [];
            for (let sIdx = 1; sIdx < u.series.length; sIdx++) {
              const sData = u.data[sIdx];
              if (!sData || !sData.length) continue;
              let lastIdx = -1;
              for (let i = sData.length - 1; i >= 0; i--) {
                if (sData[i] != null) {
                  lastIdx = i;
                  break;
                }
              }
              if (lastIdx !== -1) {
                const val = sData[lastIdx];
                const scaleKey = u.series[sIdx].scale || "y";
                const xPos = u.valToPos(u.data[0][lastIdx], "x", true);
                const yPos = u.valToPos(val, scaleKey, true);
                const label =
                  scaleKey === "intensity"
                    ? `${Math.round(val * 100)}%`
                    : val % 1 === 0
                      ? String(val)
                      : val.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
                endpoints.push({
                  xPos,
                  yPos,
                  label,
                  color: u.series[sIdx].stroke || palette.text,
                });
              }
            }

            if (!endpoints.length) return;

            ctx.save();
            ctx.font = "bold 11px system-ui, sans-serif";
            ctx.textAlign = "center";

            if (endpoints.length === 2) {
              const [ep1, ep2] = endpoints;
              const closeX = Math.abs(ep1.xPos - ep2.xPos) < 30;
              const closeY = Math.abs(ep1.yPos - ep2.yPos) < 18;
              if (closeX && closeY) {
                const [topEp, botEp] = ep1.yPos <= ep2.yPos ? [ep1, ep2] : [ep2, ep1];

                ctx.fillStyle = topEp.color;
                ctx.textBaseline = "bottom";
                ctx.fillText(topEp.label, topEp.xPos, topEp.yPos - 12);

                ctx.fillStyle = botEp.color;
                ctx.textBaseline = "top";
                ctx.fillText(botEp.label, botEp.xPos, botEp.yPos + 12);

                ctx.restore();
                return;
              }
            }

            endpoints.forEach((ep) => {
              ctx.fillStyle = ep.color;
              ctx.textBaseline = "bottom";
              ctx.fillText(ep.label, ep.xPos, ep.yPos - 12);
            });

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

  const formatSignedPct = (val) =>
    (val > 0 ? "+" : "") +
    (val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)) +
    "%";

  function asymmetryEndpointLabelPlugin() {
    return {
      hooks: {
        draw: [
          (u) => {
            const ctx = u.ctx;
            const endpoints = [];
            for (let sIdx = 1; sIdx < u.series.length; sIdx++) {
              const sData = u.data[sIdx];
              if (!sData || !sData.length) continue;
              let lastIdx = -1;
              for (let i = sData.length - 1; i >= 0; i--) {
                if (sData[i] != null) {
                  lastIdx = i;
                  break;
                }
              }
              if (lastIdx !== -1) {
                const val = sData[lastIdx];
                const xPos = u.valToPos(u.data[0][lastIdx], "x", true);
                const yPos = u.valToPos(val, "y", true);
                endpoints.push({
                  xPos,
                  yPos,
                  val,
                  color: u.series[sIdx].stroke || palette.text,
                });
              }
            }

            if (!endpoints.length) return;

            ctx.save();
            ctx.font = "bold 11px system-ui, sans-serif";
            ctx.textAlign = "center";

            if (endpoints.length === 2) {
              const [ep1, ep2] = endpoints;
              const closeX = Math.abs(ep1.xPos - ep2.xPos) < 30;
              const closeY = Math.abs(ep1.yPos - ep2.yPos) < 18;
              if (closeX && closeY) {
                const [topEp, botEp] = ep1.yPos <= ep2.yPos ? [ep1, ep2] : [ep2, ep1];

                ctx.fillStyle = topEp.color;
                ctx.textBaseline = "bottom";
                ctx.fillText(formatSignedPct(topEp.val), topEp.xPos, topEp.yPos - 12);

                ctx.fillStyle = botEp.color;
                ctx.textBaseline = "top";
                ctx.fillText(formatSignedPct(botEp.val), botEp.xPos, botEp.yPos + 12);

                ctx.restore();
                return;
              }
            }

            endpoints.forEach((ep) => {
              ctx.fillStyle = ep.color;
              ctx.textBaseline = "bottom";
              ctx.fillText(formatSignedPct(ep.val), ep.xPos, ep.yPos - 12);
            });

            ctx.restore();
          },
        ],
      },
    };
  }

  const charts = [];

  // 1. TrainingVolume and Mean Intensity trend charts
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
        if (!target) return;

        const volDates = combo.dates || [];
        const volValues = combo.volumes || [];
        const intensityDates = combo.intensity_dates || [];
        const intensityValues = combo.intensities || [];

        if (!volDates.length && !intensityDates.length) return;

        const volMap = new Map();
        let lastVolTs = -Infinity;
        volDates.forEach((d, i) => {
          let ts = toUnixSeconds(d);
          if (ts <= lastVolTs) {
            ts = lastVolTs + 3600;
          }
          lastVolTs = ts;
          volMap.set(ts, volValues[i]);
        });

        const intensityMap = new Map();
        let lastIntensityTs = -Infinity;
        intensityDates.forEach((d, i) => {
          let ts = toUnixSeconds(d);
          if (ts <= lastIntensityTs) {
            ts = lastIntensityTs + 3600;
          }
          lastIntensityTs = ts;
          intensityMap.set(ts, intensityValues[i]);
        });

        const allTimestamps = Array.from(
          new Set([...volMap.keys(), ...intensityMap.keys()])
        ).sort((a, b) => a - b);

        const seriesOpts = [
          {},
          {
            scale: "y",
            label: "Volume",
            stroke: palette.mark,
            width: 2,
            points: {
              show: true,
              size: 8,
              stroke: palette.pointRing,
              width: 2,
              fill: palette.mark,
            },
            fill: AREA_FILL,
            spanGaps: true,
          },
        ];
        const chartData = [
          allTimestamps,
          allTimestamps.map((t) => (volMap.has(t) ? volMap.get(t) : null)),
        ];

        const hasIntensity = intensityDates.length > 0;
        if (hasIntensity) {
          seriesOpts.push({
            scale: "intensity",
            label: "Mean Intensity",
            stroke: palette.intensityMark,
            width: 2,
            dash: [1, 5],
            points: {
              show: true,
              size: 7,
              stroke: palette.pointRing,
              width: 2,
              fill: palette.intensityMark,
            },
            spanGaps: true,
          });
          chartData.push(
            allTimestamps.map((t) =>
              intensityMap.has(t) ? intensityMap.get(t) : null
            )
          );
        }

        const scalesOpts = {
          x: { time: true },
          y: { auto: true },
        };
        if (hasIntensity) {
          scalesOpts.intensity = {
            auto: true,
            range: (u, dataMin, dataMax) => [
              0,
              Math.max(1.0, dataMax != null ? dataMax + 0.05 : 1.0),
            ],
          };
        }

        const axesOpts = [
          {
            stroke: palette.ink,
            grid: { show: false },
            ticks: { show: false },
            font: "10px system-ui, sans-serif",
          },
          {
            scale: "y",
            side: 3,
            stroke: palette.ink,
            grid: { show: true, stroke: palette.grid, width: 1 },
            ticks: { show: false },
            font: "10px system-ui, sans-serif",
          },
        ];
        if (hasIntensity) {
          axesOpts.push({
            scale: "intensity",
            side: 1,
            stroke: palette.ink,
            grid: { show: false },
            ticks: { show: false },
            font: "10px system-ui, sans-serif",
            values: (u, vals) =>
              vals.map((v) => (v != null ? `${Math.round(v * 100)}%` : "")),
          });
        }

        const opts = {
          width: target.clientWidth || 320,
          height: 220,
          padding: [24, 12, 8, 8],
          scales: scalesOpts,
          cursor: { show: false },
          legend: { show: false },
          series: seriesOpts,
          axes: axesOpts,
          plugins: [trendEndpointLabelPlugin()],
        };

        const chart = new uPlot(opts, chartData, target);
        // Deliberately no root background: the container div is strong glass
        // (app.css) and the map/blur should keep showing through the chart.
        chart.root.style.borderRadius = "10px";
        charts.push({ chart, target });
      });
    }
  }

  // 2. Strength gap and Load gap asymmetry trend charts
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
        if (!target) return;

        const strengthDates = pair.strength_dates || [];
        const strengthGaps = pair.strength_gaps || [];
        const loadDates = pair.load_dates || [];
        const loadGaps = pair.load_gaps || [];

        if (!strengthDates.length && !loadDates.length) return;

        const strengthMap = new Map();
        let lastStrengthTs = -Infinity;
        strengthDates.forEach((d, i) => {
          let ts = toUnixSeconds(d);
          if (ts <= lastStrengthTs) {
            ts = lastStrengthTs + 3600;
          }
          lastStrengthTs = ts;
          strengthMap.set(ts, strengthGaps[i]);
        });

        const loadMap = new Map();
        let lastLoadTs = -Infinity;
        loadDates.forEach((d, i) => {
          let ts = toUnixSeconds(d);
          if (ts <= lastLoadTs) {
            ts = lastLoadTs + 3600;
          }
          lastLoadTs = ts;
          loadMap.set(ts, loadGaps[i]);
        });

        const allTimestamps = Array.from(
          new Set([...strengthMap.keys(), ...loadMap.keys()])
        ).sort((a, b) => a - b);

        const seriesOpts = [{}];
        const chartData = [allTimestamps];

        if (strengthDates.length > 0) {
          seriesOpts.push({
            label: "Strength Gap",
            stroke: palette.mark,
            width: 2,
            points: {
              show: true,
              size: 8,
              stroke: palette.pointRing,
              width: 2,
              fill: palette.mark,
            },
            spanGaps: true,
          });
          chartData.push(
            allTimestamps.map((t) => (strengthMap.has(t) ? strengthMap.get(t) : null))
          );
        }

        if (loadDates.length > 0) {
          seriesOpts.push({
            label: "Load Gap",
            stroke: palette.loadMark,
            width: 2,
            dash: [1, 5],
            points: {
              show: true,
              size: 7,
              stroke: palette.pointRing,
              width: 2,
              fill: palette.loadMark,
            },
            spanGaps: true,
          });
          chartData.push(
            allTimestamps.map((t) => (loadMap.has(t) ? loadMap.get(t) : null))
          );
        }

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
          series: seriesOpts,
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
          plugins: [asymmetryBandsPlugin(), asymmetryEndpointLabelPlugin()],
        };

        const chart = new uPlot(opts, chartData, target);
        // Deliberately no root background: the container div is strong glass
        // (app.css) and the map/blur should keep showing through the chart.
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
