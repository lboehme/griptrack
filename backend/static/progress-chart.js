// Progress headline chart (issue #150): CurrentMax as % of bodyweight per
// hand, drawn as step lines, with boulder sends as grade-coloured dots on a
// second (grade) axis. Fed by the JSON-in-DOM payload #progress-chart-data
// (backend/progress.py), same idiom as dashboard-chart.js.
//
// Marks follow docs/ui-review-2026-09.md V2/V7: Left is a solid 2.5px
// accent line, Right a dotted chalk line (so the hands differ by more than
// colour), last point marked with a dot, hairline grid in --line, axis text
// in --mu. Every colour is read from app.css's custom properties at
// runtime -- the send dots resolve each grade band's token by name.
//
// The range/combo pickers swap #progress-root via htmx, so drawing runs on
// first load, on every htmx:load of new content, and after a history
// restore (the cached snapshot keeps an empty canvas).
// Requires uPlot vendored at /static/uplot.iife.min.js.
(function () {
  let current = null;

  function token(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function toUnixSeconds(isoDate) {
    return Math.floor(new Date(isoDate + "T00:00:00Z").getTime() / 1000);
  }

  function lastIndex(values) {
    for (let i = values.length - 1; i >= 0; i--) {
      if (values[i] != null) return i;
    }
    return -1;
  }

  function draw() {
    if (typeof uPlot === "undefined") return;
    const target = document.querySelector("[data-progress-chart]");
    const dataEl = document.getElementById("progress-chart-data");
    if (!target || !dataEl) return;

    let payload;
    try {
      payload = JSON.parse(dataEl.textContent);
    } catch (e) {
      return;
    }
    if (current) {
      current.chart.destroy();
      current = null;
    }
    target.innerHTML = "";

    const hands = payload.hands || {};
    const left = hands.left || { dates: [], values: [] };
    const right = hands.right || { dates: [], values: [] };
    const sends = payload.sends || [];
    if (!left.dates.length && !right.dates.length && !sends.length) return;

    const palette = {
      left: token("--acc", "currentColor"),
      right: token("--tx", "currentColor"),
      ink: token("--mu", "currentColor"),
      grid: token("--line", "currentColor"),
      ring: token("--s1", "currentColor"),
    };

    const leftMap = new Map(left.dates.map((d, i) => [toUnixSeconds(d), left.values[i]]));
    const rightMap = new Map(right.dates.map((d, i) => [toUnixSeconds(d), right.values[i]]));
    // Two sends on one day share an x; nudge later ones by an hour so each
    // keeps its own dot (same trick as dashboard-chart.js).
    const sendPoints = [];
    let lastSendTs = -Infinity;
    sends.forEach((s) => {
      let ts = toUnixSeconds(s.date);
      if (ts <= lastSendTs) ts = lastSendTs + 3600;
      lastSendTs = ts;
      sendPoints.push({ ts, value: s.value, grade: s.grade, color: token(s.token, palette.ink) });
    });
    const sendMap = new Map(sendPoints.map((p) => [p.ts, p.value]));

    const xs = Array.from(
      new Set([...leftMap.keys(), ...rightMap.keys(), ...sendMap.keys()])
    ).sort((a, b) => a - b);
    const data = [
      xs,
      xs.map((t) => (leftMap.has(t) ? leftMap.get(t) : null)),
      xs.map((t) => (rightMap.has(t) ? rightMap.get(t) : null)),
      xs.map((t) => (sendMap.has(t) ? sendMap.get(t) : null)),
    ];

    const gradeLabels = new Map();
    sends.forEach((s) => {
      if (!gradeLabels.has(s.value)) gradeLabels.set(s.value, s.grade);
    });

    const stepped = uPlot.paths && uPlot.paths.stepped ? uPlot.paths.stepped({ align: 1 }) : undefined;
    const xMin = payload.since ? toUnixSeconds(payload.since) : xs[0];
    const xMax = Math.max(toUnixSeconds(payload.today), xs[xs.length - 1]);

    // Last point per hand, and every send, drawn as dots in one hook: uPlot
    // can't colour points individually, and only the endpoints get a dot.
    const dotsPlugin = {
      hooks: {
        draw: [
          (u) => {
            const ctx = u.ctx;
            const dpr = window.devicePixelRatio || 1;
            ctx.save();
            [1, 2].forEach((sIdx) => {
              const i = lastIndex(u.data[sIdx]);
              if (i === -1) return;
              const x = u.valToPos(u.data[0][i], "x", true);
              const y = u.valToPos(u.data[sIdx][i], "pct", true);
              ctx.beginPath();
              ctx.arc(x, y, 4.5 * dpr, 0, 2 * Math.PI);
              ctx.fillStyle = sIdx === 1 ? palette.left : palette.right;
              ctx.strokeStyle = palette.ring;
              ctx.lineWidth = 2 * dpr;
              ctx.fill();
              ctx.stroke();
            });
            sendPoints.forEach((p) => {
              const x = u.valToPos(p.ts, "x", true);
              const y = u.valToPos(p.value, "grade", true);
              ctx.beginPath();
              ctx.arc(x, y, 4 * dpr, 0, 2 * Math.PI);
              ctx.fillStyle = p.color;
              ctx.fill();
            });
            ctx.restore();
          },
        ],
      },
    };

    const gradeValues = sends.map((s) => s.value);
    const opts = {
      width: target.clientWidth || 320,
      height: 200,
      padding: [12, 8, 4, 4],
      cursor: { show: false },
      legend: { show: false },
      scales: {
        x: { time: true, range: () => [xMin, xMax] },
        pct: {
          range: (u, min, max) => {
            if (min == null || max == null) return [0, 1];
            const pad = Math.max((max - min) * 0.2, 0.02);
            return [Math.max(0, min - pad), max + pad];
          },
        },
        grade: {
          range: () =>
            gradeValues.length
              ? [Math.min(...gradeValues) - 1, Math.max(...gradeValues) + 1]
              : [0, 1],
        },
      },
      series: [
        {},
        {
          label: "Left",
          scale: "pct",
          stroke: palette.left,
          width: 2.5,
          paths: stepped,
          points: { show: false },
          spanGaps: true,
        },
        {
          label: "Right",
          scale: "pct",
          stroke: palette.right,
          width: 2,
          dash: [1, 5],
          cap: "round",
          paths: stepped,
          points: { show: false },
          spanGaps: true,
        },
        {
          label: "Sends",
          scale: "grade",
          stroke: "transparent",
          width: 0,
          paths: () => null,
          points: { show: false },
        },
      ],
      axes: [
        {
          stroke: palette.ink,
          grid: { show: false },
          ticks: { show: false },
          font: "600 10px Barlow, system-ui, sans-serif",
        },
        {
          scale: "pct",
          stroke: palette.ink,
          grid: { show: true, stroke: palette.grid, width: 1 },
          ticks: { show: false },
          font: "600 10px Barlow, system-ui, sans-serif",
          size: 40,
          values: (u, vals) => vals.map((v) => (v == null ? "" : Math.round(v * 100) + "%")),
        },
        {
          scale: "grade",
          side: 1,
          stroke: palette.ink,
          grid: { show: false },
          ticks: { show: false },
          font: "600 10px Barlow, system-ui, sans-serif",
          size: 36,
          splits: () => Array.from(gradeLabels.keys()).sort((a, b) => a - b),
          values: (u, vals) => vals.map((v) => gradeLabels.get(v) || ""),
        },
      ],
      plugins: [dotsPlugin],
    };

    const chart = new uPlot(opts, data, target);
    current = { chart, target };
  }

  window.addEventListener("resize", () => {
    if (current) {
      current.chart.setSize({ width: current.target.clientWidth || 320, height: 200 });
    }
  });
  document.addEventListener("DOMContentLoaded", draw);
  document.addEventListener("htmx:load", (event) => {
    const el = event.target;
    if (el && el.querySelector && (el.matches("#progress-root") || el.querySelector("#progress-root"))) draw();
  });
  document.addEventListener("htmx:historyRestore", draw);
})();
