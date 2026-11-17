---
status: SOURCE-REVIEWED
curated: 2026-11-17
---
# Unity games

For a Unity game the draft is made from the game folder, not from one file. The tools are the same
`localize_*` tools; resolve exact arguments from [tool contracts](../tools.md).

## What is supported

A player build with Mono scripting and loose data files: the folder holds `<Game>_Data/` with
`globalgamemanagers`, `resources.assets`, `sharedassetsN.assets`, `levelN` and `Managed/Assembly-CSharp.dll`.
Serialized-file format 22 (Unity 2020 and later), little-endian.

Three carriers are read:

| Kind in the draft | Where the text is | Address |
|---|---|---|
| `textasset:<key>` | A TextAsset whose content is a JSON document: every string value that passes the filter | file, object ID, JSON path |
| `mono:<Script class>` | A string field of a script component or ScriptableObject (`mono:TMPro.TextMeshProUGUI` is a label placed in a scene or prefab) | file, object ID, byte offset in the object |
| `code:string` | A string literal that a method of `Assembly-CSharp*.dll` loads | heap offset |

`context` on a unit gives the asset or object name and, for JSON, the short sibling values of the entry
(an ID, a type number, a speaker ID). Use it to tell dialogue from labels and to keep a speaker's voice.

Not supported, and `localize_inspect` says so: `data.unity3d` (UnityFS), other format versions, signed
assemblies (refused at export). On an IL2CPP build the data files are still read but code strings are not.
Never covered: asset bundles, text in images, text assembled at run time, text in other assemblies.

## Flow

1. `localize_inspect` with the game folder. Report `units`, `files`, `kinds`, `blocked_name_matches` and
   `notes` to the user. `text_filter` decides what counts as text: `cjk` (default) for a Japanese, Chinese or
   Korean source; `non_ascii` for other non-English sources; `all` only when the source is ASCII, and expect
   many internal identifiers in it.
2. Small job: page with `localize_get` and save with `localize_translate`. Large job: `localize_units_file`,
   fill the `translation` field of each line, `localize_import_translations`. Rejected lines come back with a
   line number and reason; fix those lines and import again (already saved lines count as unchanged).
3. `localize_validate`. `errors` must be empty. `wider_than_source_units` is a warning list, widest overrun
   first: a label or a fixed box may clip there.
4. `localize_export`. The result folder holds only the files that changed, under their original names.
   The user copies them over the same files in a COPY of the game.

## Rules for the wording

- Keep every `{0}`, `{1:#,0}` and every `<tag>` exactly; they may move. `localize_translate` refuses otherwise.
- Keep line breaks where the source has them unless the sentence needs otherwise; there is no row limit
  check for Unity, so more rows than the source is only a warning.
- Do not translate identifiers. With the `cjk` filter almost everything offered is wording, but look at
  `kind`: a script class whose strings are all short keys (part names, IDs) deserves a look at how the game
  uses them before translating.
- Code literals are sometimes concatenated (`"あと" + x + "個です"`): translate each piece so the
  joined sentence still reads, and tell the user which ones you could not make natural.

## Name matches

A string equal to the name of a game object or asset in the same game is blocked: games often find an
object, sprite or resource by a name stored in data. `allow_name_matches=true` on a new inspect lifts the
block for the whole draft. Only do that when the user accepts the risk or the code was read (ModLab and
REA can decompile `Assembly-CSharp.dll`) and the field is display-only. A string that is a lookup key
without matching any object name (a dictionary key, a save-file key) is not detected.

## How the files are written

- Serialized file: the changed object is rewritten, the objects after it move, and the object table and the
  file size in the header are updated. Objects that did not change are copied byte for byte. Nothing in
  `.resS` or `.resource` moves, because those are addressed from inside objects that are not touched.
- JSON text asset: only the characters of the changed string values are replaced; indentation, key order,
  line endings and the byte-order mark stay.
- Assembly: the metadata block is copied to the end of the last section with the new literals appended to
  the string heap, and only the `ldstr` instructions of changed literals are pointed at them. Method bodies
  are walked instruction by instruction to find those; no code moves.

## Evidence limits

The export is re-read by the plugin before it is written, and that is all it proves: the files parse and
contain the new strings. It does not prove the game starts, that a font has the needed letters (a
Japanese-only TextMeshPro font shows boxes for missing letters), that text fits, or that no translated
string was a lookup key. Those need the patched copy running: offer a playtest, do not claim it.
Save files may store text or names from the original language.
