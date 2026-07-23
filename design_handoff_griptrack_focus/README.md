# Handoff: GripTrack — "Focus" work-sets screen (concept 1c)

## Overview
GripTrack is a hangboard / finger-strength training app for climbers. This handoff covers the **Work sets** screen of a live session — where the climber logs each set (weight, reps, RPE) for the left and right hand. The chosen direction is the **"Focus"** concept (labelled `1c` in the prototype): instead of a dense table, it shows **one set at a time** using large tap-to-adjust steppers rather than a keyboard, so the user can log a set one-handed between hangs.

The recent change: the screen now shows **both hands on screen at once** — two stacked cards (Left hand above, Right hand below), each with its own weight / reps / RPE controls — followed by a single "Set done" button that advances both.

## About the design files
The files in this bundle are **design references created in HTML** — prototypes showing the intended look and behavior. They are **not production code to copy directly**. The prototype uses a small in-house HTML component runtime (`support.js`, `<x-dc>`, `<sc-for>`, `<x-import>`) that is only for previewing — **do not port that runtime.**

Your task is to **recreate this screen in the target codebase's existing environment** (React Native, SwiftUI, Flutter, React web, etc.) using its established components, navigation, and styling patterns. If no environment exists yet, pick the framework best suited to the app (this is a mobile-first product) and implement it there. Treat the HTML as the spec for layout, spacing, color, type, and behavior — not as source to transpile.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and radii are final and listed exactly below. Recreate the UI pixel-accurately, then wire it to real data and the codebase's design system. The prototype is a static mock — steppers, chips, and buttons are not yet interactive; the interaction spec below defines how they should behave.

## Screen: Work sets (Focus)

### Layout (top to bottom)
Mobile screen, single column. Design width 390pt (rendered in a 402px iOS bezel). Three regions:

1. **Header** — padding `64px 22px 0`.
   - Row: exercise title (left) + progress pill (right), space-between, vertically centered.
   - Segmented progress bar below (6 segments, `gap: 5px`, each `flex:1`, `height: 4px`, `border-radius: 2px`), `margin-top: 12px`. Completed segments filled accent, current segment mid-tint, remaining light-tint.
2. **Scrollable body** — `flex: 1`, padding `18px 22px 26px`.
   - **Two hand cards**, stacked in a `flex column` with `gap: 12px`.
   - **"Set done" button** as the last child of that same column (so it sits directly under the second card with the same 12px gap).
   - **Completed section** below, `margin-top: 22px`.
3. **Tab bar** — sticky bottom, `height: 62px`, 5 tabs, frosted white.

### Components

**Exercise title** — "Half crimp · 20 mm", 15px / weight 700 / letter-spacing -0.01em / color `#241f33`.

**Progress pill** — text "Set 3 of 6", 12px / 700, color `#5b4b8a`, background `#eae5f4`, padding `4px 11px`, border-radius 999px.

**Progress bar segments** — filled `#5b4b8a`; current `#cfc6e2`; remaining `#e4dff0`.

**Hand card** (repeated for Left and Right):
- Container: background `#ffffff`, border-radius 20px, padding `16px 20px 18px`, shadow `0 2px 16px -6px rgba(36,31,51,.14)`.
- **Card header row** (`flex`, `gap: 8px`, centered):
  - Hand badge: 24×24, border-radius 7px, `display:grid; place-content:center`, white text 12px / 800. Left badge fill `#5b4b8a` (text "L"); Right badge fill `#8577b0` (text "R").
  - Hand label: "Left hand" / "Right hand", 14px / 700.
- **Weight stepper row** (`flex`, centered, `gap: 18px`, `margin-top: 10px`):
  - Minus button: 46×46 circle, `border: 2px solid #ded7ec`, glyph "−" 24px, color `#5b4b8a`, weight 600.
  - Center: weight value **42px / 800**, letter-spacing -0.04em, tabular-nums, line-height 1 (Left "32.5", Right "30.0"); caption below "kg · plate-loadable" 12px, color `#7a7194`, `margin-top: 3px`.
  - Plus button: identical to minus, glyph "＋".
  - *(Note: weight was reduced from 56px to 42px so two cards fit on one screen.)*
- **Reps + RPE row** (`display:grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 16px`):
  - **REPS** column — label "REPS" 11px / 700 / letter-spacing 0.14em / `#7a7194`, centered. Below: minus/plus circles 32×32 (`border: 2px solid #ded7ec`, glyph 17px `#5b4b8a`) flanking value 23px / 800 tabular-nums, `gap: 12px`, `margin-top: 6px`.
  - **RPE** column — label "RPE" same style. Below: three chips (`7`, `8`, `9`), `gap: 6px`, `margin-top: 9px`, each padding `6px 10px`, border-radius 8px, 13px / 700. Unselected: background `#f1eef7`, text `#7a7194`. Selected (`8`): background `#5b4b8a`, text `#fff`.

**"Set done" button** — `height: 56px`, border-radius 16px, background `#5b4b8a`, white text "Set done — rest 3:00", 17px / 800, letter-spacing -0.01em, centered.

**Completed section**:
- Heading "COMPLETED" — 12px / 700 / letter-spacing 0.14em / `#7a7194`, `margin-bottom: 8px`.
- Completed row (repeated): `flex`, `gap: 12px`, padding `10px 14px`, background `#ffffff`, border-radius 12px, `margin-bottom: 6px`. Contents: 22×22 accent circle (`#5b4b8a`) with white check icon; "Set N" 14px / 700; detail (e.g. "32.5 kg × 5 @ 8") pushed right (`margin-left: auto`), 14px, color `#7a7194`, tabular-nums.
- Up-next row: padding `10px 14px`, `border: 1.5px dashed #cfc6e2`, border-radius 12px, color `#7a7194`, 14px, text "Sets 4–6 up next · same load carries down".

**Tab bar** — sticky bottom, `height: 62px`, background `rgba(255,255,255,.9)`, `backdrop-filter: blur(14px)`, `border-top: 1px solid #e4dff0`, `padding-bottom: 12px`. 5 equal tabs (`flex:1`), each a column (`gap: 3px`) with a 20×20 glyph + 10.5px / 700 label. Active tab is **Session** (color `#5b4b8a`, filled glyph); others `#7a7194`, outline glyph. Tabs: Home, Session, Trends, Climbs, Profile.

## Interactions & behavior
- **Weight steppers**: −/＋ adjust that hand's weight independently. Increment should snap to plate-loadable values (caption implies this) — confirm the real increment with the team (e.g. 2.5 kg or 0.5 kg on a pulley). Each hand is independent (Left and Right can differ, e.g. 32.5 vs 30.0).
- **Reps steppers**: −/＋ adjust reps, min 0, integer.
- **RPE chips**: single-select per hand; tapping a chip sets that hand's RPE (7 / 8 / 9 shown; consider a wider range or half-steps to match the data, which uses 8.5, 7.5).
- **Set done — rest 3:00**: commits both hands' current values as the next completed set, appends a row to COMPLETED, advances the progress bar/pill (Set N → N+1), and starts a 3:00 rest timer. Load carries down to the next set by default ("same load carries down").
- **Autosave**: edits persist immediately (matches the current app's "edits save automatically" behavior).
- **Rest timer**: the "rest 3:00" label implies a countdown after committing a set — confirm whether it counts down inline on the button, as a banner, or a separate timer UI.
- No hover states (touch product). Provide pressed/active feedback on all steppers, chips, and buttons per the platform's conventions. Touch targets: steppers are 46 and 32px — keep the 32px reps/plus targets ≥44px effective hit area with padding.

## State
Per screen (one exercise, one session):
- `exercise` — name + edge (e.g. "Half crimp", "20 mm").
- `totalSets`, `currentSetIndex` (drives pill + progress bar).
- `hands: { left, right }`, each `{ weight, reps, rpe }` — the in-progress set's editable values.
- `completedSets: [{ n, left:{kg,reps,rpe}, right:{kg,reps,rpe} }]`.
- `restTimer` — running / remaining seconds after a set is committed.
- Committing (`Set done`) pushes the current `hands` into `completedSets`, increments `currentSetIndex`, seeds the next `hands` from the last set, and starts `restTimer`.

## Design tokens
Colors:
- Accent / primary: `#5b4b8a` (purple)
- Accent light (right-hand badge): `#8577b0`
- Text primary: `#241f33`
- Text secondary / muted: `#7a7194`
- Screen background: `#f6f4f9`
- Card / surface: `#ffffff`
- Pill background: `#eae5f4`
- Chip background (unselected): `#f1eef7`
- Stepper border: `#ded7ec`
- Progress: filled `#5b4b8a`, current `#cfc6e2`, remaining `#e4dff0`
- Dashed/up-next border: `#cfc6e2`
- Tab-bar top border: `#e4dff0`

Typography — system sans (`-apple-system` / Helvetica in the mock; use the platform system font). Scale used on this screen: 42 (weight value), 23 (reps value), 17 (primary button), 15 (title), 14 (labels/rows), 13 (RPE chip), 12 (caption/pill), 11 (field labels), 10.5 (tab label). Weights: 800 for numerals/buttons, 700 for labels/titles, 600 for stepper glyphs. `font-variant-numeric: tabular-nums` on all numeric values. Letter-spacing: -0.04em on the big weight, 0.14em on uppercase field labels.

Radii: 20 (card), 16 (primary button), 12 (completed row / dashed row), 8 (RPE chip), 7 (hand badge), 999 (stepper circles, pill).

Shadow: card `0 2px 16px -6px rgba(36,31,51,.14)`.

Spacing rhythm: card gap 12; header→body 18; body→completed 22; grid gaps 14; stepper gaps 18/12.

## Assets
No image assets. Icons are inline SVG:
- Check mark (completed rows): `<path d="M4 12.5 9.5 18 20 6.5">`, stroke-width 3.5, round caps.
- Tab glyphs are simple CSS boxes/circles in the mock — replace with the codebase's real icon set (home, session/bolt, trends/chart, climbs/mountain, profile).

## Files in this bundle
- `Griptrack Concepts.dc.html` — full prototype. **Concept `1c` (the `#1c` block, labelled "Focus")** is the target screen. The file also contains the current design (`1a`) and four alternate concepts (`1b`, `1d`–`1f`) for context only — ignore them unless you want reference.
- `ios-frame.jsx` — the iOS bezel used to frame the mock in the prototype. **Preview chrome only — do not port.**

## Viewing the prototype
The HTML uses a preview runtime and does not render as a plain file open. To see it as intended, view it in the design tool it was authored in. The token/measurement spec above is self-sufficient for implementation without running the file.
