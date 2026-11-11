"""Private playtest receipts; no automatic success inference or replay."""
try:
    import fcntl
except ImportError:
    fcntl = None
import json
import os
from pathlib import Path
import uuid


def bounded(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(label + ' must be nonempty and bounded')


def require_posix():
    if fcntl is None: raise ValueError('Playtest Pilot requires X11 and POSIX locking')


class Pilot:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, run_id):
        if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id): raise ValueError('Invalid run ID')
        p = self.root / (run_id + '.json')
        if p.is_symlink(): raise ValueError('Invalid run path')
        return p

    def load(self, run_id):
        return json.loads(self.path(run_id).read_text())

    def save(self, run_id, value):
        temp = self.root / (uuid.uuid4().hex + '.tmp')
        try:
            with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f: json.dump(value, f)
            os.replace(temp, self.path(run_id))
        finally: temp.unlink(missing_ok=True)

    def start(self, app, scenario, window_id, pid=None):
        require_posix()
        bounded(app, 'app', 200)
        bounded(scenario, 'scenario', 2000)
        if app.lower().strip() in ('screen', 'desktop'): raise ValueError('Select a specific application')
        if type(window_id) is not int or not 1 <= window_id <= 2**32-1: raise ValueError('Select an exact application window ID')
        if pid is not None and (type(pid) is not int or not 1 <= pid <= 2**32-1): raise ValueError('pid must be a positive process ID')
        display = os.environ.get('DISPLAY')
        if not display: raise ValueError('An X11 display is required')
        run_id = uuid.uuid4().hex
        self.save(run_id, {'app': app, 'scenario': scenario, 'window_id': window_id, 'display': display, 'steps': [], **({'pid': pid} if pid else {})})
        return {'run_id': run_id, 'app': app, 'window_id': window_id}

    def target(self, run_id):
        require_posix()
        data = self.load(run_id)
        if data.get('display') != os.environ.get('DISPLAY'):
            raise ValueError('The playtest and computer-use session must use the same X11 display')
        return {'app': data['app'], 'window_id': data['window_id'], **({'pid': data['pid']} if data.get('pid') else {})}

    def begin(self, run_id, intent, expected, action_type, replay_action=None):
        require_posix()
        bounded(intent, 'intent', 500)
        bounded(expected, 'expected outcome', 500)
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.load(run_id)
            if len(data['steps']) >= 1000: raise ValueError('Run exceeds 1000 steps')
            if data['steps'] and (data['steps'][-1]['acknowledgment'] == 'pending' or (data['steps'][-1]['acknowledgment'] == 'unknown' and data['steps'][-1]['observation'] is None)):
                raise ValueError('A prior action is unresolved; do not replay automatically')
            entry = {'intent': intent, 'expected': expected, 'action_type': action_type, 'acknowledgment': 'pending', 'observation': None}
            if replay_action is not None: entry['replay_action'] = replay_action
            data['steps'].append(entry)
            self.save(run_id, data)
            return len(data['steps'])

    def finish(self, run_id, step, status, scene_shift=None):
        require_posix()
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.load(run_id)
            data['steps'][step-1]['acknowledgment'] = status
            if scene_shift: data['steps'][step-1]['scene_shift'] = scene_shift
            self.save(run_id, data)

    def observe(self, run_id, step, status, note):
        require_posix()
        bounded(note, 'observation', 2000)
        if type(step) is not int or step < 1 or status not in ('passed', 'failed', 'uncertain'): raise ValueError('Invalid step or observation status')
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.load(run_id)
            if step > len(data['steps']): raise ValueError('Step not found')
            data['steps'][step-1]['observation'] = {'status': status, 'note': note}
            self.save(run_id, data)
        return {'step': step, 'status': status}

    def report(self, run_id):
        data = self.load(run_id)
        return {**data, 'notice': 'Action acknowledgments and recorded observations are distinct; no automatic gameplay verification is performed.'}
