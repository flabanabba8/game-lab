# Extracting text from Unity binary asset bundles

These are observations from one extraction experiment, not general Unity format rules. The current plugin supports Unity Mono imports; use its importer when it fits.

Use when a game's text lives in Unity `.assets`/`.assets.resS` bundles instead of RPG Maker JSON, and the built-in importer does not fit. Covers finding the strings; packing (repatching) is a separate, format-dependent step.

## What Unity stores where
- Text lives in the **uncompressed `.assets`** files as embedded **UTF-16LE** strings inside a binary serialization tree. The game's `.resS` files hold only compressed binary resources (textures/images); audio is a separate FMOD `.resource` bank (`FSB5` magic). Do not hunt for text in `.resS`.
- The `.assets` header is non-standard for its Unity version (custom version string, a GUID table near offset `0x4C`, no standard `fileIDListSize`/`nextOffset`/`treeSize` layout). The standard Unity binary-serialization varint tree walk fails on these files — do not assume the tree layout; find strings by content, not by the header.
- `strings -e S` on a `.assets` file reports the CJK strings (ground-truth count for later cross-checking). The C# assembly (`Assembly-CSharp.dll`) usually has none.

## Finding candidate strings (works; validated)
1. Read the `.assets` file as raw bytes.
2. Decode the whole file as UTF-16LE with a replacement policy: `raw.decode('utf_16_le','replace')`.
3. Run a regex for the script ranges you need, e.g. Japanese `[぀-ヿ㐀-䶿一-龯]+`, and keep runs of length ~4–60.
4. Map each run back to bytes with `byte_offset = char_index * 2`. This mapping is exact for UTF-16LE — verify a candidate by dumping its bytes from the raw file, not by trusting the decoded string alone.
5. Confirm a candidate is real text, not binary, before translating it (see below).

## Real text vs binary in CJK ranges (decision table)
The decode puts binary ID tables and metadata into the same CJK codepoint ranges as text, so filter by content:
- **Reject** runs whose bytes are sequential codepoints (e.g. UTF-16LE `00 2f 00 30 00 31 ...` = ASCII `/0123...`), or repeat a fixed sentinel (repeating `00 48`, `AA AA`, `FF FF`, `49 92 24 ...`). These are counters, type indices, GUIDs, and serialized handles.
- **Reject** runs whose high bytes are all `0x00`/`0x01` with only the low byte varying (chars like `U+4800`, `U+7701`) — structured binary, not words.
- **Accept** runs that mix kana (hiragana `U+3040–U+309F`, katakana `U+30A0–U+30FF`) with kanji (`U+4E00–U+9FAF`) and show varied bytes in both positions. Real dialogue has low repetition and no sequential/sentinel pattern.
- Check the surrounding bytes: real strings sit between serialization structure; pure binary sits between binary structure. Dump ~16 bytes on each side to see the delimiter.

## Known open question
The exact string delimiting in these files (length-prefixed vs structural markers) is not yet confirmed, so **repatching translated text back into `.assets` in a way the game still loads is unverified.** Until you can prove the delimiter format and round-trip a patched file, treat this skill as extraction-and-analysis only, and state that live in-game verification is still required. Do not claim a working Unity pipeline until the round trip is proven.

## Non-caveat: whole-file decode is a heuristic, not clean
The file is a binary serialization with embedded UTF-16LE strings, not pure UTF-16LE — a whole-file decode can misalign by a few code units (observed off-by-7 on a 2578872-byte file). Always confirm a candidate's bytes against the raw file before acting on it.
