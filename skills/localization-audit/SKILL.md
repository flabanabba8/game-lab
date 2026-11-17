---
name: localization-audit
description: Audit and fix name/term consistency using a glossary.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [localization, audit, consistency, game_lab]
    related_skills: [game-localization-studio]
---

# Localization Audit Skill

Use this skill to ensure naming consistency across a large translation corpus.

## When to Use
Use this skill when:
- A new glossary has been updated and needs to be propagated.
- A character name was changed in the source but remains old in the translation.
- "Garbled" or "Opaque" Japanese phrases need a standardized English equivalent.
- Initializing a new project's translation and want to ensure baseline coherence.

## Workflow

### 1. Identify the Glossary
Locate the project's authoritative glossary or style guide. If none exists, use
confirmed project evidence and report uncertain terms rather than inventing a
canonical mapping.

### 2. Define the legacy map
Build a project-specific list of obsolete or inconsistent terms and their
approved replacements. Check names in context; identical words can have
different meanings, and names may have intentional variants.

### 3. Execute audit
Search the current translation records for candidates. Review each match in
context before changing it. Preserve IDs, source strings, placeholders,
formatting and the project's line-break representation. Apply changes to the
canonical translation data and regenerate derived chunks only if the project
workflow requires it; never replace text in source fields.

### 4. Verification
Recheck changed records and derived chunks for the intended terms and for
unintended replacements. Compare affected translations to their sources and run
`localize_validate` when using Game Localization Studio. Report checked files,
changes, unresolved cases, and any remaining verification.

## Pitfalls

- Old translations in derived chunks can reappear after regeneration. Check
  both the canonical translations and any derived outputs, without changing
  the source text.
- A global replacement can alter unrelated words or intentional variants.
  Review matches in context.
