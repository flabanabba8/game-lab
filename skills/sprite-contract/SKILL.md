---
name: sprite-contract
description: Inspect and preview a sprite sheet for its actual engine grid. Use for this domain with its matching plugin tools.
---

On first use read the [bundled LLM wiki](../../llmwiki/sprites/index.md), then load
only the domain references needed for this task.


Ask for engine/version, sheet layout, expected slots/directions and rendering target. Current tools implement RPG Maker MV character grids; inspect the source fingerprint before choosing a walk row. Other engines need an explicit grid/metadata contract and adapter, not assumed MV sizing. Use Pillow for deterministic previews when installed; inspect images directly in the main session with native vision. Grid validity is not an anatomy or animation-quality review.

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

This part pairs with ModLab: before a mod that replaces character art is applied to a lab copy, check the sheet here (ModLab's `modlab_inspect` already adds a short report-only note). Never block or edit the artwork from this part.

Available domain tools: `sprite_inspect_mv`, `sprite_preview_mv`.
