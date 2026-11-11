import json
import io
import base64
import functools
import math
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from .core import Pilot, bounded

_action_lock = threading.Lock()

TOOLS = {
    'playtest_start': ('Start an explicitly authorized playtest for one named application with a scenario description.', {'app': {'type': 'string'}, 'scenario': {'type': 'string'}, 'window_id': {'type': 'integer', 'minimum': 1}, 'pid': {'type': 'integer', 'minimum': 1, 'description': 'Process ID of that window, from computer_use list_windows; needed so the window can be captured before each action'}}, ['app', 'scenario', 'window_id']),
    'playtest_action': ('Perform ONE native computer-use action on the selected app. Optionally record a restricted non-text action for explicit step-by-step replay. Host approvals remain in force; observations are separate.', {'run_id': {'type': 'string'}, 'intent': {'type': 'string'}, 'expected': {'type': 'string'}, 'action': {'type': 'object', 'description': 'The native computer_use action as an object, for example {"action": "key", "keys": "Right"} or {"action": "key", "keys": "space", "delivery_mode": "foreground", "bring_to_front": true}. Do not wrap it again and do not repeat run_id or app inside it. For movement or jumps in an action game use {"action": "hold", "keys": ["Right"], "seconds": 1.5} (up to three keys together, at most 3 seconds): a tap is too short for a game that reads held keys, For a one-shot pause key use a short tap or 0.05–0.1 second hold, then wait and inspect; holding it longer can toggle pause repeatedly. A hold requests a capture one quarter of the way through; slow capture can arrive after key release, so inspect the image rather than assuming its timing. A wait action with seconds from 0 to 30 captures the window after the delay. Input actions request a fresh capture; its pixel size is in the result and click coordinates use that frame.'}, 'record_for_replay': {'type': 'boolean'}}, ['run_id', 'intent', 'expected', 'action']),
    'playtest_replay': ('Replay one explicitly selected, previously observed non-text action into a separate run of the same named app. Verify coordinates and state first; host approvals remain in force.', {'run_id': {'type': 'string'}, 'source_run_id': {'type': 'string'}, 'source_step': {'type': 'integer', 'minimum': 1}}, ['run_id', 'source_run_id', 'source_step']),
    'playtest_observe': ('Record a user/agent observation after inspecting actual game state. The result is a human observation, not automatic proof.', {'run_id': {'type': 'string'}, 'step': {'type': 'integer', 'minimum': 1}, 'status': {'type': 'string', 'enum': ['passed', 'failed', 'uncertain']}, 'note': {'type': 'string'}}, ['run_id', 'step', 'status', 'note']),
    'playtest_report': ('Read playtest intentions, action acknowledgment and separately recorded observations.', {'run_id': {'type': 'string'}}, ['run_id']),
}

TOOLS.update({
    'playtest_check': ('Capture before, during and after one approved input and measure the change. Record the verdict with playtest_observe.', {'run_id': {'type': 'string'}, 'intent': {'type': 'string'}, 'expected': {'type': 'string'}, 'action': {'type': 'object', 'description': 'Example: {\"action\": \"hold\", \"keys\": [\"Right\"], \"seconds\": 1.5}; key uses the same shape; click uses coordinate.', 'properties': {'action': {'type': 'string', 'enum': ['key', 'hold', 'click']}, 'keys': {'description': 'One to three key names', 'anyOf': [{'type': 'string'}, {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 3}]}, 'seconds': {'type': 'number', 'minimum': 0.05, 'maximum': 3}, 'coordinate': {'type': 'array', 'items': {'type': 'integer'}, 'minItems': 2, 'maxItems': 2}}, 'required': ['action'], 'additionalProperties': False}, 'pause_probe': {'type': 'boolean', 'description': 'Capture again after one second to test whether the frame is frozen.'}, 'resume_key': {'type': 'string', 'description': 'Optional key to unpause after the pause probe; compare the resumed frame.'}, 'dismiss_key': {'type': 'string', 'description': 'Optional key to dismiss a visible panel before performing this input, within this approval.'}}, ['run_id', 'intent', 'expected', 'action']),
    'playtest_read_value': ('Capture and magnify a fractional window region to read a HUD value.', {'run_id': {'type': 'string'}, 'region': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4, 'description': '[left, top, right, bottom] as fractions of the window'}, 'step': {'type': 'integer', 'minimum': 1, 'description': 'Optional recorded check to crop instead of the current window'}, 'frame': {'type': 'string', 'description': 'Recorded frame label, such as after or one second later; default after'}}, ['run_id', 'region']),
})

def invoke(name, args, ctx, **kwargs):
    from plugins.plugin_storage import plugin_data_dir
    try:
        pilot = Pilot(plugin_data_dir('game-lab-playtest'))
        if name == 'playtest_start':
            return start_ready(pilot, **args)
        if name == 'playtest_check':
            return check(pilot, **args)
        if name == 'playtest_read_value':
            return read_value(pilot, **args)
        if name == 'playtest_action':
            return perform(pilot, ctx, **args, **kwargs)
        if name == 'playtest_replay':
            return replay(pilot, ctx, **args, **kwargs)
        return json.dumps(getattr(pilot, name.removeprefix('playtest_'))(**args))
    except (ValueError, TypeError, OSError, KeyError, RuntimeError) as exc:
        return json.dumps({'error': str(exc)})

def replayable(action):
    if not isinstance(action, dict): raise ValueError('Invalid replay action')
    kind = action.get('action')
    fields = {
        'click': {'coordinate'}, 'double_click': {'coordinate'}, 'right_click': {'coordinate'},
        'middle_click': {'coordinate'}, 'drag': {'from_coordinate', 'to_coordinate'},
        'scroll': {'direction', 'amount'}, 'key': {'keys'}, 'wait': {'seconds'},
    }
    if kind not in fields or set(action) != fields[kind] | {'action'}:
        raise ValueError('Replay recording supports only explicit non-text actions with bounded fields')
    def coordinate(value):
        return isinstance(value, list) and len(value) == 2 and all(type(x) is int and 0 <= x <= 32768 for x in value)
    if kind in ('click', 'double_click', 'right_click', 'middle_click') and not coordinate(action['coordinate']): raise ValueError('Invalid replay coordinate')
    if kind == 'drag' and not all(coordinate(action[k]) for k in ('from_coordinate', 'to_coordinate')): raise ValueError('Invalid replay coordinate')
    if kind == 'scroll' and (action['direction'] not in ('up', 'down', 'left', 'right') or type(action['amount']) is not int or not 1 <= action['amount'] <= 30): raise ValueError('Invalid replay scroll')
    if kind == 'key' and action['keys'] not in ('up', 'down', 'left', 'right', 'escape', 'return', 'enter', 'tab', 'space'): raise ValueError('Only navigation keys can be recorded for replay')
    if kind == 'wait' and (type(action['seconds']) not in (int, float) or not math.isfinite(action['seconds']) or not 0 <= action['seconds'] <= 30): raise ValueError('Invalid replay wait')
    return dict(action)


HOLD_KEYS = re.compile(r'^(?:[A-Za-z0-9]|Left|Right|Up|Down|space|Return|Escape|Tab|Shift_L|Control_L|Alt_L)$')


def hold_spec(action):
    """Validate a hold action: up to three plain keys held together for 0.05 to 3 seconds."""
    if set(action) - {'action', 'keys', 'seconds', 'app', 'window_id', 'pid'}: raise ValueError('hold takes only keys and seconds')
    keys = action.get('keys'); seconds = action.get('seconds')
    keys = [keys] if isinstance(keys, str) else keys
    aliases = {k.lower(): k for k in ('Left', 'Right', 'Up', 'Down', 'space', 'Return', 'Escape', 'Tab', 'Shift_L', 'Control_L', 'Alt_L')}
    if isinstance(keys, list): keys = [aliases.get(k.lower(), k) if isinstance(k, str) else k for k in keys]
    if not isinstance(keys, list) or not 1 <= len(keys) <= 3 or not all(isinstance(k, str) and HOLD_KEYS.match(k) for k in keys):
        raise ValueError('hold needs one to three plain key names, for example ["Right", "space"] (letters, digits, arrows, space, Return, Escape, Tab)')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0.05 <= seconds <= 3: raise ValueError('hold seconds must be between 0.05 and 3')
    return keys, float(seconds)


def hold_keys(window_id, keys, seconds, run=subprocess.run, sleep=time.sleep, during=None):
    """Press the keys down on the focused target window, wait, release them (X11, xdotool). Keys are always released."""
    exe = shutil.which('xdotool')
    if not exe or not os.environ.get('DISPLAY'):
        raise ValueError('Holding a key needs an X11 display and xdotool on this computer; use tap actions instead')
    env = {'PATH': os.environ.get('PATH', os.defpath), 'DISPLAY': os.environ['DISPLAY']}
    def xdo(*args): return run([exe, *args], env=env, capture_output=True, timeout=10, check=False)
    if xdo('windowraise', str(window_id)).returncode or xdo('windowfocus', str(window_id)).returncode:
        raise RuntimeError('Could not raise and focus the selected game window; no keys were sent')
    pressed = []
    released = threading.Event()
    try:
        for key in keys:
            result = xdo('keydown', key)
            if result.returncode: raise RuntimeError('xdotool could not press ' + key)
            pressed.append(key)
        sleep(seconds / 4)
        captured = []
        def capture():
            try:
                value = during()
                captured.append((True, value, not released.is_set()))
            except Exception as exc: captured.append((False, exc))
        thread = threading.Thread(target=capture, daemon=True) if during else None
        if thread: thread.start()
        sleep(seconds * 3 / 4)
    finally:
        released.set()
        for key in reversed(pressed): xdo('keyup', key)
    if thread:
        thread.join(timeout=30)
        if not captured: raise RuntimeError('Capture timed out after releasing the keys')
        if not captured[0][0]: raise captured[0][1]
    return {'ok': True, 'action': 'hold', 'keys': keys, 'seconds': seconds, 'during': captured[0][1] if captured else None, 'during_completed_before_release': captured[0][2] if captured else None}


def grab_window(window_id, run=subprocess.run):
    """Grab the pixels of the target window (X11) as a small grayscale array, or None when that is not possible."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not os.environ.get('DISPLAY'): return None
    env = {'PATH': os.environ.get('PATH', os.defpath), 'DISPLAY': os.environ['DISPLAY']}
    try:
        out = run([ffmpeg, '-v', 'error', '-f', 'x11grab', '-window_id', str(window_id), '-i', os.environ['DISPLAY'],
                   '-frames:v', '1', '-vf', 'scale=320:-2,format=gray', '-f', 'rawvideo', '-'], env=env, capture_output=True, timeout=15, check=False).stdout
        import numpy
        width = 320; height = len(out) // width
        return numpy.frombuffer(out[:width * height], dtype=numpy.uint8).reshape(height, width).astype(numpy.int16) if height > 20 else None
    except (OSError, ValueError, KeyError, ImportError, subprocess.SubprocessError):
        return None


def shift_between(before, after):
    """(columns, zero_error, best_error, percent_changed, width) for two grayscale grabs, or None when they cannot be compared.
    columns > 0 means the whole picture slid LEFT by that many columns, < 0 to the right, 0 means no sideways slide was found."""
    try:
        import numpy
        if before is None or after is None or before.shape != after.shape: return None
        h, w = before.shape; limit = w // 3
        top = slice(0, int(h * 0.8))  # the lower strip often holds fixed interface; the scenery fills the rest
        zero = float(numpy.abs(before[top] - after[top]).mean())
        changed = float((numpy.abs(before - after) > 24).mean()) * 100
        best, best_error = 0, zero
        for s in range(-limit, limit + 1):
            if s == 0: continue
            a = before[top, max(s, 0):w + min(s, 0)]; b = after[top, max(-s, 0):w + min(-s, 0)]
            error = float(numpy.abs(a - b).mean())
            if error < best_error: best, best_error = s, error
        if not (best and best_error < zero * 0.85): best = 0
        return best, zero, best_error, changed, w
    except (ImportError, ValueError):
        return None


def scene_line(columns, width, changed, pairs=1):
    """The plain sentence for a total sideways slide of the picture (columns > 0 = to the left)."""
    if abs(columns) >= 0.02 * width:
        side = 'left' if columns > 0 else 'right'
        return ('Scene shift: the whole picture slid %d percent of its width to the %s (%.1f percent of the last picture differs). Scenery sliding %s '
                'means the viewpoint followed a character moving %s, even if the character stayed in the same place on screen.'
                % (round(100 * abs(columns) / width), side, changed, side, 'right' if side == 'left' else 'left'))
    if changed < 1.0: return 'Scene shift: the picture did not change (%.1f percent of it differs).' % changed
    return 'Scene shift: the picture changed (%.1f percent differs) but did not slide sideways as a whole; look at what changed.' % changed


def scene_shift(before, after):
    """One plain line saying how far the picture moved between two grabs (None when they cannot be compared)."""
    r = shift_between(before, after)
    return scene_line(r[0], r[4], r[3]) if r else None


def scene_track(frames):
    """Like scene_shift for a series of grabs taken during one action: add up the slide between neighbouring grabs, so a long scroll still counts."""
    frames = [f for f in frames if f is not None]
    steps = [shift_between(x, y) for x, y in zip(frames, frames[1:])]
    steps = [r for r in steps if r]
    if not steps: return None
    whole = shift_between(frames[0], frames[-1])
    return scene_line(sum(r[0] for r in steps), steps[0][4], whole[3] if whole else steps[-1][3], len(steps))


class Sampler:
    """Grab the window every quarter second on a side thread while an action runs (used to track scrolling during a hold)."""
    def __init__(self, window_id, grab=None):
        self.frames = []; self._stop = threading.Event(); self._grab = grab or grab_window; self._id = window_id
        self._thread = threading.Thread(target=self._run, daemon=True)
    def _run(self):
        while not self._stop.is_set():
            self.frames.append(self._grab(self._id)); self._stop.wait(0.2)
    def __enter__(self): self._thread.start(); return self
    def __exit__(self, *exc): self._stop.set(); self._thread.join(timeout=5)


def with_hint(result, hint):
    """Attach the scene-shift line to a tool result without disturbing image content."""
    if not hint: return result
    if isinstance(result, dict): return {**result, 'scene_shift': hint}
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict): return json.dumps({**parsed, 'scene_shift': hint})
        except ValueError: pass
    return result


def on_pre_tool_call(tool_name='', args=None, **kwargs):
    if tool_name == 'playtest_check':
        return {'action': 'approve', 'message': 'Playtest Pilot will focus the selected window and perform this check, including any dismissal or resume key: %s. Confirm.' % str({k: (args or {}).get(k) for k in ('action', 'dismiss_key', 'resume_key')}), 'rule_key': 'playtest-check'}
    action = (args or {}).get('action') if tool_name == 'playtest_action' else None
    if isinstance(action, dict) and action.get('action') == 'hold':
        return {'action': 'approve', 'message': 'Playtest Pilot: hold %s for %s seconds in the selected app window. This raises and focuses the window. Confirm.' % ('+'.join(map(str, action.get('keys') if isinstance(action.get('keys'), list) else [action.get('keys')])), action.get('seconds')), 'rule_key': 'playtest-hold'}
    return None


def perform(pilot, ctx, run_id, intent, expected, action, record_for_replay=False, **kwargs):
    if type(record_for_replay) is not bool: raise ValueError('record_for_replay must be boolean')
    recorded = replayable(action) if record_for_replay else None
    if not _action_lock.acquire(blocking=False):
        raise RuntimeError('Another Playtest Pilot action is in progress; wait for it to finish')
    try:
        return _perform(pilot, ctx, run_id, intent, expected, action, recorded, **kwargs)
    finally:
        _action_lock.release()


def _perform(pilot, ctx, run_id, intent, expected, action, recorded=None, **kwargs):
    if not isinstance(action, dict) or action.get('action') not in {'click', 'double_click', 'right_click', 'middle_click', 'drag', 'scroll', 'type', 'key', 'wait', 'hold'}:
        raise ValueError('Choose one supported computer-use action')
    if any(action.get(k) is not None for k in ('element', 'from_element', 'to_element')):
        raise ValueError('Element-index actions are unsupported after target recapture; use freshly observed coordinates')
    target = pilot.target(run_id)
    if str(action.get('app', target['app'])).casefold() != target['app'].casefold() or action.get('window_id', target['window_id']) != target['window_id']:
        raise ValueError('Action must target the selected app (%s) and window ID %d' % (target['app'], target['window_id']))
    session_id = kwargs.get('session_id') or getattr(kwargs.get('parent_agent'), 'session_id', None)
    if not isinstance(session_id, str) or not session_id:
        raise ValueError('A Hermes session ID is required for isolated computer use')
    context = {k: kwargs[k] for k in ('parent_agent', 'task_id') if k in kwargs}
    context['session_id'] = session_id
    # Native input uses the last captured target; do not run concurrent computer-use calls.
    # The native driver can only capture a window when it is given both pid and window_id.
    pid = action.get('pid')
    if pid is not None and (type(pid) is not int or pid < 1): raise ValueError('pid must be the positive process ID from computer_use list_windows')
    pid = pid if pid is not None else target.get('pid')
    preflight = ctx.dispatch_tool('computer_use', {**target, **({'pid': pid} if pid else {}), 'action': 'capture', 'mode': 'ax'}, **context)
    try: captured = json.loads(preflight) if isinstance(preflight, str) else preflight
    except (ValueError, TypeError): return preflight
    if not isinstance(captured, dict) or captured.get('error') or captured.get('ok') is False or captured.get('mode') != 'ax':
        return json.dumps({'error': 'Ready check failed: Hermes could not capture the selected game window. Check the window ID and PID, keep the game visible on the same X11 display, and try a software renderer with a TrueColor visual. No input was sent.', 'capture_result': captured})
    if action['action'] == 'hold': hold_spec(action)
    if action['action'] == 'wait' and (type(action.get('seconds')) not in (int, float) or not math.isfinite(action['seconds']) or not 0 <= action['seconds'] <= 30):
        raise ValueError('wait seconds must be between 0 and 30')
    step = pilot.begin(run_id, intent, expected, action['action'], recorded)
    try:
        # Input must reach the selected window: unless the caller chose a delivery mode, bring the window to the front
        # (separately approved by the user) so a game that ignores background events still receives the key.
        if action['action'] == 'hold':
            keys, seconds = hold_spec(action)
            look = lambda: ctx.dispatch_tool('computer_use', {**target, **({'pid': pid} if pid else {}), 'action': 'capture', 'mode': 'vision'}, **context)
            # The capture is requested a quarter of the way through the hold and returned as the result
            # (image-bearing result preserved) so the effect, such as a jump, is seen without extra calls.
            with Sampler(target['window_id']) as sampler:  # pictures of the window all through the hold, to follow a long scroll
                result = hold_keys(target['window_id'], keys, seconds, during=look)['during']
            hint = scene_track(sampler.frames + [grab_window(target['window_id'])])
            pilot.finish(run_id, step, 'acknowledged', hint)
            return with_hint(result, hint)
        if action['action'] == 'wait':
            seconds = action.get('seconds')
            time.sleep(seconds)
            result = ctx.dispatch_tool('computer_use', {**target, **({'pid': pid} if pid else {}), 'action': 'capture', 'mode': 'vision'}, **context)
            pilot.finish(run_id, step, 'acknowledged')
            return result
        delivery = {} if action.get('delivery_mode') else {'delivery_mode': 'foreground', 'bring_to_front': True}
        after = {} if action['action'] == 'wait' or 'capture_after' in action else {'capture_after': True}
        first = grab_window(target['window_id'])
        result = ctx.dispatch_tool('computer_use', {**delivery, **after, **action, 'app': target['app']}, **context)
    except BaseException:
        pilot.finish(run_id, step, 'unknown')
        raise
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
        if isinstance(parsed, dict) and isinstance(parsed.get('action_result'), dict):
            parsed = parsed['action_result']
        if not isinstance(parsed, dict):
            status = 'unknown'
        elif parsed.get('error') or parsed.get('ok') is False or parsed.get('success') is False or parsed.get('status') in ('blocked', 'denied', 'cancelled', 'error'):
            status = 'failed_or_denied'
        elif parsed.get('ok') is True or parsed.get('success') is True or parsed.get('status') in ('success', 'completed', 'ok'):
            status = 'acknowledged'
        else:
            status = 'unknown'
    except (ValueError, TypeError):
        status = 'unknown'
    hint = scene_shift(first, grab_window(target['window_id']) if first is not None else None)
    pilot.finish(run_id, step, status, hint)
    return with_hint(result, hint)


def capture_image(window_id):
    """Capture the visible X11 window through the root visual, including DirectColor windows."""
    try: from PIL import ImageGrab
    except ImportError: raise ValueError('Pillow with X11 capture support is required')
    exe = shutil.which('xdotool'); display = os.environ.get('DISPLAY')
    if not exe or not display: raise ValueError('Cannot capture: xdotool and an X11 display are required')
    env = {'PATH': os.environ.get('PATH', os.defpath), 'DISPLAY': display}
    try:
        proc = subprocess.run([exe, 'getwindowgeometry', '--shell', str(window_id)], env=env, capture_output=True, text=True, timeout=5, check=True)
        geometry = dict(line.split('=', 1) for line in proc.stdout.splitlines() if '=' in line)
        x, y, w, h = (int(geometry[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT'))
        screen = subprocess.run([exe, 'getdisplaygeometry'], env=env, capture_output=True, text=True, timeout=5, check=True).stdout.split()
        sw, sh = (int(v) for v in screen)
        if x < 0 or y < 0 or w < 1 or h < 1 or w * h > 32000000 or x + w > sw or y + h > sh: raise ValueError('Window must fit fully on the X display')
        image = ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=display).convert('RGB')
        if image.size != (w, h): raise ValueError('Incomplete window capture')
        return image
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        raise ValueError('Cannot capture selected window on this X display: %s' % exc) from exc


def is_black(image):
    from PIL import ImageStat
    return max(ImageStat.Stat(image.resize((32, 32))).mean) < 4


def focus_window(window):
    exe = shutil.which('xdotool')
    if not exe or not os.environ.get('DISPLAY'): raise ValueError('Cannot focus window: xdotool and an X11 display are required')
    env = {'PATH': os.environ.get('PATH', os.defpath), 'DISPLAY': os.environ['DISPLAY']}
    for command in ('windowraise', 'windowfocus'):
        if subprocess.run([exe, command, str(window)], env=env, capture_output=True, timeout=10).returncode: raise ValueError('Window not found or cannot be focused on this X display')


def visible_text(image):
    """Optional local OCR; text from a game is untrusted and may be wrong."""
    exe = shutil.which('tesseract')
    if not exe: return ''
    from PIL import ImageEnhance
    w, h = image.size
    centre = image.crop((w//20, h//6, 19*w//20, 5*h//6)).convert('L').resize((9*w//5, 4*h//3))
    centre = ImageEnhance.Contrast(centre).enhance(2)
    data = io.BytesIO(); centre.save(data, format='PNG')
    try:
        result = subprocess.run([exe, 'stdin', 'stdout', '--psm', '6'], input=data.getvalue(), capture_output=True, timeout=5)
        return result.stdout.decode('utf-8', 'replace')[:2000] if result.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError): return ''


def exclusive(function):
    @functools.wraps(function)
    def call(*args, **kwargs):
        if not _action_lock.acquire(blocking=False): raise RuntimeError('Another playtest action is in progress')
        try: return function(*args, **kwargs)
        finally: _action_lock.release()
    return call


@exclusive
def start_ready(pilot, app, scenario, window_id, pid=None):
    bounded(app, 'app', 200); bounded(scenario, 'scenario', 2000)
    if app.lower().strip() in ('screen', 'desktop'): raise ValueError('Select a specific application')
    if pid is not None and (type(pid) is not int or not 1 <= pid <= 2**32-1): raise ValueError('pid must be a positive process ID')
    # A stable capture means non-black frames of consistent geometry, not proof of gameplay.
    if type(window_id) is not int or not 1 <= window_id <= 2**32-1: raise ValueError('Select an exact application window ID')
    try: focus_window(window_id)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        return json.dumps({'ready': False, 'reason': str(exc), 'what_to_do': 'Select a visible game window on this X display. No input sent.'})
    deadline = time.monotonic() + 8
    reason = 'window not found or cannot capture this visual'
    previous = None
    while time.monotonic() < deadline:
        try:
            image = capture_image(window_id)
            if is_black(image): reason = 'still loading or black screen'; previous = None
            elif previous is not None and previous.size == image.size and measurements(previous, image)['changed_percent'] < 30:
                text = visible_text(image)
                keys = sorted(set(re.findall(r'\[([1-3])\]', text)))
                facts = {**pilot.start(app, scenario, window_id, pid), 'ready': True, 'notice': 'Non-black window captured twice; inspect it for title screens or loading overlays. If the model cannot see tool images, visual verdicts remain unverified.'}
                if len(keys) >= 2:
                    facts.update(panel_hint=True, visible_text_untrusted=text, suggested_keys_from_ocr=keys, overlay_suggestion='A choice panel may be blocking gameplay; inspect the displayed keys and dismiss it before testing movement.')
                return image_result([('ready window', image)], facts)
            else: previous = image
        except (ValueError, OSError, subprocess.SubprocessError): previous = None
        time.sleep(0.5)
    return json.dumps({'ready': False, 'reason': reason, 'what_to_do': 'Check the selected window and display; wait for loading or try a software renderer, then start again. No input sent.'})


def image_result(images, facts, max_width=320):
    blocks = [{'type': 'text', 'text': json.dumps(facts)}]
    for label, image in images:
        output = io.BytesIO()
        shown = image.copy()
        if max_width and shown.width > max_width: shown.thumbnail((max_width, max_width * shown.height // shown.width))
        shown.convert('RGB').save(output, format='JPEG', quality=70, optimize=True)
        blocks.extend([{'type': 'text', 'text': label}, {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()}}])
    return {'_multimodal': True, 'content': blocks, 'text_summary': json.dumps(facts), 'action_result': facts}


def measurements(before, after):
    from PIL import ImageChops, ImageStat
    if before.size != after.size: raise ValueError('Window size changed during the check')
    diff = ImageChops.difference(before, after).convert('L')
    hist = diff.histogram(); changed = 100 * sum(hist[25:]) / (before.width * before.height)
    # A large uniform centre is only a panel hint, not a reliable classifier.
    def panel(im):
        gray = im.convert('L').resize((80, 60), resample=0)
        centre = ImageStat.Stat(gray.crop((20, 15, 60, 45))).stddev[0]
        edge = ImageStat.Stat(gray).stddev[0]
        return centre < 18 and edge > centre + 8
    a, b = panel(before), panel(after)
    # Pillow's C-backed difference handles scroll measurement without a NumPy dependency.
    w = 160; h = max(2, round(before.height * w / before.width))
    image_a = before.convert('L').resize((w, h)).crop((0, 0, w, max(1, int(h * .8))))
    image_b = after.convert('L').resize((w, h)).crop((0, 0, w, max(1, int(h * .8))))
    zero = ImageStat.Stat(ImageChops.difference(image_a, image_b)).mean[0]
    best, best_error = 0, zero
    for shift in range(-w // 3, w // 3 + 1):
        if not shift: continue
        left = max(shift, 0); right = w + min(shift, 0)
        aa = image_a.crop((left, 0, right, image_a.height)); bb = image_b.crop((max(-shift, 0), 0, w + min(-shift, 0), image_b.height))
        error = ImageStat.Stat(ImageChops.difference(aa, bb)).mean[0]
        if error < best_error: best, best_error = shift, error
    if best_error >= zero * .85 or zero < 3 or changed < 1: best = 0
    pixels = round(best * before.width / w)
    if pixels: reading = 'Scene scrolled %d px %s; inspect the frames to confirm movement.' % (abs(pixels), 'left' if pixels > 0 else 'right')
    else: reading = '%.1f%% of the screen changed; no reliable horizontal scroll detected.' % changed
    return {'changed_percent': round(changed, 2), 'scene_scroll_pixels': pixels, 'scroll_direction': ('left' if pixels > 0 else 'right' if pixels < 0 else None), 'panel_before_hint': a, 'panel_after_hint': b, 'panel_change': 'appeared' if b and not a else 'disappeared' if a and not b else 'unchanged', 'reading': reading, **({'overlay_suggestion': 'A centred panel may be blocking input; inspect the displayed keys and check again with the appropriate dismiss key.'} if changed < 1 and b else {})}


def check(pilot, run_id, intent, expected, action, pause_probe=False, resume_key=None, dismiss_key=None):
    if not _action_lock.acquire(blocking=False): raise RuntimeError('Another playtest action is in progress')
    step = None
    try:
        target = pilot.target(run_id); window = target['window_id']
        if type(pause_probe) is not bool: raise ValueError('pause_probe must be boolean')
        for key in (resume_key, dismiss_key):
            if key is not None: hold_spec({'action': 'hold', 'keys': key, 'seconds': 0.08})
        if resume_key and not pause_probe: raise ValueError('resume_key requires pause_probe')
        if not isinstance(action, dict): raise ValueError('Action must be an object')
        if set(action) == {'key'}: action = {'action': 'key', 'keys': action['key']}
        if 'action' in action and 'type' in action: raise ValueError('Use either action or type, not both')
        kind = action.get('action', action.get('type'))
        if kind in ('key', 'hold'):
            if set(action) - {'action', 'type', 'keys', 'seconds'}: raise ValueError('Unexpected key action fields')
            keys, seconds = hold_spec({'action': 'hold', 'keys': action.get('keys'), 'seconds': action.get('seconds', 0.08)})
        elif kind == 'click':
            if set(action) not in ({'action', 'coordinate'}, {'type', 'coordinate'}): raise ValueError('Unexpected click action fields')
            coordinate = action.get('coordinate')
            if not isinstance(coordinate, list) or len(coordinate) != 2 or not all(type(v) is int and v >= 0 for v in coordinate): raise ValueError('click needs nonnegative window coordinates')
        else: raise ValueError('Choose key, hold or click')
        exe = shutil.which('xdotool')
        if not exe: raise ValueError('xdotool is required')
        env = {'PATH': os.environ.get('PATH', os.defpath), 'DISPLAY': os.environ['DISPLAY']}
        for command in ('windowraise', 'windowfocus'):
            if subprocess.run([exe, command, str(window)], env=env, capture_output=True, timeout=10).returncode: raise RuntimeError('Could not raise and focus selected game window')
        initial = capture_image(window)
        if kind == 'click' and not (coordinate[0] < initial.width and coordinate[1] < initial.height): raise ValueError('Click is outside the selected window')
        step = pilot.begin(run_id, intent, expected, kind)
        pre_dismiss = initial if dismiss_key else None
        if dismiss_key:
            hold_keys(window, hold_spec({'action': 'hold', 'keys': dismiss_key, 'seconds': 0.08})[0], 0.08)
            before = capture_image(window)
        else: before = initial
        if kind in ('key', 'hold'):
            held = hold_keys(window, keys, seconds, during=lambda: capture_image(window))
            during = held['during']
        else:
            exe = shutil.which('xdotool')
            if not exe: raise ValueError('xdotool is required')
            env = {'PATH': os.environ.get('PATH', os.defpath), 'DISPLAY': os.environ['DISPLAY']}
            for args in (['windowraise', str(window)], ['windowfocus', str(window)], ['mousemove', '--window', str(window), *map(str, coordinate)], ['click', '1']):
                if subprocess.run([exe, *args], env=env, capture_output=True, timeout=10).returncode: raise RuntimeError('Could not focus or click selected window')
            during = capture_image(window)
        after = capture_image(window); facts = measurements(before, after)
        if kind in ('key', 'hold') and facts['scene_scroll_pixels']:
            side = facts['scroll_direction']; motion = 'right' if side == 'left' else 'left'
            facts['reading'] = 'Scene scrolled %d px %s while %s was held: consistent with moving %s.' % (abs(facts['scene_scroll_pixels']), side, '+'.join(keys), motion)
        images = ([('before dismissal', pre_dismiss)] if pre_dismiss else []) + [('before', before), ('during', during), ('after', after)]
        if pre_dismiss: facts['dismissal'] = measurements(pre_dismiss, before)
        if facts['panel_after_hint'] or facts['changed_percent'] < 2:
            text = visible_text(after)
            if text:
                visible_keys = sorted(set(re.findall(r'\[([1-3])\]', text)))
                if re.search(r'\b(?:[cg]ontinue|resume|select|choose|level up|abort)\b', text, re.I) or len(visible_keys) >= 2:
                    facts['visible_text_untrusted'] = text
                    facts['panel_after_hint'] = True
                    if facts['changed_percent'] < 1: facts['panel_before_hint'] = True
                    facts['panel_change'] = 'unchanged (OCR hint)' if facts['panel_before_hint'] else 'unknown (OCR hint only)'
                    if visible_keys: facts['suggested_keys_from_ocr'] = visible_keys
                    facts['overlay_suggestion'] = 'A panel may be blocking input; inspect the untrusted visible text and image, then dismiss using a displayed key.'
        if pause_probe:
            time.sleep(1); later = capture_image(window); facts['frozen_one_second'] = after.tobytes() == later.tobytes(); images.append(('one second later', later))
            if resume_key:
                hold_keys(window, hold_spec({'action': 'hold', 'keys': resume_key, 'seconds': 0.08})[0], 0.08); resumed = capture_image(window); time.sleep(1); resumed_later = capture_image(window)
                facts['changed_after_resume'] = resumed.tobytes() != resumed_later.tobytes(); images.extend([('after resume', resumed), ('resume one second later', resumed_later)])
        evidence = []
        for number, (label, picture) in enumerate(images):
            path = pilot.root / ('%s-step%d-frame%d.png' % (run_id, step, number))
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out:
                picture.save(out, format='PNG')
            evidence.append({'label': label, 'file': path.name})
        facts['evidence'] = evidence
        facts['input'] = ({'action': kind, 'keys': keys, 'seconds': seconds} if kind in ('key', 'hold') else {'action': kind, 'coordinate': coordinate})
        if dismiss_key: facts['dismiss_key'] = dismiss_key
        if resume_key: facts['resume_key'] = resume_key
        facts['vision_required'] = 'Inspect the returned images; if the active model cannot see tool images, report visual verdicts as unverified.'
        facts['step'] = step
        facts['during_completed_before_release'] = held.get('during_completed_before_release') if kind in ('key', 'hold') else None
        facts['capture_timing'] = 'A during capture that did not complete before release may show a later moment.'
        pilot.finish(run_id, step, 'acknowledged', facts=facts)
        return image_result(images, facts)
    except BaseException:
        if step is not None: pilot.finish(run_id, step, 'unknown')
        raise
    finally: _action_lock.release()


@exclusive
def read_value(pilot, run_id, region, step=None, frame="after"):
    if not isinstance(region, list) or len(region) != 4 or not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in region) or region[0] >= region[2] or region[1] >= region[3]: raise ValueError('region must be [left, top, right, bottom] fractions in ascending order')
    window = pilot.target(run_id)['window_id']
    if step is None:
        focus_window(window); image = capture_image(window)
    else:
        try: from PIL import Image
        except ImportError: raise ValueError('Pillow is required to read saved frames')
        if type(step) is not int or step < 1 or not isinstance(frame, str): raise ValueError('Invalid recorded step or frame')
        steps = pilot.load(run_id)['steps']
        if step > len(steps): raise ValueError('Step not found')
        entries = steps[step-1].get('facts', {}).get('evidence', [])
        match = next((e['file'] for e in entries if e.get('label') == frame), None)
        if not isinstance(match, str) or not match.startswith('%s-step%d-frame' % (run_id, step)) or Path(match).name != match: raise ValueError('Recorded frame not found')
        fd = os.open(pilot.root / match, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as source:
            if os.fstat(source.fileno()).st_size > 32 * 1024 * 1024: raise ValueError('Recorded frame is too large')
            image = Image.open(source).convert('RGB')
    w, h = image.size
    requested = (int(region[0]*w), int(region[1]*h), int(region[2]*w), int(region[3]*h))
    margin_x, margin_y = max(1, w//50), max(1, h//50)
    box = (max(0, requested[0]-margin_x), max(0, requested[1]-margin_y), min(w, requested[2]+margin_x), min(h, requested[3]+margin_y))
    crop = image.crop(box)
    if not crop.width or not crop.height: raise ValueError('Region is too small')
    if crop.width * crop.height > min(w * h // 6, 200000): raise ValueError('Select a smaller HUD region')
    enlarged = crop.resize((crop.width*4, crop.height*4), resample=0)
    text = ''
    exe = shutil.which('tesseract')
    if exe:
        data = io.BytesIO(); enlarged.save(data, format='PNG')
        try:
            result = subprocess.run([exe, 'stdin', 'stdout', '--psm', '6'], input=data.getvalue(), capture_output=True, timeout=5)
            if result.returncode == 0: text = result.stdout.decode('utf-8', 'replace')[:2000]
        except (OSError, subprocess.SubprocessError): pass
    return image_result([('magnified region', enlarged)], {'region': region, 'source_pixels': box, 'ocr_text_untrusted': text, 'step': step, 'frame': frame if step else 'current'}, max_width=None)


def replay(pilot, ctx, run_id, source_run_id, source_step, **kwargs):
    if run_id == source_run_id or type(source_step) is not int or source_step < 1:
        raise ValueError('Choose a source step and a separate target run')
    if not _action_lock.acquire(blocking=False): raise RuntimeError('Another Playtest Pilot action is in progress; wait for it to finish')
    try:
        source, target = pilot.load(source_run_id), pilot.load(run_id)
        if source.get('app') != target.get('app'): raise ValueError('Replay runs must target the same named app')
        if source_step > len(source['steps']): raise ValueError('Source step not found')
        step = source['steps'][source_step-1]
        observation = step.get('observation')
        if step.get('acknowledgment') != 'acknowledged' or not isinstance(observation, dict) or observation.get('status') not in ('passed', 'failed'):
            raise ValueError('Source action must be acknowledged and observed before replay')
        if target['steps']:
            last = target['steps'][-1].get('observation')
            if not isinstance(last, dict) or last.get('status') not in ('passed', 'failed'):
                raise ValueError('Observe the previous target action before continuing replay')
        action = replayable(step.get('replay_action'))
        return _perform(pilot, ctx, run_id, step['intent'], step['expected'], action, action, **kwargs)
    finally:
        _action_lock.release()

def register(ctx):
    if hasattr(ctx, 'register_hook'): ctx.register_hook('pre_tool_call', on_pre_tool_call)
    if hasattr(ctx, 'register_skill'):
        from pathlib import Path
        ctx.register_skill('playtest-pilot', Path(__file__).parents[2] / 'skills/playtest-pilot/SKILL.md', description='Record observed playtest actions for a selected application')
    for name, (description, properties, required) in TOOLS.items():
        ctx.register_tool(name=name, toolset='playtest_pilot', schema={'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}},
            handler=lambda args, _name=name, **kwargs: invoke(_name, args, ctx, **kwargs))
