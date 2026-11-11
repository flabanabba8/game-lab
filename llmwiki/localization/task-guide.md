---
status: SOURCE-REVIEWED
curated: 2026-11-09
---
# game-localization-studio setup and task guide

This is a source-reviewed operating guide, not a claim of a new live test.
Resolve exact parameter shapes from [tool contracts](../tools.md) and
[registration schemas](contracts.json) before calling a tool.

## Setup decisions

Confirm RPG Maker MV/MZ JSON, target language/glossary/font and the actual game message-row budget. Other formats need their own importer contract. Source text goes to the active host for translation, but the plugin makes no model/API calls. Opt-in system type names can affect custom scripts.

## Worked task flow

Use localize_inspect on the chosen JSON, then page localize_get by draft_id. Translate one addressed unit with localize_translate while preserving required control tokens. Validate the draft, resolve choice-branch/token/row findings and localize_export a separate file under its original game filename. Keep the original game data available for comparison.

## Failure diagnosis

Formatting/wait controls preserve order; supported variable/name/icon placeholders may move for grammar. Choice labels and branches must remain synchronized; missing or mismatched branches need manual review. An omitted row budget means layout is unknown. A structural pass cannot test font coverage, menus, images, plugins or actual message-box pixels.

## Acceptance and evidence limits

Accept an original-preserving JSON export with valid controls, reviewed language/glossary and documented uncovered fields. Verify representative dialogue/choices in the actual game before calling the localization ready. Avoid translating internal IDs/filenames or script-dependent names by assumption.

## Source trail

Derived from the packaged [README](../../README.md), [manifest](../../plugin.yaml),
registered tool schemas and the tests listed in provenance.json. Existing
verification records describe their own dated scope; no new live capability
was inferred from this documentation review.
