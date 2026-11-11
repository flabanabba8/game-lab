---
status: SOURCE-REVIEWED
curated: 2026-11-11
---
# Playtest workflow

Select the window and use `playtest_start`, then use one `playtest_check` per expectation. Inspect its images and measured hints, record a verdict with `playtest_observe`, and finish with `playtest_report`. Use `playtest_read_value` for a small HUD region. For an overlay, read the displayed dismissal key and perform a separate approved check before retrying. Pause probing compares frames one second apart; verify resumed movement separately. Measurements are heuristics and do not prove game semantics.
