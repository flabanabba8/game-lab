import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

root = Path(__file__).parents[1] / 'parts' / 'playtest'
spec = importlib.util.spec_from_file_location('clips_fixture', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
from clips_fixture import clips as cut  # noqa: E402

T0 = 1_800_000_000.0
HAVE = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,pix_fmt,width,height:format=duration', '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)
    stream = info['streams'][0]
    return {'codec': stream['codec_name'], 'pix': stream['pix_fmt'], 'w': stream['width'], 'h': stream['height'], 'duration': float(info['format']['duration'])}


def first_frame(video, work, at=0.0):
    png = Path(work) / ('frame-%s.png' % at)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(at), '-i', str(video), '-frames:v', '1', str(png)], check=True)
    return Image.open(png).convert('RGB')


def colour(n):
    return (20 * n, 40, 255 - 20 * n)


def make_run(tmp, names=None, verdicts=('PASS', 'FAIL', 'FAIL'), size=(321, 181)):
    """A saved run: 3 checks, a frame each second from T0+1 to T0+11, run ended at T0+12. Frame n has colour(n)."""
    pilot = module.Pilot(tmp)
    run_id = 'ab' * 16
    entries = []
    for index, verdict in enumerate(verdicts):
        evidence, times = [], []
        for k in range(3):
            n = 4 * index + 1 + k                           # frames at +1 +2 +3, +5 +6 +7, +9 +10 +11
            name = '%s-batch%d-frame%d.png' % (run_id, index, k)
            Image.new('RGB', size, colour(n)).save(Path(tmp) / name)
            evidence.append(name); times.append(T0 + n)
        entries.append({'name': (names or ['moves right', 'jumps', 'pause'])[index], 'verdict': verdict, 'reason': 'changed 0.00%; no movement detected', 'evidence': evidence,
                        'expected': 'the scene moves right while Right is held for 1 s', 'frame_times': times})
    data = {'app': 'Game', 'steps': [], 'batch_results': entries, 'batch_report': 'x', 'batch_started': T0, 'batch_ended': T0 + 12}
    pilot.save(run_id, data)
    return pilot, run_id, entries


@unittest.skipUnless(HAVE, 'ffmpeg and ffprobe required')
class ClipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='clips-test-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_failing_check_gets_clip_with_range_and_duration(self):
        pilot, run_id, entries = make_run(self.tmp)
        result = cut.make_clips(pilot, run_id, checks=['jumps'], before_seconds=3, after_seconds=1.5, reel=False)
        clip = result['clips'][0]
        moment = entries[1]['frame_times'][-1] - T0
        self.assertAlmostEqual(clip['failure_at_seconds'], moment, places=2)
        self.assertAlmostEqual(clip['start_seconds'], moment - 3, places=2)
        self.assertAlmostEqual(clip['end_seconds'], moment + 1.5, places=2)
        info = probe(clip['file'])
        self.assertEqual((info['codec'], info['pix']), ('h264', 'yuv420p'))
        self.assertEqual((info['w'] % 2, info['h'] % 2), (0, 0))           # source was 321x181
        self.assertAlmostEqual(info['duration'], 4.5, delta=0.25)
        self.assertEqual(Path(clip['file']).parent, pilot.root / (run_id + '-clips'))
        self.assertEqual(clip['method'], 'frames from the run')
        # the first picture is the frame that was on screen at the clip start, and the report carries the path and range
        self.assertIn(clip['file'], result['report'])
        self.assertIn('clip', pilot.report(run_id)['checks'][1])
        with tempfile.TemporaryDirectory(dir=self.tmp) as work:
            top = first_frame(clip['file'], work).getpixel((5, 5))
        shown = [t for t in entries[0]['frame_times'] + entries[1]['frame_times'] if t <= T0 + moment - 3 + 0.01][-1] - T0
        for got, want in zip(top, colour(int(shown))): self.assertAlmostEqual(got, want, delta=14)

    def test_caps_at_run_start_and_end(self):
        pilot, run_id, entries = make_run(self.tmp, verdicts=('FAIL', 'PASS', 'FAIL'))
        result = cut.make_clips(pilot, run_id, before_seconds=10, after_seconds=10, reel=False)
        early, late = result['clips']
        self.assertAlmostEqual(early['start_seconds'], 1.0, places=2)      # first captured frame, not before the run
        self.assertAlmostEqual(late['end_seconds'], 12.0, places=2)         # the run's own end
        for item in (early, late): self.assertAlmostEqual(probe(item['file'])['duration'], item['duration_seconds'], delta=0.25)
        with self.assertRaises(ValueError): cut.make_clips(pilot, run_id, before_seconds=31)
        with self.assertRaises(ValueError): cut.make_clips(pilot, run_id, after_seconds=-1)

    def test_several_failures_make_a_reel_in_order(self):
        pilot, run_id, entries = make_run(self.tmp)
        result = cut.make_clips(pilot, run_id, before_seconds=1, after_seconds=1)
        self.assertEqual([c['check'] for c in result['clips']], ['jumps', 'pause'])
        self.assertEqual(result['reel']['clips'], ['jumps', 'pause'])
        total = sum(probe(c['file'])['duration'] for c in result['clips'])
        self.assertAlmostEqual(probe(result['reel']['file'])['duration'], total, delta=0.3)
        self.assertIn(result['reel']['file'], result['report'])
        self.assertEqual(oct(os.stat(result['reel']['file']).st_mode & 0o777), '0o600')

    def test_passing_run_makes_nothing(self):
        pilot, run_id, _ = make_run(self.tmp, verdicts=('PASS', 'PASS', 'UNVERIFIED'))
        self.assertIsNone(cut.make_clips(pilot, run_id, automatic=True))
        result = cut.make_clips(pilot, run_id)
        self.assertEqual(result['clips'], []); self.assertIn('No failed checks', result['message'])
        self.assertFalse((pilot.root / (run_id + '-clips')).exists())
        named = cut.make_clips(pilot, run_id, checks=['moves right'], reel=False)        # a passing check only when asked by name
        self.assertEqual(len(named['clips']), 1)

    def test_ffmpeg_missing_is_said_plainly_and_report_stays_complete(self):
        pilot, run_id, entries = make_run(self.tmp)
        with patch.object(cut.shutil, 'which', return_value=None):
            result = cut.make_clips(pilot, run_id, automatic=True)
        self.assertEqual(result['clips'], []); self.assertIn('ffmpeg was not found', result['message'])
        report = pilot.report(run_id)
        self.assertIn('ffmpeg was not found', report['report'])
        self.assertEqual([c['verdict'] for c in report['checks']], ['PASS', 'FAIL', 'FAIL'])
        self.assertFalse((pilot.root / (run_id + '-clips')).exists())

    def test_hostile_check_names(self):
        hostile = ['../../etc/passwd; $(touch pwned) `id`', "a'b\"c\nd\x1b[31m", '\u65e5\u672c\u8a9e' * 40]
        pilot, run_id, _ = make_run(self.tmp, names=['ok'] + hostile[:2], verdicts=('FAIL', 'FAIL', 'FAIL'))
        result = cut.make_clips(pilot, run_id, reel=True)
        folder = pilot.root / (run_id + '-clips')
        self.assertEqual(len(result['clips']), 3, result['skipped'])
        for clip in result['clips']:
            self.assertEqual(Path(clip['file']).parent, folder)
            self.assertRegex(Path(clip['file']).name, r'^clip-\d\d-[A-Za-z0-9-]*\.mp4$')
        self.assertFalse((Path(self.tmp).parent / 'etc').exists() or (folder / 'pwned').exists())
        self.assertEqual(cut.slug('\u65e5\u672c\u8a9e'), 'check'); self.assertEqual(cut.slug('../..'), 'check')
        self.assertNotIn('\x1b', cut.clean_text('a\x1b[31mb'))
        pilot2, run2, _ = make_run(tempfile.mkdtemp(dir=self.tmp), names=['ok', hostile[2], 'z'], verdicts=('PASS', 'FAIL', 'PASS'))
        self.assertEqual(len(cut.make_clips(pilot2, run2, reel=False)['clips']), 1)

    def test_evidence_names_from_saved_data_are_checked(self):
        pilot, run_id, entries = make_run(self.tmp)
        data = pilot.load(run_id); data['batch_results'][1]['evidence'][2] = '../../outside.png'; pilot.save(run_id, data)
        outside = Path(self.tmp).parent / 'outside.png'
        self.assertNotIn(outside, [p for _, p in cut.timeline(pilot.load(run_id), pilot.root)])
        self.assertEqual(len(cut.timeline(pilot.load(run_id), pilot.root)), 8)

    def make_recording(self, seconds=12):
        path = Path(self.tmp) / 'my recorder output.mp4'     # a space in the name on purpose
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=320x240:r=10:d=%d' % seconds, '-vf', "format=rgb24,geq=r='20*floor(T)':g='0':b='0',format=yuv420p",
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
        return path

    def test_user_recording_with_start_time_offset(self):
        pilot, run_id, entries = make_run(self.tmp)
        recording = self.make_recording()
        # the recorder was started 0.5 s after the run began: the failure at T0+7 is 6.5 s into the file
        result = cut.make_clips(pilot, run_id, checks=['jumps'], before_seconds=3, after_seconds=1.5, reel=False, recording={'path': str(recording), 'start_time': T0 + 0.5})
        clip = result['clips'][0]
        self.assertEqual(clip['method'], 'your recording')
        self.assertAlmostEqual(clip['duration_seconds'], 4.5, places=2)
        info = probe(clip['file'])
        self.assertAlmostEqual(info['duration'], 4.5, delta=0.25)
        self.assertEqual((info['pix'], info['w'] % 2, info['h'] % 2), ('yuv420p', 0, 0))
        with tempfile.TemporaryDirectory(dir=self.tmp) as work:
            red = first_frame(clip['file'], work, 0.05).getpixel((5, 5))[0]
        # clip starts at T0+4 = 3.5 s into the recording, where red is 20*3 = 60 (a wrong offset would give 80 or 40)
        self.assertAlmostEqual(red, 60, delta=12)
        iso = cut.make_clips(pilot, run_id, checks=['jumps'], reel=False, recording={'path': str(recording), 'start_time': '2027-01-16T08:00:00.500+00:00'})
        self.assertEqual(iso['clips'], []); self.assertIn('outside the recording', iso['skipped'][0]['reason'])
        with self.assertRaises(ValueError): cut.make_clips(pilot, run_id, recording={'path': str(Path(self.tmp) / 'nope.mp4'), 'start_time': T0})
        with self.assertRaises(ValueError): cut.make_clips(pilot, run_id, recording={'path': str(recording), 'start_time': 'yesterday'})
        with self.assertRaises(ValueError): cut.make_clips(pilot, run_id, recording={'path': str(recording), 'start_time': '2026-11-13T10:00:00'})   # no zone

    def test_iso_start_time_equals_epoch(self):
        self.assertEqual(cut.epoch('2027-01-15T08:00:00+00:00'), 1800000000.0)
        self.assertEqual(cut.epoch('2027-01-15T08:00:00Z'), cut.epoch('2027-01-15T10:00:00+02:00'))


@unittest.skipUnless(HAVE, 'ffmpeg and ffprobe required')
class RunIntegrationTests(unittest.TestCase):
    def test_playtest_run_records_times_and_cuts_clip_for_failure_only(self):
        counter = iter(range(1000))
        def capture(window_id):
            time_sleep(0.05)
            return Image.new('RGB', (160, 90), colour(next(counter) % 8))
        time_sleep = __import__('time').sleep
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'DISPLAY': ':7'}):
            pilot = module.Pilot(tmp)
            checks = [{'name': 'moves right', 'kind': 'move', 'keys': ['Right'], 'hold': .1}, {'name': 'moves left', 'kind': 'move', 'keys': ['Left'], 'hold': .1}]
            moves = iter([(True, 'moved'), (False, 'still'), (False, 'still')])
            with patch.object(module, 'focus_window'), patch.object(module, 'is_black', return_value=False), patch.object(module, 'capture_image', side_effect=capture), patch.object(module, 'visible_text', return_value=''), \
                    patch.object(module, 'hold_keys', return_value={'during': Image.new('RGB', (160, 90), 'white')}), patch.object(module.batch, 'displacement', side_effect=lambda *a: next(moves)), \
                    patch.object(module, 'measurements', return_value={'changed_percent': 0, 'panel_after_hint': False}):
                result = module.run_batch(pilot, 'Game', 42, checks, {'settle_seconds': 0})
            verdicts = [c['verdict'] for c in result['checks']]
            self.assertEqual(verdicts, ['PASS', 'FAIL'])
            for entry in result['checks']:
                self.assertEqual(len(entry['frame_times']), len(entry['evidence']))
                self.assertEqual(entry['frame_times'], sorted(entry['frame_times']))
            self.assertNotIn('clip', result['checks'][0]); clip = result['checks'][1]['clip']
            self.assertTrue(Path(clip['file']).is_file() and clip['file'].endswith('.mp4'))
            self.assertIn(clip['file'], result['report']); self.assertIn('frames from the run', result['report'])
            self.assertEqual(result['clips']['clips'][0]['check'], 'moves left')
            self.assertEqual(pilot.report(result['run_id'])['report'], result['report'])
            self.assertEqual(len(list((pilot.root / (result['run_id'] + '-clips')).glob('*.mp4'))), 1)     # one failure: no reel, no clip for the pass
            moves = iter([(True, 'moved')] * 3)        # a clean run makes no clip folder at all
            with patch.object(module, 'focus_window'), patch.object(module, 'is_black', return_value=False), patch.object(module, 'capture_image', side_effect=capture), patch.object(module, 'visible_text', return_value=''), \
                    patch.object(module, 'hold_keys', return_value={'during': Image.new('RGB', (160, 90), 'white')}), patch.object(module.batch, 'displacement', side_effect=lambda *a: next(moves)), \
                    patch.object(module, 'measurements', return_value={'changed_percent': 0, 'panel_after_hint': False}):
                clean = module.run_batch(pilot, 'Game', 42, checks[:1], {'settle_seconds': 0})
            self.assertNotIn('clips', clean); self.assertFalse((pilot.root / (clean['run_id'] + '-clips')).exists())
            with patch.object(module, 'focus_window'), patch.object(module, 'is_black', return_value=False), patch.object(module, 'capture_image', side_effect=capture), patch.object(module, 'visible_text', return_value=''), \
                    patch.object(module, 'hold_keys', return_value={'during': Image.new('RGB', (160, 90), 'white')}), patch.object(module.batch, 'displacement', side_effect=lambda *a: (False, 'still')), \
                    patch.object(module, 'measurements', return_value={'changed_percent': 0, 'panel_after_hint': False}):
                off = module.run_batch(pilot, 'Game', 42, checks[:1], {'settle_seconds': 0}, {'enabled': False})
            self.assertNotIn('clips', off); self.assertEqual(off['checks'][0]['verdict'], 'FAIL')

    def test_tool_approval_only_when_reading_a_recording(self):
        self.assertEqual(module.on_pre_tool_call('playtest_clips', {'run_id': 'x', 'recording': {'path': '/a.mp4', 'start_time': 1}})['action'], 'approve')
        self.assertNotEqual((module.on_pre_tool_call('playtest_clips', {'run_id': 'x'}) or {}).get('action'), 'approve')
        self.assertIn('playtest_clips', module.TOOLS)


if __name__ == '__main__': unittest.main()
