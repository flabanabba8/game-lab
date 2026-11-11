import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from .core import Pilot

_action_lock = threading.Lock()

TOOLS = {
    'playtest_start': ('Start an explicitly authorized playtest for one named application with a scenario description.', {'app': {'type': 'string'}, 'scenario': {'type': 'string'}, 'window_id': {'type': 'integer', 'minimum': 1}, 'pid': {'type': 'integer', 'minimum': 1, 'description': 'Process ID of that window, from computer_use list_windows; needed so the window can be captured before each action'}}, ['app', 'scenario', 'window_id']),
    'playtest_action': ('Perform ONE native computer-use action on the selected app. Optionally record a restricted non-text action for explicit step-by-step replay. Host approvals remain in force; observations are separate.', {'run_id': {'type': 'string'}, 'intent': {'type': 'string'}, 'expected': {'type': 'string'}, 'action': {'type': 'object', 'description': 'The native computer_use action as an object, for example {"action": "key", "keys": "Right"} or {"action": "key", "keys": "space", "delivery_mode": "foreground", "bring_to_front": true}. Do not wrap it again and do not repeat run_id or app inside it. For movement or jumps in an action game use {"action": "hold", "keys": ["Right"], "seconds": 1.5} (up to three keys together, at most 3 seconds): a tap is too short for a game that reads held keys, and the same goes for Escape or a pause key during play (hold it 0.3 seconds). A hold returns a capture taken a quarter of the way through, while the keys are still down. Every input action returns a fresh capture of the window; its pixel size is in the result and click coordinates use that frame.'}, 'record_for_replay': {'type': 'boolean'}}, ['run_id', 'intent', 'expected', 'action']),
    'playtest_replay': ('Replay one explicitly selected, previously observed non-text action into a separate run of the same named app. Verify coordinates and state first; host approvals remain in force.', {'run_id': {'type': 'string'}, 'source_run_id': {'type': 'string'}, 'source_step': {'type': 'integer', 'minimum': 1}}, ['run_id', 'source_run_id', 'source_step']),
    'playtest_observe': ('Record a user/agent observation after inspecting actual game state. The result is a human observation, not automatic proof.', {'run_id': {'type': 'string'}, 'step': {'type': 'integer', 'minimum': 1}, 'status': {'type': 'string', 'enum': ['passed', 'failed', 'uncertain']}, 'note': {'type': 'string'}}, ['run_id', 'step', 'status', 'note']),
    'playtest_report': ('Read playtest intentions, action acknowledgment and separately recorded observations.', {'run_id': {'type': 'string'}}, ['run_id']),
}

def invoke(name, args, ctx, **kwargs):
    from plugins.plugin_storage import plugin_data_dir
    try:
        pilot = Pilot(plugin_data_dir('game-lab-playtest'))
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
    xdo('windowraise', str(window_id)); xdo('windowfocus', str(window_id))
    pressed = []
    try:
        for key in keys:
            result = xdo('keydown', key)
            if result.returncode: raise RuntimeError('xdotool could not press ' + key)
            pressed.append(key)
        sleep(seconds / 4)
        seen = during() if during else None  # look at the window early, while the keys are still down (for example Tux in the air)
        sleep(seconds * 3 / 4)
    finally:
        for key in reversed(pressed): xdo('keyup', key)
    return {'ok': True, 'action': 'hold', 'keys': keys, 'seconds': seconds, 'during': seen}


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
        return preflight
    if action['action'] == 'hold': hold_spec(action)
    step = pilot.begin(run_id, intent, expected, action['action'], recorded)
    try:
        # Input must reach the selected window: unless the caller chose a delivery mode, bring the window to the front
        # (separately approved by the user) so a game that ignores background events still receives the key.
        if action['action'] == 'hold':
            keys, seconds = hold_spec(action)
            look = lambda: ctx.dispatch_tool('computer_use', {**target, **({'pid': pid} if pid else {}), 'action': 'capture', 'mode': 'vision'}, **context)
            # The capture is taken a quarter of the way through the hold, while the keys are down, and returned as the result
            # (image-bearing result preserved) so the effect, such as a jump, is seen without extra calls.
            with Sampler(target['window_id']) as sampler:  # pictures of the window all through the hold, to follow a long scroll
                result = hold_keys(target['window_id'], keys, seconds, during=look)['during']
            hint = scene_track(sampler.frames + [grab_window(target['window_id'])])
            pilot.finish(run_id, step, 'acknowledged', hint)
            return with_hint(result, hint)
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
