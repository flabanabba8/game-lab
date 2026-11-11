---
status: SOURCE-REVIEWED
curated: 2026-11-09
---
# playtest-pilot setup and task guide

This is a source-reviewed operating guide, not a claim of a new live test.
Resolve exact parameter shapes from [tool contracts](../tools.md) and
[registration schemas](contracts.json) before calling a tool.

## Setup decisions

Confirm the app, scenario, permitted actions and exact X11 window_id. Current execution requires native Hermes computer_use plus POSIX locking. It does not launch a game, record screenshots/video or infer pass/fail. Observe images directly in the main session.

## Worked task flow

playtest_start records the scenario. For one intended operation, playtest_action includes intent, expected and an action based on fresh coordinates. Inspect the actual result and use playtest_observe to record passed/failed/uncertain with evidence. playtest_report separates intention, acknowledgment and observation.

## Failure diagnosis

Capture and action are not atomic across clients; coordinate other computer-use activity. Recapture makes old element indices unsuitable. An acknowledged click may still hit the wrong target. Only explicitly recorded, acknowledged and observed restricted non-text actions can replay into a separate same-app run; observe each replay before another. Never replay an uncertain action.

## Acceptance and evidence limits

Accept a trace of actual inspected outcomes and explicit uncertainty rather than a run with every acknowledgment labeled passed. Recheck target scale/layout/state before replay. Missing native action/observation support blocks execution; do not invent a text-only game test.

## Source trail

Derived from the packaged [README](../../README.md), [manifest](../../plugin.yaml),
registered tool schemas and the tests listed in provenance.json. Existing
verification records describe their own dated scope; no new live capability
was inferred from this documentation review.

## Games and keyboard delivery

A game window usually discards background key events. After a key whose effect a fresh capture does not show, repeat the same action once with delivery_mode foreground and bring_to_front true (separately approved by the user; bring_to_front keeps the game window active so later keys land, which was verified by hand against SuperTux), capture again and record the observation. A key that never produces a visible change is reported as failed or not tested with the screenshot, never as a pass. Work through all listed checks and keep one capture per check as evidence.

Tap or hold: playtest_action accepts a hold action (keys, up to three, seconds up to 3) implemented with xdotool key down/up on X11, since the host driver can only tap. Use it for movement and jumps in action games; taps stay right for menus. Every input action returns a fresh capture of the window. SuperTux 0.6.3 under software rendering was the evidence: six taps of Right and one tap of Escape did nothing, while a held key moved Tux and opened the pause menu.

## Camera-following games and counters

In a game whose camera follows the character, judge movement from the background and landmarks changing between the before and after captures, never from the character's screen position; the character often stays put while the world slides. Each action result carries a `scene_shift` line (also stored on the step in the record) that states whether the whole picture slid sideways and in which direction, measured from window pixels before and after the action. To check a counter or score, read it from the HUD or from the pause or status menu in a capture, quote the number, and report a mismatch with the user's claim as a failed check with the real number.

## Choice screens that block play

If keys seem to do nothing and the capture shows a picker or dialog (level-up cards, a rule choice, a prompt), dismiss it with the keys the screen names, capture again and repeat the check on the normal play screen before reporting. Do not leave a movement check as untested because a picker was open.
