---
name: game-translation-pipeline
description: Merge, audit, and chunk game translation data.
---

## Procedure

1. **Initial Recon**: Scan the master unit list (e.g., `units.jsonl`) for specific dialogue keys, UI labels, or keywords.
2. **The Merge**: Merge translation data using the project’s supported tools; write to a separate output before replacing any canonical data.
   - *Pitfall*: Validate the JSONL schema and record types before merging; preserve IDs, source text, placeholders, and the association between each source and translation.
3. **Corruption Audit**: After merging, search translations for project-specific artifacts. Compare candidates against the original source and identify affected IDs.
   - *Pitfall*: Do not alter source strings to fix a translation artifact. Confirm the cause and correct the translation or extraction process.
4. **Manual UI Patching**: Inspect the game UI when available to identify text missing from the draft. Establish where that text is stored and the actual patching contract before changing it; verify fit and meaning in game.
5. **Chunk Synchronization**: If the project uses chunks, regenerate affected chunks with the project’s existing tools.
   - *Pitfall*: Check for missing IDs, null translations, duplicate IDs and off-by-one errors. Do not assume an unbundled script exists.
6. **Final Verification**: Verify the affected IDs and source/translation pairs in the resulting chunks. Run the plugin validator and report remaining issues; a text search alone does not prove translation quality or in-game rendering.
