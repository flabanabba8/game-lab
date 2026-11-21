---
status: FIELD-OBSERVED
curated: 2026-11-21
---
# Godot 4 games (.pck)

`localize_inspect` accepts a Godot 4 `.pck` (or the folder holding exactly one). This page explains what the
importer reads, what it cannot see, and what one full localization (Godot 4.5.x, Dialogue Manager, about 2,000
units, Japanese to English) showed about finishing and verifying the job. Those observations come from one game;
they are not engine contracts.

## What the importer reads

| Kind | Where the text is | Address |
|---|---|---|
| `dialogue` / `response` | Dialogue Manager `*.dialogue-<hash>.tres`: `text` of player-visible lines | entry, character span |
| `speaker` | the same files: `character` names (patch them or every line shows the source-language name) | entry, character span |
| `resource` | uncompressed binary `.scn`/`.res` (`RSRC`) strings in the body | entry, byte offset |
| `script` | compiled scripts (`.gdc`, zstd): String constants | entry, offset in the unpacked body |

`raw_text` in dialogue files keeps the source and is never shown; it is left alone. Export writes ONE new `.pck`
(every entry copied, changed entries replaced) and re-reads it. Compiled scripts need Python 3.14+
(`compression.zstd`); on older Python they are skipped and the inspect notes say so.

Blocked by default: a string that is both a scene/resource string and a script constant (animation names,
dictionary keys). Code may look these up by value, so translating them can break lookups. Check where they are
used (scripts keyed by an ASCII id are safe), then re-inspect with `allow_name_matches`.

Not covered: text drawn into images (`.ctex`), compressed `RSCC` resources, encrypted packs, packs embedded in an
`.exe`, strings built at run time. The default `cjk` filter includes half-width katakana (U+FF66–FF9F): sound-effect
lines written in half-width kana are otherwise missed.

## Text in images
Godot 4 imports PNGs as `CompressedTexture2D` (`GST2`); the common lossless import holds a WebP after a 56-byte
header. `godot.ctex_decode` / `godot.ctex_encode` read and replace that picture (same size). Tutorial pages,
character-intro sheets and title subtitles carry text here. Workflow: list textures by folder, find text by pixel
colour inside measured boxes, erase with a fill that suits the background (row/column interpolation on gradients,
background colour on flat panels), redraw the translation inside the same box. Always read the ORIGINAL pack, so
re-runs never stack on earlier output, and check by diffing output against the original outside the edited zones.

## Verify on the game's own engine
- Use `godot_version` from the inspect result. Run the final pass on that exact version: the shipped Windows
  `.exe` under Wine on a private X display, or the official Linux build of the same version. A newer minor
  version is not a valid final pass.
- The official Linux build of the same version shows the game's debug/cheat menu if it has one (release exes hide
  it). Use it to reach late content; use the `.exe` for the final look.
- Measure, do not trust an image viewer: images in the pack equal the output PNGs; zero source-language text in
  the dialogue `text`/`character` fields of the built pack; headless boot errors equal to the original's; only
  text-holding entries changed (hash every entry against the original).

## Fit: test lines in the real box
- In the observed game the dialogue box word-wrapped and held 3 rows of about 45 characters. Estimate rows for
  every line and shorten anything over the limit; `localize_validate` warns about lines over 3 rows.
- To see a late-game line without playing to it, build a throwaway pack whose first intro lines carry the lines
  under test (or swap in the dialogue file holding a choice menu), start a new game, screenshot, then restore the
  translations and build the real pack.
- Measure button padding from pixels; a viewer described a padded button as flush.

## Gallery and art
- Sweep every character × every animation, grab each, review as contact sheets. Scrolling lists: calibrate the
  positions at top and bottom scroll first.
- Odd frames (floating arms, black backgrounds) may be original art: prove it by showing those entries are
  byte-identical to the original pack.

## Coherency pass
- Read every line against the source, scene by scene. Model errors repeat across files: a "block/take the hit"
  bark came out as an attack shout in dozens of battle lines, and a pronoun was wrong in a dozen more. Fix such
  classes with one scripted rule, then rewrite single lines by hand.
- Keep the edit list as a script, keep a copy of the translations before the pass, tag edited rows.
- Keep menu and debug names consistent with the gallery names for the same move.
