---
version: 1
slug: "dashboard-index-html"
primary_target: "dashboard/index.html"
related_targets: ["dashboard/simulation.html"]
---

# Dashboard surface brief

Scope: `dashboard/index.html` (Overview, Baseline, Scheduling, Mechanism, Evidence) and `dashboard/simulation.html`. Visitor mode: Read.

Audience and job: a recruiter or engineer arriving from a GitHub link, alone on a laptop, a few minutes; must leave knowing what was measured, when deadline-aware dropping helps, and that the numbers are traceable. Constraints: static, offline, no external resources, English default with zh-TW toggle, light and dark schemes, measured and estimated kept apart.

Unresolved: none.

## Direction contract

THESIS: The site is drawn in real-time-scheduling notation (a millisecond axis, release arrows, execution blocks, hatched overruns, a deadline arrow), so the regime boundary reads as a figure. It refuses the analytics-dashboard arrangement of grey page, white cards, stat tiles and pill tabs.

OWN-WORLD: White drafting ground, black ink, square-cornered line art, 45° hatch for estimated or overrun time, heavy ink rules instead of cards. Colour belongs only to policies (Latest blue, Guard orange, Adaptive teal), late red, and the measured / estimate stamps. One typeface family, B612 with B612 Mono for code and hashes. Navigation is a time axis: ticks, labels, a filled arrow on the current view. Controls are joined ink-bordered strips, the selected one filled.

STORY: The visitor reads the question, sees four lanes against one 100 ms deadline, notices only one lane overruns, reads the measured difference beside it, then follows the axis to policies, mechanism and evidence.

FIRST VIEWPORT: Headline top-left at display size with the one-sentence answer beside it; directly below, a full-width inverted ink plate holding the timing diagram: time ruler across the top, one lane per fixed-rate condition (open wait bar, solid service block, red hatched overrun), the deadline arrow crossing all lanes at 100 ms, and at the right of each lane the Deadline-Guard − Latest-Frame difference with its 95% interval and block dots. The primary lane carries dimension lines 50 + 57 = 107 ms. Primary action: the lane itself (trace it), then the three text links under the answer.

SIGNATURE INTERACTION: Trace a lane. Hovering or focusing a lane swaps the dimension lines to that lane and marks its difference row. MOTION: on first load the lanes are drawn left to right along the time axis by a playhead, once; controls and charts otherwise change state without choreography; reduced motion shows the finished figure.

FORM: Timing Diagram, position 1 of 7 on the ordered grounded list, chosen by the user over the rolled direction; seed key a5e96e23; code-led (no image generation available).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
