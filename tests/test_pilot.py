import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

root = Path(__file__).parents[1] / "parts" / "playtest"
spec = importlib.util.spec_from_file_location('pilot_fixture', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

class Context:
    def __init__(self, result): self.result = result; self.actions = []
    def dispatch_tool(self, name, action, **kwargs):
        self.actions.append((name, action, kwargs))
        if action['action'] == 'capture': return json.dumps({'mode': 'ax', 'app': 'Test Game'})
        return self.result

class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.display = patch.dict('os.environ', {'DISPLAY': ':7'})
        self.display.start()
        self.pilot = module.Pilot(Path(self.tmp.name))
        self.id = self.pilot.start('Test Game', 'Open the menu', 123)['run_id']

    def tearDown(self):
        self.display.stop()
        self.tmp.cleanup()

    def test_overlapping_action_does_not_capture_or_dispatch(self):
        ctx = Context(json.dumps({'ok': True}))
        with module._action_lock:
            with self.assertRaisesRegex(RuntimeError, 'action is in progress'):
                module.perform(self.pilot, ctx, self.id, 'Open menu', 'Menu visible', {'action': 'key'}, session_id='fixture-session')
        self.assertEqual(ctx.actions, [])
        self.assertEqual(self.pilot.report(self.id)['steps'], [])

    def test_missing_posix_locking_reports_requirement_before_dispatch(self):
        ctx=Context(json.dumps({'ok':True}))
        with patch.object(module.core,'fcntl',None):
            with self.assertRaisesRegex(ValueError,'requires X11 and POSIX'):
                module.perform(self.pilot,ctx,self.id,'Go','Done',{'action':'key'},session_id='fixture-session')
        self.assertEqual(ctx.actions,[])

    def test_new_and_updated_receipts_are_private_under_permissive_umask(self):
        previous = os.umask(0)
        try:
            ident = self.pilot.start('Test Game', 'Private notes', 123)['run_id']
            path = self.pilot.path(ident)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.pilot.begin(ident, 'Open menu', 'Menu visible', 'key')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        finally:
            os.umask(previous)

    def test_acknowledgment_and_observation_are_separate(self):
        ctx = Context(json.dumps({'ok': True}))
        module.perform(self.pilot, ctx, self.id, 'Open menu', 'Menu visible', {'action': 'key', 'keys': 'Escape'}, session_id='fixture-session')
        report = self.pilot.report(self.id)
        self.assertEqual(report['steps'][0]['acknowledgment'], 'acknowledged')
        self.assertIsNone(report['steps'][0]['observation'])
        self.pilot.observe(self.id, 1, 'passed', 'Menu observed')
        self.assertEqual(self.pilot.report(self.id)['steps'][0]['observation']['status'], 'passed')
        self.assertEqual(ctx.actions[0][1]['window_id'], 123)
        self.assertEqual(ctx.actions[1][1]['app'], 'Test Game')
        self.assertEqual(ctx.actions[1][2]['session_id'], 'fixture-session')

    def test_denial_and_unknown_not_silently_successful(self):
        denied = Context(json.dumps({'status': 'denied'}))
        module.perform(self.pilot, denied, self.id, 'Go', 'Moves', {'action': 'key'}, session_id='fixture-session')
        self.assertEqual(self.pilot.report(self.id)['steps'][0]['acknowledgment'], 'failed_or_denied')
        failure = Context(json.dumps({'ok': False, 'message': 'Action failed'}))
        module.perform(self.pilot, failure, self.id, 'Go', 'Moves', {'action': 'key'}, session_id='fixture-session')
        self.assertEqual(self.pilot.report(self.id)['steps'][1]['acknowledgment'], 'failed_or_denied')
        unknown = Context(json.dumps({'action': 'key'}))
        module.perform(self.pilot, unknown, self.id, 'Go', 'Moves', {'action': 'key'}, session_id='fixture-session')
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            module.perform(self.pilot, unknown, self.id, 'Again', 'Moves', {'action': 'key'}, session_id='fixture-session')
        self.assertEqual(sum(a[1]['action'] == 'key' for a in unknown.actions), 1)

    def test_multimodal_action_result_is_preserved(self):
        image_block = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}
        envelope = {'_multimodal': True, 'content': [image_block], 'action_result': {'ok': True}}
        ctx = Context(envelope)
        result = module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key'}, session_id='fixture-session')
        self.assertIs(result, envelope)
        self.assertEqual(self.pilot.report(self.id)['steps'][0]['acknowledgment'], 'acknowledged')

    def test_app_name_case_difference_is_accepted_and_selected_name_is_used(self):
        ctx = Context(json.dumps({'ok': True}))
        module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key', 'keys': 'Escape', 'app': 'test game'}, session_id='fixture-session')
        self.assertEqual(ctx.actions[1][1]['app'], 'Test Game')

    def test_input_is_brought_to_the_front_unless_the_caller_chose_a_delivery_mode(self):
        ctx = Context(json.dumps({'ok': True}))
        module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key', 'keys': 'Right'}, session_id='fixture-session')
        sent = ctx.actions[1][1]
        self.assertEqual((sent['delivery_mode'], sent['bring_to_front']), ('foreground', True))
        ctx = Context(json.dumps({'ok': True}))
        self.pilot.observe(self.id, 1, 'passed', 'moved')
        module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key', 'keys': 'Right', 'delivery_mode': 'background'}, session_id='fixture-session')
        self.assertEqual(ctx.actions[1][1]['delivery_mode'], 'background'); self.assertNotIn('bring_to_front', ctx.actions[1][1])

    def test_hold_validates_keys_and_seconds(self):
        self.assertEqual(module.hold_spec({'action': 'hold', 'keys': ['Right', 'space'], 'seconds': 1.5}), (['Right', 'space'], 1.5))
        for bad in ({'keys': 'Right', 'seconds': 4}, {'keys': 'Right', 'seconds': 0}, {'keys': ['ctrl+c'], 'seconds': 1}, {'keys': ['a', 'b', 'c', 'd'], 'seconds': 1}, {'keys': 'Right', 'seconds': 1, 'extra': 1}):
            with self.assertRaises(ValueError): module.hold_spec({'action': 'hold', **bad})

    def test_hold_presses_waits_and_always_releases_keys(self):
        calls = []
        class R: returncode = 0
        def run(argv, **kw): calls.append(argv[1:]); return R()
        waited = []
        with patch('shutil.which', return_value='/usr/bin/xdotool'):
            result = module.hold_keys(42, ['Right', 'space'], 1.5, run=run, sleep=waited.append)
        self.assertEqual(waited, [0.375, 1.125]); self.assertTrue(result['ok'])
        self.assertEqual(calls, [['windowraise', '42'], ['windowfocus', '42'], ['keydown', 'Right'], ['keydown', 'space'], ['keyup', 'space'], ['keyup', 'Right']])
        calls.clear()
        def boom(seconds): raise KeyboardInterrupt
        with patch('shutil.which', return_value='/usr/bin/xdotool'):
            with self.assertRaises(KeyboardInterrupt): module.hold_keys(42, ['Right'], 1, run=run, sleep=boom)
        self.assertIn(['keyup', 'Right'], calls)

    def test_hold_without_xdotool_gives_a_plain_error(self):
        with patch('shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'xdotool'): module.hold_keys(42, ['Right'], 1)

    def test_hold_action_records_a_step_returns_a_capture_and_asks_for_approval(self):
        ctx = Context(json.dumps({'ok': True}))
        with patch.object(module, 'grab_window', return_value=None), patch.object(module, 'hold_keys', side_effect=lambda w, k, sec, during=None: {'ok': True, 'during': during()}) as held:
            module.perform(self.pilot, ctx, self.id, 'Run', 'Moves', {'action': 'hold', 'keys': ['Right'], 'seconds': 1}, session_id='fixture-session')
        held.assert_called_once()
        self.assertEqual(ctx.actions[-1][1]['action'], 'capture'); self.assertEqual(ctx.actions[-1][1]['mode'], 'vision')
        self.assertEqual(self.pilot.report(self.id)['steps'][-1]['acknowledgment'], 'acknowledged')
        self.assertEqual(module.on_pre_tool_call(tool_name='playtest_action', args={'action': {'action': 'hold', 'keys': ['Right'], 'seconds': 1}})['action'], 'approve')
        self.assertIsNone(module.on_pre_tool_call(tool_name='playtest_action', args={'action': {'action': 'key', 'keys': 'Right'}}))

    def test_input_actions_ask_for_a_capture_after_unless_the_caller_decides(self):
        ctx = Context(json.dumps({'ok': True}))
        module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key', 'keys': 'Right'}, session_id='fixture-session')
        self.assertTrue(ctx.actions[1][1]['capture_after'])

    def test_capture_before_action_carries_pid_from_action_or_run(self):
        ctx = Context(json.dumps({'ok': True}))
        module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key', 'keys': 'Escape', 'pid': 4321}, session_id='fixture-session')
        self.assertEqual(ctx.actions[0][1]['pid'], 4321)
        run = self.pilot.start('Test Game', 'With stored pid', 123, 777)['run_id']
        ctx = Context(json.dumps({'ok': True}))
        module.perform(self.pilot, ctx, run, 'Go', 'Moves', {'action': 'key', 'keys': 'Escape'}, session_id='fixture-session')
        self.assertEqual(ctx.actions[0][1]['pid'], 777)
        with self.assertRaisesRegex(ValueError, 'pid'):
            module.perform(self.pilot, ctx, run, 'Go', 'Moves', {'action': 'key', 'keys': 'Escape', 'pid': 'x'}, session_id='fixture-session')

    def test_wrong_target_missing_session_and_indices_rejected(self):
        ctx = Context('{}')
        with self.assertRaisesRegex(ValueError, 'selected app'):
            module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key', 'app': 'Other'}, session_id='fixture-session')
        with self.assertRaisesRegex(ValueError, 'session ID'):
            module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'key'})
        with self.assertRaisesRegex(ValueError, 'Element-index'):
            module.perform(self.pilot, ctx, self.id, 'Go', 'Moves', {'action': 'click', 'element': 2}, session_id='fixture-session')
        self.assertEqual(ctx.actions, [])

    def test_explicit_step_replay_requires_observation_and_recaptures_target(self):
        ctx = Context(json.dumps({'ok': True}))
        module.perform(self.pilot, ctx, self.id, 'Open menu', 'Menu visible',
                       {'action': 'key', 'keys': 'escape'}, record_for_replay=True, session_id='fixture-session')
        target = self.pilot.start('Test Game', 'Repeat menu', 456)['run_id']
        with self.assertRaisesRegex(ValueError, 'observed'):
            module.replay(self.pilot, ctx, target, self.id, 1, session_id='fixture-session')
        self.pilot.observe(self.id, 1, 'passed', 'Menu visible')
        module.replay(self.pilot, ctx, target, self.id, 1, session_id='fixture-session')
        self.assertEqual(ctx.actions[-2][1]['window_id'], 456)
        self.assertEqual(ctx.actions[-1][1]['keys'], 'escape')
        self.assertEqual(self.pilot.report(target)['steps'][0]['acknowledgment'], 'acknowledged')
        self.assertIsNone(self.pilot.report(target)['steps'][0]['observation'])
        with self.assertRaisesRegex(ValueError, 'Observe'):
            module.replay(self.pilot, ctx, target, self.id, 1, session_id='fixture-session')
        self.pilot.observe(target, 1, 'passed', 'Menu visible again')
        module.replay(self.pilot, ctx, target, self.id, 1, session_id='fixture-session')
        self.assertEqual(len(self.pilot.report(target)['steps']), 2)

        denied_target = self.pilot.start('Test Game', 'Denied replay', 789)['run_id']
        denied = Context(json.dumps({'status': 'denied'}))
        module.replay(self.pilot, denied, denied_target, self.id, 1, session_id='fixture-session')
        self.assertEqual(self.pilot.report(denied_target)['steps'][0]['acknowledgment'], 'failed_or_denied')
        self.assertIsNone(self.pilot.report(denied_target)['steps'][0]['observation'])

    def test_replay_rejects_text_and_unsafe_or_unrecorded_actions(self):
        ctx = Context(json.dumps({'ok': True}))
        for action in ({'action':'type','text':'private'}, {'action':'key','keys':'ctrl+s'},
                       {'action':'click','coordinate':[True,2]}, {'action':'click','coordinate':[1,2],'text':'private'}):
            with self.assertRaises(ValueError):
                module.perform(self.pilot, ctx, self.id, 'Go', 'Done', action, record_for_replay=True, session_id='fixture-session')
        self.assertEqual(ctx.actions, [])
        module.perform(self.pilot, ctx, self.id, 'Go', 'Done', {'action':'key','keys':'escape'}, session_id='fixture-session')
        self.pilot.observe(self.id, 1, 'failed', 'Not done')
        target = self.pilot.start('Test Game', 'Repeat', 456)['run_id']
        with self.assertRaisesRegex(ValueError, 'replay action'):
            module.replay(self.pilot, ctx, target, self.id, 1, session_id='fixture-session')
        self.assertEqual(len(ctx.actions), 2)
        other = self.pilot.start('Other Game', 'Repeat', 789)['run_id']
        with self.assertRaisesRegex(ValueError, 'same named app'):
            module.replay(self.pilot, ctx, other, self.id, 1, session_id='fixture-session')
        denied_source = self.pilot.start('Test Game', 'Denied', 123)['run_id']
        denied = Context(json.dumps({'status':'denied'}))
        module.perform(self.pilot, denied, denied_source, 'Go', 'Done', {'action':'key','keys':'escape'}, record_for_replay=True, session_id='fixture-session')
        self.pilot.observe(denied_source, 1, 'passed', 'Synthetic observation')
        with self.assertRaisesRegex(ValueError, 'acknowledged'):
            module.replay(self.pilot, ctx, target, denied_source, 1, session_id='fixture-session')

    def test_scene_shift_reads_sideways_scroll_not_character_position(self):
        import numpy
        rng = numpy.random.default_rng(3)
        scene = rng.integers(0, 255, (180, 320)).astype(numpy.int16)
        after = numpy.roll(scene, -40, axis=1)  # scenery slid left by 40 columns
        for frame in (scene, after): frame[150:170, 150:170] = 255  # a fixed marker (the character) stays put
        line = module.scene_shift(scene, after)
        self.assertIn('slid', line); self.assertIn('to the left', line); self.assertIn('moving right', line)
        self.assertIn('did not change', module.scene_shift(scene, scene.copy()))
        self.assertIn('to the right', module.scene_shift(after, scene))
        self.assertIsNone(module.scene_shift(None, scene))
        self.assertIsNone(module.scene_shift(scene, scene[:100]))

    def test_scene_shift_is_attached_to_results_and_stored_in_the_record(self):
        import numpy
        base = numpy.random.default_rng(5).integers(0, 255, (180, 320)).astype(numpy.int16)
        grabs = iter([base, numpy.roll(base, -30, axis=1)])
        ctx = Context(json.dumps({'ok': True}))
        with patch.object(module, 'grab_window', side_effect=lambda w: next(grabs)):
            result = module.perform(self.pilot, ctx, self.id, 'Run', 'Scenery moves', {'action': 'key', 'keys': 'Right'}, session_id='fixture-session')
        self.assertIn('slid', json.loads(result)['scene_shift'])
        self.assertIn('slid', self.pilot.report(self.id)['steps'][0]['scene_shift'])
        envelope = {'_multimodal': True, 'content': [], 'action_result': {'ok': True}}
        self.assertEqual(module.with_hint(envelope, 'x')['content'], [])
        self.assertIs(module.with_hint(envelope, None), envelope)

    def test_scene_track_adds_up_a_long_scroll_that_one_comparison_cannot_follow(self):
        import numpy
        rng = numpy.random.default_rng(11)
        world = rng.integers(0, 255, (180, 1200)).astype(numpy.int16)
        frames = [world[:, x:x + 320] for x in range(0, 700, 40)]  # the view moves right through the world: scenery slides left
        self.assertIn('to the left', module.scene_track(frames)); self.assertIn('moving right', module.scene_track(frames))
        self.assertIn('to the right', module.scene_track(frames[::-1]))
        self.assertNotIn('whole picture slid', module.scene_shift(frames[0], frames[-1]) or '')  # too far for one comparison
        self.assertIsNone(module.scene_track([None, None]))
        with module.Sampler(1, grab=lambda w: frames[0]) as sampler: pass
        self.assertTrue(sampler.frames)

    def test_grab_window_without_tools_returns_none(self):
        with patch('shutil.which', return_value=None):
            self.assertIsNone(module.grab_window(42))

if __name__ == '__main__': unittest.main()
