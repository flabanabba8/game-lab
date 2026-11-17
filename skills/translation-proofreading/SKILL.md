---
name: translation-proofreading
description: Proofread English translation for spelling and coherence.
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [translation, proofreading, qa, dialogue, english, consistency, modding]
    related_skills: [localization-audit, localization-overflow, game-localization-studio]
---

# Translation proofreading

## When to Use

- The user asks to check/review already-authored English translation text for spelling, coherence, grammar, or consistency — e.g. "check your translation for spelling and coherence", "proofread the dialogue", "is the English clean?".
- You need to catch English-language defects in text that is already translated: typos, garbled/incoherent lines, untranslated source-language left inline, name/term drift, and truncation.

Do NOT use for:
- Verifying faithfulness to the source (english ↔ source) — check against the source with the project’s source-addressing contract. This skill reviews the English itself.
- Checking on-screen width/overflow budgets — that is `localization-overflow`.
- Setting up a translation worker.

## Always-on rules (hold for every instance)

1. **Start from the glossary / style guide when available.** Use it as the baseline for agreed names and terminology. Without one, report uncertain terms and use project evidence instead of inventing a canonical form.
2. **Read the text in source order, in batches.** Walk each translation file by id in ascending order; never judge quality from a one-line sample. Dialogue and UI strings are read line by line.
3. **Classify every defect so the report is actionable.** Tag each candidate as one of: spelling/typo, untranslated source-language inline, garbled or incoherent English, name/term inconsistency, or truncation. Report grouped by class, each with `file:line`.
4. **Check names and terms against the glossary.** Check names in context and respect intentional variants. Catch unintended romanization drift across chunks (e.g. one chunk renders a name the glossary calls X as Y elsewhere).
5. **Separate intentional voice from real defects.** Puns, wordplay, character speech patterns, and deliberate suffixes (e.g. a persona "-girl" suffix) read as odd but are intentional — flag them as "verify" rather than "fix". Only a calque that does not survive translation as coherent English is a real defect.

## Procedure (in order)

1. **Map the files.** Identify the translation output files (e.g. `tr-chunk-*.txt`, `id<TAB>text` lines) and the glossary, and confirm the source files (e.g. `chunk-*.jsonl`) exist for cross-checking names. Know which files are dialogue vs. placeholder labels vs. item/UI strings.
2. **Load the glossary.** Note fixed renderings and which names stay Japanese vs. romanize. This is your consistency baseline.
3. **Read in order.** Read each file by id ascending, in batches, collecting candidate defects. Prefer reading the file (so you get exact line numbers) over a piped grep.
4. **Collect by class.** For each candidate, tag spelling / untranslated / garbled / inconsistency / truncation and record `file:line` plus the offending text.
5. **Cross-check names.** Pull every proper noun against the glossary; flag unintended inconsistent renderings and term drift, while allowing intentional variants.
6. **Report.** Give a grouped list by defect class; each line is `file:line — offending text → fix`. Keep it lean. Mark items as *definite fix*, *verify* (intentional voice), or *known/acceptable* (matches source intent). Note which files/chunks were and were not reviewed.

## Pitfalls

- **Untranslated source-language left inline.** Kanji/other source script mixed into the English (e.g. a Japanese noun left untranslated). Check whether it is intentional before proposing romanization or translation.
- **Romanization / name drift.** A source name appears under inconsistent English spellings across chunks. Check context and use the glossary form unless a variant is intentional.
- **Escape-drift in literal-newline files.** When patching `.txt` files where `\\n` is stored as `\\\\n`, the `patch` tool may strip or double-escape backslashes. Use `cat -A` to confirm the literal byte representation before patching. If `patch` fails, re-read the file to get the exact string for the `old_string` match.
- **Literal calque garble.** Check awkward literal renderings against the source and surrounding context; propose wording that preserves the character’s intent.
- **Machine-translation garble.** Lines that read as gibberish or bad literal calques are usually a failed machine render (e.g. a clipped transliteration or an awkward word-for-word calque). Confirm against the source before rewriting; the literal render is wrong but the intent may be recoverable.
- **Truncated strings.** Lines ending in "…" or trailing mid-sentence are cut off. Confirm against the source whether that is intentional (ellipsis in the source) or a dropped/failed line.
- **Calques and puns that do not survive translation.** Wordplay that only works in the source reads as nonsense in English. Preserve the intent and flag that the literal rendering is incoherent rather than silently changing meaning.
- **Placeholders are not defects.** Section headers and item/UI labels (e.g. "Conversation 1", "Love Scene 2", clothing/food names) are often intentionally terse or untranslated — do not flag them as dialogue errors.

## Verification

- Every spelling/typo candidate is corrected or explicitly marked verify.
- Names and terms are checked against the available glossary and intentional variants.
- Garbled lines are confirmed against the source before being rewritten.
- Truncated lines are checked against the source for intent.
- Report states which files/chunks were and were not reviewed.