---
name: OS-Aware Edge AI Runtime
description: Measured ROS 2 frame-scheduling results drawn in real-time-scheduling notation.
colors:
  drafting-white: "#ffffff"
  rule-grey-wash: "#f0f1f3"
  ink: "#0e1013"
  ink-2: "#3a3f47"
  ink-3: "#575d67"
  tick-grey: "#646a74"
  grid-hairline: "#e6e8eb"
  axis-grey: "#b4bac2"
  focus-blue: "#1f5fd0"
  latest-blue: "#2a78d6"
  guard-orange: "#e8612b"
  adaptive-teal: "#159a6b"
  arm-grey-4: "#3a3f47"
  arm-grey-5: "#6e747e"
  arm-grey-6: "#8b919a"
  status-green: "#0c8f2e"
  measured-ink: "#0b6b2a"
  measured-wash: "#e9f5ec"
  measured-border: "#8cc29b"
  late-red: "#d03b3b"
  late-red-ink: "#b3261e"
  estimate-ink: "#7d5200"
  estimate-wash: "#fbf3e2"
  estimate-border: "#d9b76a"
  estimate-1: "#7a5200"
  estimate-2: "#a87523"
  estimate-3: "#a08a62"
  model-s: "#3a3f47"
  model-xxs: "#8a919b"
  plate-ink-ground: "#0e1013"
  plate-ink-ground-2: "#1b1e23"
  plate-line-white: "#f4f5f7"
  dark-paper: "#0c0e11"
  dark-ink: "#eef0f2"
typography:
  display:
    fontFamily: "B612, system-ui, -apple-system, Segoe UI, PingFang TC, Noto Sans TC, Microsoft JhengHei, sans-serif"
    fontSize: "58px"
    fontWeight: 700
    lineHeight: 1.04
    letterSpacing: "-0.028em"
  headline:
    fontFamily: "B612, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "B612, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  title-sm:
    fontFamily: "B612, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  body:
    fontFamily: "B612, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "\"kern\""
  body-sm:
    fontFamily: "B612, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "B612, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.45
  caption:
    fontFamily: "B612, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "\"tnum\""
  mono:
    fontFamily: "B612 Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.65
rounded:
  none: "0px"
  hair: "2px"
spacing:
  sp-1: "4px"
  sp-2: "8px"
  sp-3: "12px"
  sp-4: "16px"
  sp-5: "24px"
  sp-6: "32px"
  sp-7: "48px"
  sp-8: "64px"
  sp-9: "88px"
  gutter: "32px"
  column-gap: "40px"
  max-width: "1240px"
components:
  segment-button:
    backgroundColor: "{colors.drafting-white}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.none}"
    padding: "0 13px"
    height: "36px"
  segment-button-hover:
    backgroundColor: "{colors.rule-grey-wash}"
  segment-button-active:
    backgroundColor: "{colors.axis-grey}"
  segment-button-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.drafting-white}"
  language-toggle:
    backgroundColor: "{colors.drafting-white}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 10px"
    height: "30px"
  language-toggle-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.drafting-white}"
  stamp-measured:
    backgroundColor: "{colors.measured-wash}"
    textColor: "{colors.measured-ink}"
    typography: "{typography.caption}"
    rounded: "{rounded.hair}"
    padding: "3px 9px"
  stamp-estimate:
    backgroundColor: "{colors.estimate-wash}"
    textColor: "{colors.estimate-ink}"
    typography: "{typography.caption}"
    rounded: "{rounded.hair}"
    padding: "3px 9px"
  stamp-neutral:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.caption}"
    rounded: "{rounded.hair}"
    padding: "3px 9px"
  callout-estimate:
    backgroundColor: "{colors.estimate-wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.hair}"
    padding: "12px 16px"
  nav-tick:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    typography: "{typography.body-sm}"
    padding: "13px 22px 11px 10px"
  nav-tick-current:
    textColor: "{colors.ink}"
  tooltip:
    backgroundColor: "{colors.drafting-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.hair}"
    padding: "9px 11px"
  ink-plate:
    backgroundColor: "{colors.plate-ink-ground}"
    textColor: "{colors.plate-line-white}"
    rounded: "{rounded.none}"
    padding: "24px 0 32px"
---

# Design System: OS-Aware Edge AI Runtime

## Overview

**Creative North Star: "The Timing Diagram"**

The whole site is drawn in real-time-scheduling notation: a millisecond axis, release arrows at t = 0, execution blocks, hatched overruns and a dashed deadline with a down arrowhead. The result the project exists to show, a regime boundary, reads as a figure rather than as a stat. The page is a white drafting ground carrying black ink; figures sit on the page between heavy ink rules instead of inside cards, and the one lead figure is an inverted ink plate (white line art on black) that runs edge to edge.

Density is that of a technical paper set for the screen: one family (B612, the cockpit-display face) at a short, deliberate ramp, tabular numerals for every number, square corners everywhere except a 2 px hair on small stamps. Colour is owned, not decorative: three hues belong to three scheduling policies, red belongs to time past the deadline, green and amber are the two stamps that say what kind of number you are looking at. Everything else is ink and grey. The world rejects the analytics-dashboard arrangement of grey page, white cards, stat tiles and pill tabs.

Navigation is itself a time axis (ticks per view, a filled arrowhead on the current one) and controls are joined ink-bordered strips with the selected cell filled. Motion is a single event: a playhead draws the lead diagram once on first load; everything else changes state without choreography.

**Key Characteristics:**
- White drafting ground, black ink, square-cornered line art.
- Heavy 2 px ink rules divide figures and sections; no cards, no boxes around charts.
- One inverted ink plate per page at most, for the lead figure, redefining the same tokens locally.
- Colour ownership: policy hues, late red, measured green, estimate amber; nothing else is coloured.
- One type family (B612 + B612 Mono), bold for hierarchy, tabular numerals for data.
- Notation is consistent everywhere: open bar = waiting, solid = measured service, hatch = past deadline or estimated, dashed arrow line = the deadline.

## Colors

An ink-on-white drafting palette with a tightly owned set of signal colours; dark mode inverts the ground and lifts every signal to hold contrast.

### Primary
- **Drafting Ink** (ink): text, rules, axes, solid service blocks, the selected segment, the release and deadline arrows. The page is carried by this one colour.

### Secondary
- **Latest Blue** (latest-blue): the Latest-Frame policy, and only that policy, in every chart, legend and swatch.
- **Guard Orange** (guard-orange): the Deadline-Guard policy only.
- **Adaptive Teal** (adaptive-teal): the Adaptive policy only.

### Tertiary
- **Late Red** (late-red, with late-red-ink for text): time or frames past the deadline, drawn as a 45° hatch with a solid outline; red value labels for late lanes; the failed-check cross.
- **Measured Green** (measured-wash / measured-border / measured-ink; status-green for check icons): the "Measured" stamp and passing verification marks.
- **Estimate Amber** (estimate-wash / estimate-border / estimate-ink, and the three-step series family estimate-1..3): everything from the EDA-Lite simulator: stamps, the estimates callout, simulation chart series.

### Neutral
- **Drafting White** (drafting-white): page and chart ground; also the knock-out halo behind chart labels.
- **Rule Grey Wash** (rule-grey-wash): code background, segment hover, highlighted table row.
- **Ink 2 / Ink 3** (ink-2, ink-3): secondary text, figure subtitles, notes; wait-bar outlines and estimated hatch use ink-2.
- **Tick Grey** (tick-grey): 12 px tick labels (kept at 4.5:1 on white and on the wash).
- **Grid Hairline** (grid-hairline) and **Axis Grey** (axis-grey): gridlines; lane baselines, link underlines, list markers.
- **Arm Greys** (arm-grey-4..6): FIFO and the two legacy arms; they are compared, never highlighted.
- **Model Greys** (model-s, model-xxs): the two MobileViT models on the baseline page, distinguished by weight of grey.
- **Focus Blue** (focus-blue): keyboard focus outline only.
- Borders are translucent ink: 14 % for hairlines, 34 % for stamp and callout outlines.

### Dark mode and the plate
Under `prefers-color-scheme: dark` the ground becomes near-black (dark-paper), ink becomes dark-ink, the policy hues and signals lift (Latest #4a96f0, Guard #f0703a, Adaptive #2bb585, late #f0625a, estimate #ecbc62) and arm greys invert their order. The ink plate redefines the same token names locally (plate-ink-ground, plate-ink-ground-2, plate-line-white, with brighter policy hues and late red), so every chart drawn inside it is the same code read as white line art on black. In dark mode the plate inverts the other way: it takes the light-mode tokens and policy hues and becomes a white drafting sheet with black ink on the dark page, so the scheme change inverts the plate instead of erasing it (a dark plate on a dark page had a 1.09:1 ground contrast). Dark stamp tokens: measured #12281a / #2f6b40 / #5fd07c, estimate #2a2212 / #6f551c / #ecbc62. Print forces the plate back to black on white.

### Named Rules
**The Colour Ownership Rule.** Latest blue, Guard orange and Adaptive teal belong to those three policies only; FIFO and legacy arms are grey. Never use a policy hue for decoration, a heading, a link or a UI state.

**The Late Is Red Rule.** Red means "past the deadline" (or a failed check) and nothing else, always as hatch plus outline so it survives without colour vision.

**The Two Voices Rule.** Measured numbers carry the green stamp; simulator estimates carry amber, in stamps, callouts and every estimate series. The two never share a figure or a colour.

## Typography

**Display Font:** B612 (with system-ui, then PingFang TC / Noto Sans TC / Microsoft JhengHei for Chinese)
**Body Font:** B612
**Label/Mono Font:** B612 Mono (with ui-monospace, SFMono-Regular, Menlo) for code, commands and hashes

**Character:** A cockpit-instrument face, designed for legibility on displays, used for everything; hierarchy comes from size and bold only. Self-hosted woff2 (OFL), no other families; Chinese text falls back to system fonts.

### Hierarchy
- **Display** (700, 58px, 1.04, -0.028em): the overview question only. Steps to 46px at ≤1100px and on short laptop screens (≥961px wide, ≤860px tall, so all four lanes fit the first viewport at 1280 × 720), 34px at ≤720px.
- **Headline** (700, 40px, 1.1, -0.02em): each view's heading, balanced, max 22em. 34px at ≤1100px, 28px at ≤720px.
- **Title** (700, 26px, -0.015em): section heads and plate headings. 22px at ≤720px.
- **Title Small** (700, 20px, 1.25): figure titles; also the one-sentence answer lead in the hero.
- **Body** (400, 16px, 1.6): running text, kept to `--measure` (36em, about 70 B612 characters); secondary prose at 15px (`--fs-prose`). Notes, captions and figure subtitles at 13–14px are capped at `--measure-note` (40em, about 80 characters). Measures are set in em, not ch: B612's "0" is 1.3× its average glyph, so a ch cap admits about 30% more characters than it states.
- **Body Small** (400, 14px): figure subtitles, controls, nav labels, table toggles.
- **Label** (700, 13px): control labels, legends, table body text (13px regular).
- **Caption** (12px): stamps (bold), table headers (bold), chart ticks and axis titles; tabular numerals.
- **Mono** (13px/1.65 in command blocks, 0.86em inline).

### Named Rules
**The One Family Rule.** B612 for everything, B612 Mono for code and hashes. No second display face, no system display stack standing in for it.

**The Tabular Numbers Rule.** Every number on a chart, table, spec list or tooltip uses tabular numerals so columns of values align.

## Layout

A 12-column grid, 40 px column gap, 1240 px maximum, 32 px page gutter (16 px at ≤720px). Views are a vertical column of sections: each section opens with a 2 px ink rule, the heading at left (5/12) and its one-line purpose at right (7/12). Figures take span-12, 8/4, 7/5 or 6/6 and sit 64 px apart vertically. The ink plate breaks the column and runs edge to edge with its content re-centred inside.

Spacing follows 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 88 px; sections are 88 px apart (64 px on phones), figure groups 64 px. Text is left-aligned throughout; blocks with their own max width stay left-aligned rather than centred.

Breakpoints: ≤1100px tightens the display sizes; ≤960px collapses every grid (hero, plate foot, section head, spec list) to one column; ≤720px turns the nav into a vertical axis behind a toggle, stacks controls, raises touch targets to 40–44px. The header is sticky; anchors scroll with 124px padding (96px on phones).

## Elevation & Depth

Flat. Depth is conveyed by ink weight (2 px rules over 1 px hairlines), the inverted plate, and translucent ink washes (4–7 %) for hover and traced-row bands. The one shadow in the system belongs to the floating tooltip, which genuinely sits above the page.

### Shadow Vocabulary
- **Pop** (`box-shadow: 0 10px 28px rgba(14,16,19,0.16), 0 2px 5px rgba(14,16,19,0.08)`; dark: `0 12px 32px rgba(0,0,0,0.6), 0 2px 6px rgba(0,0,0,0.5)`): the chart tooltip only.

### Named Rules
**The Ruled Not Boxed Rule.** A figure is ruled off above with a 2 px ink line and never placed inside a card, panel or shadowed box. The only filled boxes are the estimate callout and stamps.

## Shapes

Square. Buttons, segments, the language toggle, the nav toggle and the plate have 0 radius; stamps, callouts, code, tooltips and the skip link take a 2 px hair. Strokes are 1–1.5 px line art; arrowheads (release ▲, deadline ▼, current-view ▼, nav ▶ on mobile) are drawn shapes via clip-path or SVG, not glyphs. The 45° hatch (2 px stroke on a 5–6 px pitch) is the system's one texture. Icons are small authored SVGs (arrow, check, cross, chevron) drawn at a 2 px stroke in currentColor.

## Components

### Buttons (segmented controls)
Joined ink strips: tactile, flat, unmistakably selected.
- **Shape:** square cells (0), 1 px ink border, cells overlap by 1 px so borders join.
- **Default:** white ground, ink text, 14px, 36px tall (40px on phones), 0 13px padding.
- **Hover / Active:** wash grey / axis grey fill; **Selected:** filled ink, white text (`aria-pressed`).
- **Focus:** 2 px focus-blue outline, offset 3px, raised above neighbours. Arrow keys move between cells.
- **Language toggle:** a single ink-bordered square cell (min 48×30) that inverts to ink on hover.

### Chips (stamps)
- **Style:** 12px bold, 3px 9px, 2 px radius, 1 px border. Measured: green wash / border / ink. Estimate: amber wash / border / ink. Neutral ("Concept illustration"): no fill, 34 % ink border, ink-2 text.
- **Use:** says what kind of number a figure or page holds; always placed in the figure head or page header, never as a decoration. Every measured figure carries its own stamp, so on phones (≤720px) the header stamp is dropped to keep the header to one row.

### Cards / Containers
- There are no cards. Figures are ruled (2 px ink top rule, 16 px padding-top). The **estimate callout** is the one bordered box: amber wash, amber border, 2 px radius, 12px 16px padding.
- **Ink plate:** full-bleed black band, 24px top / 32px bottom padding, tokens redefined locally; its foot is split 7/5 by a hairline.

### Navigation
- **Style:** a 2 px ink axis under the title block; each view is a tick (2 px × 13 px, scaled to 54 % at rest, full on hover) with a 14px label in ink-3.
- **Current:** a filled downward arrowhead on the axis and ink text.
- **Mobile:** the axis turns vertical on the left behind an ink toggle with a chevron; ticks become horizontal, the current view gets a right-pointing arrowhead; 44px rows.

### Key-measurement list
A two-column definition list ruled by a 1 px ink top line and hairline row separators: bold label left, 20px bold tabular value right with a 13px regular unit (amber `--est` on the simulation page, never the measured ink), a 13px ink-3 detail line beneath. Replaces stat tiles.

### Tables
1 px ink rules top and bottom of the wrap, ink rule under the header row, hairline rows, right-aligned tabular numbers with the first column left. Wide tables scroll inside the wrap with a 56 px right-edge fade until scrolled to the end. Long tables collapse behind a chevron `details` toggle.

### Timing diagram (signature)
One lane per condition against a shared millisecond ruler: release arrow at t = 0, open bar for waiting / frame age, solid block for measured service, red hatch with outline for time past the deadline, a dashed deadline line with a down arrowhead crossing all lanes, value labels haloed in the ground colour. The traced (primary) lane's difference is set at 20px bold with its 95% interval beneath it; a degenerate interval at 0 is labelled "no misses under either policy" instead of reading as no effect. Dimension lines (e.g. 50 ms wait + 57 ms service) sit under the traced lane. Hovering or focusing a lane (or one of its block dots) moves the dimension lines and the 7 % trace band to it. Lanes are focusable in row order and the keyboard enters on the traced lane; hover shows no tooltip (every number is drawn), keyboard focus does. Ticks and labels are hidden from screen readers; the labelled marks carry the numbers. The legend and a one-line key to ρ, pp and block sit directly under the figure. On first load only, a playhead draws the lanes left to right; under `prefers-reduced-motion` the finished figure is shown.

### Chart notation (all charts)
Gridlines in grid-hairline, zero and baseline in 1.25 px ink, 12px tick labels in tick-grey; dot rows show one dot per run with a mean tick and min–max line; forest plots show mean of block differences, 95 % t-interval and open block circles; ring marks get a 2 px ground-colour knock-out. Only marks carrying a tooltip take the pointer.

## Do's and Don'ts

### Do:
- **Do** separate figures and sections with a 2 px ink rule and let them sit on the white ground.
- **Do** draw the deadline as a 1.5 px dashed line (4 3) with a down arrowhead, the same mark in every chart.
- **Do** draw past-the-deadline time as a 45° red hatch with a solid red outline; estimated service in the concept figure as an ink hatch.
- **Do** reserve latest-blue, guard-orange and adaptive-teal for their three policies and grey (arm-grey-4..6) for FIFO and legacy arms.
- **Do** stamp every measured figure green and every simulator figure amber.
- **Do** use tabular numerals and halo chart labels with a 4 px stroke in the ground colour.
- **Do** keep controls as joined, square, ink-bordered segments with the selected cell filled.
- **Do** keep motion to the one-time playhead and short (.15–.2s) state transitions on `cubic-bezier(0.16, 1, 0.3, 1)`; honour reduced motion.

### Don't:
- **Don't** put figures in cards, add a grey page behind white panels, or build stat tiles.
- **Don't** round controls into pills or tabs; corners stay square (stamps and callouts at 2 px).
- **Don't** use a policy hue, red or amber for decoration, emphasis or links.
- **Don't** let a simulation estimate share a figure, stamp or colour with a measured result.
- **Don't** add a second typeface, or substitute system display fonts for B612.
- **Don't** add drop shadows outside the floating tooltip.
- **Don't** use text glyphs as icons or arrowheads; draw them as SVG or clip-path shapes.
