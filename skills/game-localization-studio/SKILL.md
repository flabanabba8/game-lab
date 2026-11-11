---
name: game-localization-studio
description: Produce source-addressed game translation drafts. Use for this domain with its matching plugin tools.
---

First list the working folder (`ls -lR`) and find the game file the user means (RPG Maker data JSON such as Map001.json, System.json, CommonEvents.json); do not ask for a path that is already in the folder, and use its absolute path with `localize_inspect`.

On first use read the [bundled LLM wiki](../../llmwiki/localization/index.md), then load
only the domain references needed for this task.


Ask the game/engine/data format, source/target languages, glossary, font and message-box constraints. Current importer targets RPG Maker MV/MZ message JSON; preserve control tokens and row budgets. Translate in the active user-selected host model or accept user translations; no translation provider is required. Another engine needs its actual importer/exporter contract and round-trip fixture, not renamed RPG Maker fields. Export separately and verify in the target game; token checks do not prove translation quality.

When the user only asks to translate a game and keep it working, do not interrogate
them. If no message-box size is given, assume RPG Maker's standard four-line message
window, pass `message_rows: 4` to `localize_inspect`, and say so in the final report.
The plugin counts rows, not pixels, and the default window does not wrap long lines:
if a translation is much longer than its source line, shorten it, or break it with a
line break only while the whole message stays within the row limit. Run
`localize_validate` before every export; if it or `localize_translate` reports a
problem, fix that unit and validate again. After `localize_export`, tell the user the export is a separate copy and offer a playtest: they can copy the file into a lab copy of the game, start it in a window they choose, and ask "Playtest it: <what to check>". Do not start a game or a playtest yourself without being asked, and do not call it proof of how the text looks.

In the report say how many units were
translated, which problems were caught and fixed, and that the originals were not
changed and the export is a separate copy.

Start with the user’s outcome and available resources. Reuse known answers and
accepted artifacts; ask missing questions only in ordinary chat. Local deterministic
work needs no model/API subscription. If remote services or model inference become
necessary, ask about hardware, runtimes/tools, subscriptions, separately verified
API entitlements, privacy and spending limits (zero is valid); recommend suitable
choices before downloads, installs, uploads or paid execution. Keep credentials
with the selected host interface. Preserve original contracts and real errors.

Use the existing tools when their contracts fit. When they do not, select an
actually available equivalent or build the smallest authorized adapter from the
real input/output contract, validate with bounded offline fixtures, and report
remaining live verification. Never substitute placeholder success, silently switch
providers or claim unimplemented platform support. Preserve unrelated work, pauses
and accepted assets; publication requires separate explicit authorization.

Available domain tools: `localize_inspect`, `localize_get`, `localize_translate`, `localize_validate`, `localize_export`, `localize_list_drafts`.

Row width: `localize_inspect` returns `row_width_limit_chars`, the widest original row in the file (the game's author
already fitted that on screen; pass `message_columns` to set another width). `localize_validate` reports every translated
row wider than that. Rows of one message are ONE sentence split across rows by the author: read all rows of the message
(same `group` in `localize_get`), translate the message as a whole, then put the Spanish (or other language) back row by
row, each row within the width and the message within the row limit, with no sentence repeated in two rows. Do not put the
whole message into the first row. When validate reports a wide row, fix that row and validate again; say in the report
which rows were caught and fixed.
