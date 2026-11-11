---
name: playtest-pilot
description: Playtest a selected X11 game window and report measured evidence.
---

Use `computer_use` to list the game window, then translate the user's request into a short checklist and call `playtest_run` once. Each check has a name and kind: `move` or `move_vertical` with `keys` (one arrow, WASD or space) and `hold` seconds; `freeze` with `key` and `resume_key`; or `value` with `label` and numeric `expect`. Optional `setup` has `restart_key`, `dismiss_keys` and `settle_seconds`. The user approves the listed inputs once. Relay the returned report exactly; never change its verdicts. The batch runner is experimental: measurements can be ambiguous, especially with moving enemies, animation, unlabeled HUD icons and modal screens. Full-size evidence is saved privately. See `llmwiki/playtest/index.md` for limitations. `playtest_check` remains available for exploratory single actions.
