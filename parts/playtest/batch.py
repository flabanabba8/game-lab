"""Bounded, evidence-producing batch playtests on an explicitly selected X11 window."""
import io
import math
import os
import re
import shutil
import subprocess
import time

from .core import bounded


def validate(checklist, setup, hold_spec):
    if not isinstance(checklist, list) or not 1 <= len(checklist) <= 20:
        raise ValueError('checklist must contain 1 to 20 checks')
    if not isinstance(setup, dict) or set(setup) - {'dismiss_keys', 'restart_key', 'settle_seconds'}:
        raise ValueError('Invalid setup')
    dismiss = setup.get('dismiss_keys', [])
    if not isinstance(dismiss, list) or len(dismiss) > 3: raise ValueError('Invalid dismiss_keys')
    for key in dismiss + ([setup['restart_key']] if setup.get('restart_key') else []):
        hold_spec({'keys': key, 'seconds': .08})
    settle = setup.get('settle_seconds', 2)
    if type(settle) not in (int, float) or not math.isfinite(settle) or not 0 <= settle <= 10: raise ValueError('Invalid settle_seconds')
    for check in checklist:
        if not isinstance(check, dict): raise ValueError('Each check must be an object')
        bounded(check.get('name'), 'check name', 100)
        kind = check.get('kind')
        fields = {'move': {'name', 'kind', 'keys', 'hold'}, 'move_vertical': {'name', 'kind', 'keys', 'hold'},
                  'freeze': {'name', 'kind', 'key', 'resume_key'}, 'value': {'name', 'kind', 'label', 'expect'}}
        if kind not in fields or set(check) != fields[kind]: raise ValueError('Invalid fields for check')
        if kind in ('move', 'move_vertical'):
            if not isinstance(check['keys'], list): raise ValueError('Movement keys must be a list')
            keys, _ = hold_spec({'keys': check['keys'], 'seconds': check['hold']})
            if len(keys) != 1: raise ValueError('Movement checks require one direction key')
            if keys[0].lower() not in ('left', 'right', 'up', 'down', 'w', 'a', 's', 'd', 'space'):
                raise ValueError('Movement direction must be an arrow, WASD or space')
        elif kind == 'freeze':
            for key in (check['key'], check['resume_key']): hold_spec({'keys': key, 'seconds': .08})
        else:
            bounded(check['label'], 'value label', 80)
            if type(check['expect']) not in (int, float) or not math.isfinite(check['expect']): raise ValueError('Expected value must be a number')


def colour_blobs(image):
    """Find contiguous saturated objects on a small image, grouped by hue."""
    hsv = image.convert('HSV').resize((320, 180))
    pixels = list(hsv.getdata()); labels = [-1] * len(pixels)
    for i, (h, sat, value) in enumerate(pixels):
        if sat >= 110 and value >= 100: labels[i] = h // 16
    found = []
    for i, hue in enumerate(labels):
        if hue < 0: continue
        labels[i] = -1; todo = [i]; count = sx = sy = 0
        while todo:
            pos = todo.pop(); x, y = pos % 320, pos // 320
            count += 1; sx += x; sy += y
            for other in (pos-1 if x else -1, pos+1 if x < 319 else -1, pos-320 if y else -1, pos+320 if y < 179 else -1):
                if other >= 0 and labels[other] == hue:
                    labels[other] = -1; todo.append(other)
        if 8 <= count <= 3000: found.append((hue, count, sx/count, sy/count))
    return found


def blob_shift(before, after, direction):
    first, second = colour_blobs(before), colour_blobs(after)
    candidates = []
    for hue, size, x, y in first:
        options = [(abs(n-size)/size, (xx-x)**2+(yy-y)**2, xx-x, yy-y) for h,n,xx,yy in second
                   if h == hue and .6*size <= n <= 1.6*size and (xx-x)**2+(yy-y)**2 <= 100**2]
        if not options: continue
        _, _, dx, dy = min(options, key=lambda v: (v[1], v[0]))
        if max(abs(dx), abs(dy)) >= 2: candidates.append((size, dx, dy))
    if not candidates: return None
    size, dx, dy = max(candidates)
    axis = dx if direction in ('left', 'right') else dy
    sign = 1 if direction in ('right', 'down') else -1
    if axis * sign >= 2: return 'largest moving colour region: %d px area, shift (%.1f, %.1f) at 320x180' % (size, dx, dy)
    return None


def displacement(before, after, direction, measure):
    """Compare camera translation and moving regions; ambiguous results remain unverified."""
    from PIL import ImageChops, ImageStat
    facts = measure(before, after)
    horizontal = direction in ('left', 'right')
    sign = 1 if direction in ('right', 'down') else -1
    scroll = facts['scene_scroll_pixels'] if horizontal else 0
    if scroll * sign >= before.width * .015:
        return True, 'camera scroll %d px' % scroll
    blob = blob_shift(before, after, direction)
    if blob: return True, blob
    # Match a changed region against the corresponding area at small offsets.
    # Using the whole diff bounding box makes this conservative when the world animates.
    a = before.convert('L').resize((160, 90)); b = after.convert('L').resize((160, 90))
    diff = ImageChops.difference(a, b).point(lambda p: 255 if p > 32 else 0)
    box = diff.getbbox()
    if box:
        x0, y0, x1, y1 = box
        if (x1-x0)*(y1-y0) < 160*90*.4 and x1-x0 > 2 and y1-y0 > 2:
            best, error = 0, float('inf')
            for delta in range(-25, 26):
                dx, dy = (delta, 0) if horizontal else (0, delta)
                l, t, r, bot = max(x0, -dx), max(y0, -dy), min(x1, 160-dx), min(y1, 90-dy)
                if r-l < 3 or bot-t < 3: continue
                e = ImageStat.Stat(ImageChops.difference(a.crop((l,t,r,bot)), b.crop((l+dx,t+dy,r+dx,bot+dy)))).mean[0]
                if e < error: best, error = delta, e
            if best * sign >= 2: return True, 'moving region shifted %d scaled px; changed %.2f%%' % (best, facts['changed_percent'])
    if facts['changed_percent'] < .5: return False, 'changed %.2f%%; no movement detected' % facts['changed_percent']
    return None, 'changed %.2f%%; direction could not be established' % facts['changed_percent']


def read_number(image, label):
    """Read a number on the same OCR line as the requested label."""
    exe = shutil.which('tesseract')
    if not exe: return None, 'tesseract unavailable; needs a person/model to read'
    from PIL import Image
    readings = []
    for sample in (image.convert('RGB'), image.convert('RGB').resize((image.width * 2, image.height * 2), Image.Resampling.NEAREST)):
        data = io.BytesIO(); sample.save(data, format='PNG')
        try:
            result = subprocess.run([exe, 'stdin', 'stdout', '--psm', '6'], input=data.getvalue(), capture_output=True, timeout=10, env={'PATH': os.environ.get('PATH', os.defpath), 'HOME': os.path.expanduser('~'), 'LANG': 'C'})
        except (OSError, subprocess.SubprocessError): return None, 'OCR failed; needs a person/model to read'
        if result.returncode: return None, 'OCR failed; needs a person/model to read'
        matches = []
        for line in result.stdout.decode('utf-8', 'replace').splitlines():
            match = re.search(r'\b' + re.escape(label) + r'\b', line, re.I)
            if match:
                numbers = list(re.finditer(r'(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])', line))
                if numbers:
                    n = min(numbers, key=lambda item: min(abs(item.start()-match.end()), abs(match.start()-item.end())))
                    matches.append(float(n.group()))
        if len(matches) != 1: return None, 'OCR could not uniquely associate a number with %s; needs a person/model to read' % label
        readings.append(matches[0])
    if readings[0] != readings[1]: return None, 'OCR readings disagree; needs a person/model to read'
    return readings[0], 'OCR read %s near %s' % (readings[0], label)


def run(pilot, app, window_id, checklist, setup, api):
    validate(checklist, setup, api.hold_spec)
    api.focus_window(window_id)
    api.capture_image(window_id)  # verify capture before any input
    run_id = pilot.start(app, 'Batch playtest', window_id)['run_id']
    tap = lambda key: api.hold_keys(window_id, api.hold_spec({'keys': key, 'seconds': .08})[0], .08)
    capture = lambda: api.capture_image(window_id)
    if setup.get('restart_key'): tap(setup['restart_key'])
    time.sleep(setup.get('settle_seconds', 2))
    ordered = sorted(enumerate(checklist), key=lambda item: item[1]['kind'] != 'value')
    results = []
    for index, check in ordered:
        frames = []
        kind = check['kind']
        try:
            before = capture(); frames.append(before)
            if api.is_black(before): raise ValueError('Window is black or loading; no check input sent')
            if kind == 'value':
                number, reason = read_number(before, check['label'])
                verdict = 'UNVERIFIED' if number is None else ('PASS' if number == check['expect'] else 'FAIL')
                reason += '; expected %s' % check['expect']
                frames.append(before.resize((before.width * 2, before.height * 2)))
            elif kind == 'freeze':
                tap(check['key']); time.sleep(.2); paused = capture(); time.sleep(1); later = capture()
                tap(check['resume_key']); time.sleep(.2); resumed = capture(); time.sleep(1); resumed_later = capture()
                frozen = paused.tobytes() == later.tobytes(); changed = resumed.tobytes() != resumed_later.tobytes()
                verdict = 'PASS' if frozen and changed else 'UNVERIFIED'
                reason = 'identical after one second: %s; changed after resume: %s' % (frozen, changed)
                frames = [paused, later, resumed_later]
            else:
                key = check['keys'][0].lower()
                direction = {'right':'right','d':'right','left':'left','a':'left','up':'up','w':'up','space':'up','down':'down','s':'down'}[key]
                measured = None
                for attempt in range(2):
                    if attempt:
                        text = api.visible_text(before)
                        if len(set(re.findall(r'\[([1-3])\]', text))) >= 2 or api.measurements(before, before)['panel_after_hint']:
                            for k in setup.get('dismiss_keys', []): tap(k)
                        # Wait for a stable state, bounded to avoid endless cutscenes.
                        for _ in range(5):
                            time.sleep(.5); current = capture()
                            if api.measurements(before, current)['changed_percent'] < 2: break
                            before = current
                        before = capture()
                    held = api.hold_keys(window_id, api.hold_spec({'keys': check['keys'], 'seconds': check['hold']})[0], check['hold'], during=capture)
                    after = capture(); frames = [before, held['during'], after]
                    measured, reason = displacement(before, after, direction, api.measurements)
                    if not measured and held.get('during_completed_before_release'):
                        during_measured, during_reason = displacement(before, held['during'], direction, api.measurements)
                        if during_measured: measured, reason = during_measured, during_reason + ' during hold'
                    if measured: break
                    before = after
                verdict = 'PASS' if measured is True else 'FAIL' if measured is False else 'UNVERIFIED'
            evidence = []
            for n, image in enumerate(frames):
                path = pilot.root / ('%s-batch%d-frame%d.png' % (run_id, index, n))
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out: image.save(out, format='PNG')
                evidence.append(path.name)
            results.append((index, {'name': check['name'], 'verdict': verdict, 'reason': reason, 'evidence': evidence}))
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            results.append((index, {'name': check['name'], 'verdict': 'UNVERIFIED', 'reason': str(exc), 'evidence': []}))
    results.sort(); entries = [item[1] for item in results]
    report = '\n'.join('%s: %s — %s' % (x['name'], x['verdict'], x['reason']) for x in entries)
    data = pilot.load(run_id); data['batch_results'] = entries; data['batch_report'] = report; pilot.save(run_id, data)
    return {'run_id': run_id, 'report': report, 'checks': entries}
