---
name: playtest-pilot
description: Record observed playtest actions for a selected application. Use for this domain with its matching plugin tools.
---

On first use read the [bundled LLM wiki](../../llmwiki/playtest/index.md), then load
only the domain references needed for this task.


Ask for the application/scenario, platform, native computer-use access and permitted edits. Inspect the current host action schema and target before each action; forward approvals and original image-bearing results. The shipped adapter needs Hermes computer_use and POSIX window targeting; other runtimes need a supported target/action/observation contract and verified mapping. Until available, actions are blocked. Inspect screenshots in the main session, separate acknowledgment from observed success and never replay without an explicit selected step.

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

Available domain tools: `playtest_start`, `playtest_action`, `playtest_replay`, `playtest_observe`, `playtest_report`.

## Driving a game by keyboard (read this before the first action)

Games read keys only from the window that has focus, so background key delivery is often
acknowledged but lost. Follow the escalation ladder, one step at a time: send the key as an
action with the default delivery, then take a fresh capture and look. If nothing changed, repeat
the SAME action once with `"delivery_mode": "foreground"` AND `"bring_to_front": true` in the action object (the host asks the user to approve a visible focus change; the user approving it is expected). Bringing the window to the front keeps it active, so the keys after it land; foreground delivery without bring_to_front often swaps focus back too soon for a game. Capture again after each key. Record what you saw
with `playtest_observe` after every step: `passed` only for something you saw on screen,
`failed` for a visible mismatch, `uncertain` when you cannot tell. Do not stop after one lost
key: climb the ladder, and report a check as not tested only if the ladder is exhausted.
Work through every check the user listed, in the order a player would (title screen, start,
first level, run and jump with held or repeated keys, pause menu, back), and keep one screenshot
as evidence per check. A false expectation the user gave is a FAIL to report plainly, with what
the screen showed instead. Finish with a short plain report: for each check, what you did,
what you saw, and pass or fail. Never claim a pass the screen did not show.

Menus change in small ways: after a key, compare the NEW capture with the old one for any difference (a different highlighted entry, a submenu with different entries, a new screen). A submenu is progress, not a failure: read its entries and keep going with keys (up, down, return, escape). Prefer keys over clicks in games; a click can open a different menu entry than you meant.

Send every game input through `playtest_action` (with the action object for the host computer-use tool), not through computer_use directly: the playtest record is the evidence. Use computer_use only to list windows and take captures.

Clicking: coordinates are in the pixels of the LATEST capture of the target window (read its width and height in the capture result, and the element bounds given in the same frame). Aim at the centre of the square or button you mean, never at a neighbouring control, then capture again and compare before recording a result. If the screen did not change, say so and try the centre of another target once, instead of reporting an unverified pass.

Tap or hold: a tap (`key`) is right for menus, buttons and one-shot commands (Return, Escape in a menu, a letter). Movement, running and jumping in an action game need a HOLD: use `{"action": "hold", "keys": ["Right"], "seconds": 1.5}` (up to three keys together, such as Right and space to run and jump, at most 3 seconds). A hold raises and focuses the window and releases every key afterwards; the user approves it like the other actions. A tap of a movement key is too short for a game that reads held keys, so it does nothing visible. Every action returns a fresh capture of the window: look at it, then record the observation.

In an action game even Escape (pause) during play needs a short hold: use `hold` with `Escape` for 0.3 seconds, then look at the capture. A hold returns the capture taken a quarter of the way through, while the keys are still down, so to check a jump hold Right and space for 1 second and look at that capture: Tux should be in the air.

Before you report a check as unverified, look through ALL the captures you already have: a counter or label that is hidden during play may be visible in a pause menu or another screen. If anything on screen contradicts the user's claim (a different number, a missing entry), the check FAILED: report it as failed and say what the screen showed. Use unverified only when nothing on any capture bears on the claim.

## Judging movement in games where the camera follows the character

In a side-scrolling or other camera-following game the character usually stays in about the same place on screen while the world moves past him. So never judge movement by where the character is. Compare the BEFORE and AFTER captures and look at the background and landmarks (trees, blocks, platforms, enemies, the ground pattern): if they shifted sideways, the character moved the opposite way. "The character did not move on screen" is NOT evidence that he did not move. Every result also carries a `scene_shift` line (and the record keeps it per step) saying whether the whole picture slid and which way; use it together with what you see. A held key whose capture shows the scenery sliding is a pass for moving in that direction; say "passed" for a run when the scenery slid; say "failed" only when the whole picture stayed the same after a held key.

## Reading counters, scores and labels

To check a number the user mentioned (coins, lives, score, health, level), do not guess and do not call it unverified too soon. Look at the HUD in a capture, or open the pause or status menu and read the number from that capture; many games show the counter only there (for example "0/37"). A counter written like 0/37 usually means 0 collected out of 37 in the level, so the current count is the first number. Quote the number you read and compare it with the user's claim: a different number (including 0) means the check FAILED, and the report should give the real number and say where it was shown. Record the step whose capture shows the number as the evidence for that check.

## Screens that block the game

A game keeps running while you think, and it may stop on a choice screen (a level-up, a card or rule picker, a dialog, a pause menu) that swallows the keys you meant for play. If a movement or action check shows no effect and the capture shows such a screen, do not report the check as blocked or untested: dismiss it with the keys the screen itself names (for example 1, 2 or 3, Return, Escape), capture again, and then repeat the check. Report the check only after you have tried it on the normal play screen.
