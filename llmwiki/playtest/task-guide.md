---
status: SOURCE-REVIEWED
curated: 2026-11-11
---
# Playtest workflow

Select the application window and translate the request into a checklist for `playtest_run`. For example, use `{"name":"moves right","kind":"move","keys":["Right"],"hold":1.0}` and `{"name":"pause","kind":"freeze","key":"Escape","resume_key":"Escape"}`. Optional setup has `restart_key`, `dismiss_keys`, and `settle_seconds`. One approval covers the stated inputs; value checks run first. Relay the finished report without changing verdicts. Restart is setup, not a verified check. Saved full-size frames allow review. `playtest_check` remains for exploration.

Only a correctly associated OCR label is read; icon-only counters may be unverified. Animated pause menus and overlays can prevent exact equality. Movement and panel detection are heuristics and can be wrong; a static screen is not necessarily gameplay. See the verification record for direct game failures and the absence of qualifying 0.2.2 Hermes sessions. X11, Pillow and xdotool are required; Tesseract is optional.
