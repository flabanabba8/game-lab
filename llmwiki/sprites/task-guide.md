---
status: SOURCE-REVIEWED
curated: 2026-11-11
---
# Sprites setup and task guide

This is a source-reviewed operating guide, not a claim of a new live test.
Resolve exact parameter shapes from [tool contracts](../tools.md) and
[registration schemas](contracts.json) before calling a tool.

## Setup decisions

Confirm RPG Maker MV map-character format, actual filename prefix, expected character slot/direction and intended target game. Pillow is needed for deterministic image inspection/preview; no art model is needed. Other sprite layouts require an explicit grid contract before using these MV tools.

## Worked task flow

sprite_inspect_mv returns the source fingerprint, inferred grid/frame sizes and transparency. A $ filename denotes a single-character layout; an ordinary sheet has eight slots. Choose the observed slot/direction and sprite_preview_mv with that fingerprint, then visually inspect the returned separate GIF in the main session.

## With ModLab

When a mod ZIP carries character art, `modlab_inspect` reports (never blocks) whether each PNG under `img/characters/` or `img/sv_actors/` divides evenly into the MV grid for its filename. Use these tools for the detail on one file before applying. The lab copy is the safety net: a wrong sheet can be rolled back.

## Failure diagnosis

Do not force 48x48 frames merely from engine familiarity; infer actual grid dimensions. Empty/transparent cells may be deliberate. GIF encoders can merge identical frames and alter palette/alpha, so encoded frame count is not always the requested four-step sequence. A valid grid does not prove direction, feet placement or animation quality.

## Acceptance and evidence limits

Accept dimensions/layout consistent with the chosen engine and an unmodified source, plus an observed preview of the intended walk row. Verify actual game rendering and timing before installation. Structural/colored-fixture evidence is not visual acceptance of real character artwork.

## Source trail

Derived from the packaged [README](../../README.md), [manifest](../../plugin.yaml),
registered tool schemas and the tests listed in provenance.json. Existing
verification records describe their own dated scope; no new live capability
was inferred from this documentation review.
