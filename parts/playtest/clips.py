"""Short clips of failed playtest checks, cut from what the run already captured.

Playtest saves a few screenshots per check and now records when each was taken. A clip is a slideshow of those frames, each
held for the time that really passed before the next one, with the check name, what was expected and what was seen on a caption
bar. It is "frames from the run", not full-motion video. If the person has their own screen recording of the run (a file plus the
wall-clock time it started), the clip is cut from that file instead. Nothing here records the screen, and nothing is uploaded.
"""
import datetime
import os
import re
import shutil
import subprocess
import tempfile

DEFAULT_BEFORE = 3.0
DEFAULT_AFTER = 1.5
MAX_BEFORE = 30.0
MAX_AFTER = 15.0
MIN_HOLD = 0.5            # the last frame of a run is held at least this long
MAX_WIDTH = 1280
FPS = 25
EVIDENCE_NAME = re.compile(r'^[0-9a-f]{32}-batch\d+-frame\d+\.png$')
NO_FFMPEG = 'ffmpeg was not found on this computer, so no clips were made. The report and saved frames are complete; install ffmpeg to get video of failed checks.'
FONTS = ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf', 'LiberationSans-Regular.ttf')


def slug(text, fallback='check'):
    """File-name-safe ASCII from untrusted game data: no separators, dots or control characters."""
    text = re.sub(r'[^A-Za-z0-9]+', '-', str(text)).strip('-')[:40].strip('-')
    return text or fallback


def clean_text(text, limit=300):
    """Drop control characters from text that will be drawn; keep it short."""
    return ''.join(c if c.isprintable() else ' ' for c in str(text)).strip()[:limit]


def seconds(value, label, default, cap):
    if value is None: return default
    if type(value) not in (int, float) or isinstance(value, bool) or value != value or not 0 <= value <= cap:
        raise ValueError('%s must be a number from 0 to %g seconds' % (label, cap))
    return float(value)


def epoch(value):
    """Wall-clock start of a recording: seconds since 1970, or an ISO 8601 time with a zone."""
    if isinstance(value, bool): raise ValueError('recording start_time must be a time')
    if isinstance(value, (int, float)):
        if value != value or value < 1e9: raise ValueError('recording start_time must be seconds since 1970 or an ISO 8601 time')
        return float(value)
    if isinstance(value, str):
        try: moment = datetime.datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError: raise ValueError('recording start_time must be seconds since 1970 or an ISO 8601 time') from None
        if moment.tzinfo is None: raise ValueError('recording start_time needs a time zone, for example 2026-11-13T10:15:00+00:00')
        return moment.timestamp()
    raise ValueError('recording start_time must be a time')


def ffmpeg_run(program, args):
    done = subprocess.run([program, '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe', *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, env={'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C'}, check=False)
    if done.returncode:
        lines = done.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise RuntimeError('ffmpeg could not make the clip: ' + (lines[-1][:200] if lines else 'unknown error'))


def probe(program, path):
    """Width, height and duration of a recording, read from ffmpeg's own description of it."""
    done = subprocess.run([program, '-nostdin', '-protocol_whitelist', 'file', '-i', path], stdin=subprocess.DEVNULL, capture_output=True,
                          env={'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C'}, check=False)
    text = done.stderr.decode('utf-8', 'replace')
    size = re.search(r'Video:.*?[ ,](\d{2,5})x(\d{2,5})[ ,\[]', text)
    length = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if not size: raise ValueError('The recording has no video that ffmpeg can read')
    total = int(length.group(1)) * 3600 + int(length.group(2)) * 60 + float(length.group(3)) if length else None
    return int(size.group(1)), int(size.group(2)), total


def font(size):
    from PIL import ImageFont
    for name in FONTS:
        try: return ImageFont.truetype(name, size)
        except OSError: continue
    return ImageFont.load_default(size=size)


def wrap(draw, text, face, width, lines):
    """Break text to at most this many lines of this pixel width; the last line ends in ... when cut."""
    words, out, line = text.split(), [], ''
    for word in words:
        trial = (line + ' ' + word).strip()
        if draw.textlength(trial, font=face) <= width or not line: line = trial
        else: out.append(line); line = word
    if line: out.append(line)
    if len(out) > lines:
        out = out[:lines]
        while out[-1] and draw.textlength(out[-1] + '...', font=face) > width: out[-1] = out[-1][:-1]
        out[-1] += '...'
    for i, one in enumerate(out):
        while len(one) > 1 and draw.textlength(one, font=face) > width: one = one[:-2] + '.'
        out[i] = one
    return out or ['']


def caption_bar(width, title, tag, expected, seen):
    """A dark bar the full width of the clip: the check name, what was expected and what was seen."""
    from PIL import Image, ImageDraw
    size = max(13, width // 48)
    face, small = font(size), font(max(11, size - 3))
    probe_draw = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    pad = size // 2
    inner = width - 2 * pad
    rows = [(title, face, (255, 255, 255), 1), ('expected: ' + expected, face, (200, 230, 255), 2), ('seen: ' + seen, face, (255, 220, 160), 2)]
    laid = [(wrap(probe_draw, clean_text(text), f, inner, n), f, colour) for text, f, colour, n in rows]
    line_h = int(size * 1.3)
    height = pad * 2 + line_h * sum(len(lines) for lines, _, _ in laid) + line_h // 2
    height += height % 2
    bar = Image.new('RGB', (width, height), (14, 16, 22))
    draw = ImageDraw.Draw(bar)
    y = pad
    for lines, f, colour in laid:
        for one in lines:
            draw.text((pad, y), one, font=f, fill=colour); y += line_h
    draw.text((pad, height - small.size - pad // 2 - 2), clean_text(tag), font=small, fill=(150, 160, 175))
    return bar


def frame_on_canvas(image, canvas, bar):
    from PIL import Image
    width, height = canvas
    fit = min(width / image.width, height / image.height)
    scaled = image.convert('RGB').resize((max(1, int(image.width * fit)), max(1, int(image.height * fit))))
    out = Image.new('RGB', (width, height + bar.height), (0, 0, 0))
    out.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
    out.paste(bar, (0, height))
    return out


def timeline(data, root):
    """Every saved evidence frame of the run as (seconds since 1970, path), in time order, one frame per moment."""
    frames = []
    for entry in data.get('batch_results', []):
        times = entry.get('frame_times') or []
        for name, moment in zip(entry.get('evidence', []), times):
            if isinstance(name, str) and EVIDENCE_NAME.match(name) and type(moment) in (int, float) and (root / name).is_file() and not (root / name).is_symlink():
                frames.append((float(moment), root / name))
    frames.sort(key=lambda item: item[0])
    out = []
    for moment, path in frames:
        if out and moment - out[-1][0] < 0.001: continue     # a magnified copy of the same capture
        out.append((moment, path))
    return out


def window(frames, moment, before, after, run_end):
    """Clip start and end (seconds since 1970): wanted span capped to the run's first frame and its end."""
    start = max(moment - before, frames[0][0])
    end = min(moment + after, max(run_end, frames[-1][0] + MIN_HOLD))
    if end < moment + min(after, MIN_HOLD): end = moment + min(after, MIN_HOLD)
    return start, max(end, start + 0.1)


def segments(frames, start, end):
    """(path, seconds held) for each frame visible between start and end, each held until the next one appears."""
    shown = [i for i, (moment, _) in enumerate(frames) if moment < end]
    first = max([i for i in shown if frames[i][0] <= start] or [shown[0]])
    out = []
    for i in range(first, shown[-1] + 1):
        begin = max(frames[i][0], start)
        stop = min(frames[i + 1][0], end) if i + 1 < len(frames) else end
        if stop - begin > 0: out.append((frames[i][1], stop - begin))
    return out


def encode_frames(program, parts, canvas, bar, target):
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix='playtest-clip-') as work:
        lines = []
        for n, (path, held) in enumerate(parts):
            with Image.open(path) as image: composed = frame_on_canvas(image, canvas, bar)
            composed.save(os.path.join(work, 'f%03d.png' % n))
            lines.append("file 'f%03d.png'\nduration %.4f" % (n, held))
        lines.append("file 'f%03d.png'" % (len(parts) - 1))       # the demuxer needs the last file repeated for its duration to count; -t trims the extra frame
        listing = os.path.join(work, 'list.txt')
        with open(listing, 'w') as out: out.write('\n'.join(lines) + '\n')
        ffmpeg_run(program, ['-y', '-f', 'concat', '-safe', '0', '-i', listing, '-vf', 'fps=%d,format=yuv420p' % FPS, '-t', '%.4f' % sum(held for _, held in parts), '-an', '-c:v', 'libx264',
                             '-preset', 'veryfast', '-crf', '23', '-movflags', '+faststart', str(target)])


def encode_recording(program, recording, offset, length, size, bar, target):
    with tempfile.TemporaryDirectory(prefix='playtest-clip-') as work:
        bar_path = os.path.join(work, 'bar.png'); bar.save(bar_path)
        w, h = size
        graph = '[0:v]scale=%d:%d,setsar=1[v];[v][1:v]vstack,fps=%d,format=yuv420p' % (w, h, FPS)
        ffmpeg_run(program, ['-y', '-ss', '%.3f' % offset, '-t', '%.3f' % length, '-i', recording, '-i', bar_path, '-filter_complex', graph, '-an', '-c:v', 'libx264',
                             '-preset', 'veryfast', '-crf', '23', '-movflags', '+faststart', str(target)])


def encode_reel(program, files, size, target):
    with tempfile.TemporaryDirectory(prefix='playtest-reel-') as work:
        listing = os.path.join(work, 'list.txt')
        with open(listing, 'w') as out: out.write(''.join("file '%s'\n" % str(f).replace("'", "'\\''") for f in files))
        w, h = size
        ffmpeg_run(program, ['-y', '-f', 'concat', '-safe', '0', '-i', listing, '-vf', 'scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%d,format=yuv420p' % (w, h, w, h, FPS),
                             '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-movflags', '+faststart', str(target)])


def canvas_for(image):
    scale = min(1.0, MAX_WIDTH / image.width)
    w, h = int(image.width * scale), int(image.height * scale)
    return w - w % 2 or 2, h - h % 2 or 2


def make_clips(pilot, run_id, checks=None, before_seconds=None, after_seconds=None, reel=True, recording=None, automatic=False):
    """Cut a clip for each failed check (or each check named in `checks`) of a finished playtest_run. Returns a plain dict.

    automatic=True is the call playtest_run makes itself: it returns None when nothing failed so a clean run produces nothing.
    """
    from PIL import Image
    before = seconds(before_seconds, 'before_seconds', DEFAULT_BEFORE, MAX_BEFORE)
    after = seconds(after_seconds, 'after_seconds', DEFAULT_AFTER, MAX_AFTER)
    if type(reel) is not bool: raise ValueError('reel must be true or false')
    data = pilot.load(run_id)
    entries = data.get('batch_results')
    if not isinstance(entries, list): raise ValueError('This run has no playtest_run results; clips are cut from a finished playtest_run')
    if checks is not None:
        if not isinstance(checks, list) or not checks or len(checks) > 20 or not all(isinstance(c, str) for c in checks): raise ValueError('checks must be a list of 1 to 20 check names')
        chosen = [i for i, e in enumerate(entries) if e.get('name') in checks]
        missing = [c for c in checks if c not in [e.get('name') for e in entries]]
    else:
        chosen = [i for i, e in enumerate(entries) if e.get('verdict') == 'FAIL']; missing = []
    if automatic and not chosen: return None
    result = {'run_id': run_id, 'method': 'frames from the run', 'clips': [], 'skipped': [{'check': name, 'reason': 'no check with this name in the run'} for name in missing]}
    if not chosen:
        result['message'] = 'No failed checks in this run, so no clips were made.' if checks is None else 'None of the named checks exist in this run.'
        return result
    program = shutil.which('ffmpeg')
    if not program:
        result['ffmpeg'] = None; result['message'] = NO_FFMPEG
        return save(pilot, run_id, data, entries, result)
    source = None
    if recording is not None:
        if not isinstance(recording, dict) or set(recording) - {'path', 'start_time'} or not recording.get('path'): raise ValueError('recording needs path and start_time')
        path = os.path.abspath(os.path.expanduser(str(recording['path'])))
        if not os.path.isfile(path): raise ValueError('The recording file was not found: ' + clean_text(path, 120))
        rec_start = epoch(recording.get('start_time'))
        width, height, length = probe(program, path)
        source = {'path': path, 'start': rec_start, 'size': (width, height), 'length': length}
        result['method'] = 'your recording'
    frames = timeline(data, pilot.root)
    if not frames: raise ValueError('This run has no saved frames with times (it was made before clips existed); run it again')
    folder = pilot.root / (run_id + '-clips')
    if folder.is_symlink(): raise ValueError('Invalid clip folder')
    folder.mkdir(mode=0o700, exist_ok=True)
    run_start = float(data.get('batch_started') or frames[0][0])
    run_end = float(data.get('batch_ended') or frames[-1][0])
    result['ffmpeg'] = program; result['folder'] = str(folder)
    made = []
    for index in chosen:
        entry = entries[index]
        times = entry.get('frame_times') or []
        if not times:
            result['skipped'].append({'check': entry.get('name'), 'reason': 'the check stopped before any frame was captured'}); continue
        moment = float(times[-1])
        start, end = window(frames, moment, before, after, run_end)
        label = clean_text(entry.get('name', 'check'), 100)
        caption = ('%s: %s' % (entry.get('verdict', '?'), label), 'frames from the run (slideshow, not full-motion video)' if source is None else 'cut from your recording',
                   clean_text(entry.get('expected', '(not recorded)')), clean_text(entry.get('reason', '')))
        target = folder / ('clip-%02d-%s.mp4' % (index + 1, slug(entry.get('name'))))
        try:
            if source is None:
                parts = segments(frames, start, end)
                if not parts: raise ValueError('no frames in this time range')
                last = min((f for f in frames if f[0] <= moment), key=lambda f: abs(f[0] - moment), default=frames[0])
                with Image.open(last[1]) as image: canvas = canvas_for(image)
                bar = caption_bar(canvas[0], *caption)
                encode_frames(program, parts, canvas, bar, target)
                shape = (canvas[0], canvas[1] + bar.height)
            else:
                lo, hi = source['start'], source['start'] + source['length'] if source['length'] else float('inf')
                if moment < lo or moment > hi: raise ValueError('this check happened outside the recording (it covers %.1f s from its start time)' % (source['length'] or 0))
                start, end = max(start, lo), min(end, hi)
                if end - start < 0.1: raise ValueError('no recording left in this time range')
                w, h = source['size']; scale = min(1.0, MAX_WIDTH / w); w, h = int(w * scale) // 2 * 2 or 2, int(h * scale) // 2 * 2 or 2
                bar = caption_bar(w, *caption)
                encode_recording(program, source['path'], start - lo, end - start, (w, h), bar, target)
                shape = (w, h + bar.height)
        except (ValueError, RuntimeError, OSError) as exc:
            result['skipped'].append({'check': entry.get('name'), 'reason': str(exc)}); continue
        os.chmod(target, 0o600)
        clip = {'file': str(target), 'start_seconds': round(start - run_start, 2), 'end_seconds': round(end - run_start, 2), 'duration_seconds': round(end - start, 2),
                'failure_at_seconds': round(moment - run_start, 2), 'method': result['method'], 'caption': {'title': caption[0], 'expected': caption[2], 'seen': caption[3]}}
        entry['clip'] = clip
        result['clips'].append({'check': entry.get('name'), **clip})
        made.append((index, target, shape))
    if reel and len(made) > 1:
        try:
            reel_path = folder / 'reel-all-failures.mp4'
            encode_reel(program, [target for _, target, _ in made], made[0][2], reel_path)
        except (ValueError, RuntimeError, OSError) as exc:
            result['skipped'].append({'check': 'all-failures reel', 'reason': str(exc)})
        else:
            os.chmod(reel_path, 0o600)
            result['reel'] = {'file': str(reel_path), 'clips': [entries[i].get('name') for i, _, _ in made]}
    return save(pilot, run_id, data, entries, result)


def save(pilot, run_id, data, entries, result):
    from . import batch
    data['batch_results'] = entries
    data['batch_clips'] = {k: v for k, v in result.items() if k != 'ffmpeg'}
    data['batch_report'] = batch.render_report(entries, data['batch_clips'])
    pilot.save(run_id, data)
    result['report'] = data['batch_report']
    return result
