#!/usr/bin/env python3
"""Measure per-project text-box budgets for safe localization.

The localization plugin counts ROWS, not pixels, and the default window does
not wrap long lines. The source provides two estimates:

  * WIDTH  = the widest ORIGINAL (source) row in a file, in characters.
            This is an estimate, not proof of visual fit. Measure it per
            file because different windows can have different widths.
  * HEIGHT = the number of rows the window shows (the message-box row budget).
            A message is ONE sentence the author split across its rows; a
            translated message must stay within that same row count and never
            repeat a sentence across two rows.

Usage:
  python3 measure_dimensions.py <draft.json>

Output: source budgets and translated rows exceeding those budgets.
"""
import json
import sys
from collections import defaultdict, Counter

NL = chr(10)      # real newline inside a source string (author's line breaks)


def measure(draft_path):
    dr = json.load(open(draft_path, encoding="utf-8"))
    units = dr["units"]

    def file_for(unit):
        if unit.get("source_file"):
            return str(unit["source_file"])
        path = unit.get("path")
        if dr.get("engine") == "unity" and isinstance(path, list) and path:
            return str(path[0])
        return str(dr.get("source_name") or unit.get("kind") or "unknown")

    rows_by_file = defaultdict(list)   # file -> list of row char-lengths
    rows_by_unit = {}                  # unit_id -> source row count
    for u in units:
        src = u.get("source", "")
        if not isinstance(src, str) or not src:
            continue
        rows_by_unit[u["id"]] = src.count(NL) + 1
        f = file_for(u)
        for line in src.split(NL):
            rows_by_file[f].append(len(line))

    width = {f: max(lengths) for f, lengths in rows_by_file.items()}
    height = max(rows_by_unit.values()) if rows_by_unit else 0

    print("=== Per-file WIDTH (widest original row, chars) ===")
    for f in sorted(width, key=lambda k: -width[k]):
        print(f"  {width[f]:>4} chars  {f}")
    print()
    print(f"Global WIDTH limit (chars): {max(width.values()) if width else 0}")
    print(f"Global HEIGHT limit (rows): {height}")
    print()

    width_vals = sorted(width.values())
    hvals = sorted(rows_by_unit.values())
    if not width_vals:
        print("No nonempty source units to measure.")
        return 1
    print(f"WIDTH distribution: min={width_vals[0]} median={width_vals[len(width_vals)//2]} max={width_vals[-1]}")
    print(f"HEIGHT distribution: min={hvals[0]} median={hvals[len(hvals)//2]} max={hvals[-1]}")
    print(f"units by source row count: {dict(sorted(Counter(rows_by_unit.values()).items()))}")

    violations = 0
    checked = 0
    for u in units:
        if u.get("id") not in rows_by_unit or not isinstance(u.get("translation"), str):
            continue
        checked += 1
        rows = u["translation"].split(NL)
        limit = width[file_for(u)]
        if len(rows) > rows_by_unit[u["id"]]:
            print(f"Unit {u['id']}: {len(rows)} rows exceeds source limit {rows_by_unit[u['id']]}")
            violations += 1
        for row_num, row in enumerate(rows, 1):
            if len(row) > limit:
                print(f"Unit {u['id']} row {row_num}: width {len(row)} exceeds {file_for(u)} limit {limit}")
                violations += 1
    print(f"Checked {checked} translations; {violations} violations.")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(measure(sys.argv[1] if len(sys.argv) > 1 else "draft.json"))
