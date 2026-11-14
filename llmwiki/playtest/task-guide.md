---
status: SOURCE-REVIEWED
curated: 2026-11-11
---
# Playtest workflow

Select the application window and translate the request into a checklist for `playtest_run`. For example, use `{"name":"moves right","kind":"move","keys":["Right"],"hold":1.0}` and `{"name":"pause","kind":"freeze","key":"Escape","resume_key":"Escape"}`. Optional setup has `restart_key`, `dismiss_keys`, and `settle_seconds`. One approval covers the stated inputs; value checks run first. Relay the finished report without changing verdicts. Restart is setup, not a verified check. Saved full-size frames allow review. `playtest_check` remains for exploration.

Only a correctly associated OCR label is read; icon-only counters may be unverified. Animated pause menus and overlays can prevent exact equality. Movement and panel detection are heuristics and can be wrong; a static screen is not necessarily gameplay. See the verification record for direct game failures and the absence of qualifying 0.2.2 Hermes sessions. X11, Pillow and xdotool are required; Tesseract is optional.

## Clips of failed checks

Each saved frame carries its capture time. After a run, every FAIL gets `<run id>-clips/clip-NN-<name>.mp4`: from 3 seconds before the check's last frame to 1.5 seconds after (change with `clips: {before_seconds, after_seconds, reel, enabled}` on `playtest_run` or with `playtest_clips`), never reaching before the run's first frame or past its end. The clip is a slideshow of the run's own frames held for their real durations, with a bar naming the check, what was expected and what was seen. If the user recorded the session with their own recorder, call `playtest_clips` with `recording: {path, start_time}` to cut from that file instead. Two or more clips also join into `reel-all-failures.mp4`. Passing checks only get a clip when named in `checks`. Without ffmpeg the report says no clips were made and is otherwise complete. File names are made from check names with only letters, digits and hyphens.
