# Unity (Mono) text translation via units.jsonl

These observations describe one Unity Mono project. The current plugin supports Unity Mono imports; use its bundled import/export tools. The `make_chunk.py` helper described below was project-specific and is not bundled. All files you create live in the working folder (e.g. `work/`), never in the game folder.

## Units file
`<plugin-data>/.../<draft_id>/units.jsonl` — one JSON object per line: `id`, `kind`, `context`, `group` (always null here), `source`, `translation` (null until filled).
- `textasset:text` — dialogue/narration from scenario JSON. `context.characterID` is the speaker; `context.id` is the line id. Lines of one scene are consecutive — translate in order, keep each speaker's voice consistent.
- `mono:<Class>` (Item, Food, Job, Skill, Achievement, Clothing, …) — names and descriptions of game data. A name is usually followed by its description.
- `mono:TMPro.TextMeshProUGUI` — UI labels; keep short (fixed sizes).
- `textasset:name` — internal node labels (e.g. 会話６, 終了). Leave untranslated: not shown to the player.
- `textasset:value`, `code:string` — function arguments / code literals; some are fragments the code joins to other text — translate so the joined sentence still reads.

## Pipeline
1. `localize_inspect(source_path=<game folder>)` to create the draft and get counts per kind; report the counts and the blocked name matches.
2. Read `units.jsonl` directly (or `localize_units_file(draft_id=...)` to rewrite it). Read ~25 lines at a time (offset 1, 26, 51, …). Read each unit's **full** `source` before translating — do not slice it (e.g. `source[:46]`), because a truncated slice still looks like a complete line and you will translate the wrong (shortened) text.
3. Write each window to `work/tr-chunk-NNN.txt`, one line per unit, **tab-separated**: `id<TAB>translation`. Skip `textasset:name` lines. Keep every `{0}`/`<tag>` placeholder exactly; never return an empty translation; never include control characters.
4. Assemble: `python3 make_chunk.py <units.jsonl> chunk-NNN.jsonl tr-chunk-NNN.txt`. The assembler pairs each line's id with the unit's `source` string verbatim and emits `{"id","source","translation"}`, escaping `\n` for you. It skips `textasset:name` lines.
5. Import: `localize_import_translations(draft_id=..., path=<absolute chunk jsonl>)`.
6. **Verify** (see below). If `rejected > 0`, read `rejected_lines`, fix only those lines in a small file, and re-import; do not move on with rejections unresolved.
7. After ~10 chunks, `localize_list_drafts` to confirm the translated count is rising; add recurring terms to the glossary.
8. When all translatable units are done: `localize_validate` (fix anything it lists, re-validate), then `localize_export` (patched copies in a separate folder; do not copy into the game).

## make_chunk.py
`python3 make_chunk.py <units.jsonl> <out.jsonl> <tr.txt>`
- Input `.txt` must be tab-delimited (`id<TAB>translation`); a missing tab drops the line.
- It reads the `.txt` line by line and looks up each id in `units.jsonl`; the `source` is taken verbatim from `units.jsonl`, never from your file.
- Lines whose unit is `textasset:name` are skipped.
- Output is a JSONL of `{"id","source","translation"}`.
- **Corruption check before building**: `grep -c '<parameter' tr-chunk-NNN.txt` first. A duplicated `path` parameter in the write_file call appends a `<parameter=...>` call-trace line (plus the file path string) into the text; the assembler then pairs that phantom line with a unit and the build breaks. If the count is nonzero, rewrite the file cleanly with a single `path`.

## Verification (do not skip)
`localize_import_translations` only checks that a chunk's `source` string matches the unit's source — it does not check that your translation is faithful. A zero-rejection import can hide a shifted or dropped translation. After every import, spot-check the stored translations: read the draft's `draft.json` (`units[].translation`) for the ids you just imported and confirm each is the one you intended for that id. The usual failure is skipping one source line mid-window — often a line you mistook for a `textasset:name` — which shifts every later line in the window, and the whole chunk still imports with zero rejections. Confirm the ids present in the chunk against the real source lines before trusting the count.

## Chunking
~22–28 translation lines per chunk keeps each reviewable. Track cumulative counts from the import response (`translated`/`total`).

## Line breaks in translations (format)
Represent a line break in a translation as escaped backslash-n (`\n` — the two characters backslash + n), never a real newline (chr 10). The `.txt` must have exactly one line per unit: a real newline inside a translation field breaks the tab-delimited format and splits one entry across two lines. The source keeps real newlines (they arrive verbatim from the game). `make_chunk.py` reads the `\n` as literal backslash-n and `json.dumps` doubles the backslash in the JSONL; the import stores backslash-n in `draft.json`, which is what the renderer turns into a line break. Verify before building that the file has one line per unit (e.g. `wc -l` equals the unit count) and that no translation contains a real newline — split each stored `units[].translation` on backslash-n (chr 92 + `n`), not on chr 10, when checking.

## Wrapping to fit the message box
The box counts rows, not pixels, and the default window does not wrap long lines. When `row_width_limit_chars` is unavailable (custom importer, hand-built chunk), derive the cap from the widest source row: count its characters — CJK and Latin rows both fill the box in the game's own font, so an English row may exceed that count by at most ~1.4×, since Latin glyphs render a little narrower than CJK. Wrap each source line independently, never the whole message as one string: an embedded line break is real text, and wrapping across it strands short words (and, I, of, to) alone on a line. Check the vertical axis too — a message that gains rows beyond the source can overflow the box bottom even when every line fits; keep the row count at or below the source unless the box visibly holds more.
