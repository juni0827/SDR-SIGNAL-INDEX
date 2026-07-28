# Dashboard information architecture

The dashboard is the operator's command deck, not a smaller copy of every
screen. It concentrates information that changes an immediate collection,
review, or investigation decision.

| Dashboard block | Merged operational information | Detail screen kept for |
|---|---|---|
| Operator queue | unreviewed segments, failed pipeline jobs, automation blockers, active hypotheses | audio correction, retry diagnostics, full notebook editing |
| Activity radar | seven-day activity pulse and active duration | timeline zoom, period overlay, delta calculation, layer filters |
| Live index | ten newest sessions | structured search, similarity, session evidence |
| Frequency focus | current watchlist and its labels/modes | full-band heatmap, date/mode/receiver filtering, tuning links |
| Autonomous collection | worker/scheduler posture, enabled sources/captures, configured/online receivers | source configuration, capture schedules, receiver transport configuration/history |
| Entity pulse | repeated callsigns and number groups | entity search, exact/fuzzy group matching, graph neighborhood |
| Investigation notebook | active hypotheses, latest public events, saved query launchers | relation graph, evidence editing, hypothesis history, event CRUD |

The following remain deliberately separate because they require dense,
interactive work rather than an operational glance: Spectrum, Receiver map,
Recordings, Sessions, Timeline, Relations graph, Hypotheses, Events, Sources,
and Capture.

## Visual system

- Base surfaces use black and neutral gray (`#070707`–`#171719`).
- Borders, typography, cards, navigation, and charts are neutral gray first.
- Green, amber, red, blue, violet, and pink occur only as state/evidence
  accents; they are not structural background colors.
- The dashboard uses a 12-column command-deck grid on desktop, collapses to
  three metric columns on tablet, and two metric columns with stacked queues on
  mobile.
