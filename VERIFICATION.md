# Verification

Version 0.1.0 of the bundle. Dated 2026-11-11, Linux only.

## What was tested for the bundle

- **Python tests:** 56 pass (Hermes managed Python 3.11, a disposable Hermes home). That is the unchanged suites of the three parts (15 ModLab, 17 Game Localization Studio, 21 Playtest Pilot) with only their import paths adjusted, plus 3 bundle tests: `register()` exposes exactly the 19 declared tools and the one declared hook and finds all three skill files; the tool reference lists exactly the registered tools; the three parts use three separate plugin-data folders.
- **Desktop page:** the Game Localization Studio page test (headless browser fixture, stubbed Desktop SDK) passes against the bundle's `desktop/plugin.js`. The dashboard route module loads, answers `localize_list_drafts` through a test client and refuses a tool of another part.
- **Retirement/workflow preflight:** `tools/check-plugin-workflows.py` passes on the bundle.
- **Hermes admission:** `hermes plugins validate` (Hermes v0.23.0) on a clean `git archive` export of the pinned commit, with `--install-deps`, in a disposable Hermes home and checkout: passed with no warnings (the same run on the exact pinned commit is recorded in the catalog pull request). Checks passed: manifest, config schema, capability probe (declared tools and hooks equal the registered ones), built-in tool collisions, security scan, no core override, desktop surface.
- **Leak audit:** the tree and the history of the release repository were scanned for credentials, e-mail addresses, home paths, project and device identifiers: no findings.

## What was not re-tested for the bundle

The live evidence of each part is that part's own, from its stand-alone release, and was not repeated for the bundle:

- ModLab 0.2.0: synthetic Linux copy/apply/rollback tests, a read-only copy of a real game with a synthetic marker, and read-only help calls to the installed Universal Modder and REA tools. No real mod and no game launch were tested.
- Game Localization Studio 0.2.1: synthetic RPG Maker files; the official MV event interpreter and TextManager fixtures; no real game and no visual layout.
- Playtest Pilot 0.3.0: mocked tests, plus one live run against a Linux platform game in an isolated desktop (run, jump, pause and a false claim checked). Held keys use `xdotool` on X11.

The three parts were not run together against one game, and the bundle's own plugin-data folders (`game-lab-modlab`, `game-lab-localization`, `game-lab-playtest`) differ from the stand-alone plugins' folders; data written by those is not migrated. Windows, macOS and Wayland-only sessions were not tested.
