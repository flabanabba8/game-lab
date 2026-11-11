import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).parents[1] / 'parts' / 'playtest'
spec = importlib.util.spec_from_file_location('batch_fixture', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)


class BatchTests(unittest.TestCase):
    def test_scroll_and_sprite_movement(self):
        import random
        rnd = random.Random(23)
        scene = Image.new('RGB', (320, 180)); scene.putdata([(rnd.randrange(256),)*3 for _ in range(320*180)])
        after = Image.new('RGB', scene.size); after.paste(scene.crop((30, 0, 320, 180)), (0, 0))
        passed, _ = module.batch.displacement(scene, after, 'right', module.measurements)
        self.assertTrue(passed)
        scene = Image.new('RGB', (320, 180), 'black'); d = ImageDraw.Draw(scene)
        for x in range(20): d.rectangle((50+x*2, 50, 51+x*2, 70), fill=(x*12, 255-x*12, 90))
        after = Image.new('RGB', scene.size, 'black'); after.paste(scene.crop((45,45,95,75)), (65,45))
        passed, reason = module.batch.displacement(scene, after, 'right', module.measurements)
        self.assertTrue(passed, reason)
        self.assertFalse(module.batch.displacement(scene, scene.copy(), 'right', module.measurements)[0])

    @unittest.skipUnless(module.shutil.which('tesseract'), 'tesseract required')
    def test_read_rendered_value(self):
        image = Image.new('RGB', (400, 100), 'white'); draw = ImageDraw.Draw(image)
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 36)
        draw.text((10, 20), 'coins 37', font=font, fill='black')
        self.assertEqual(module.batch.read_number(image, 'coins')[0], 37)

    def test_batch_freeze_and_panel_retry(self):
        blank = Image.new('RGB', (100, 100), 'black'); moved = Image.new('RGB', (100, 100), 'white')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'DISPLAY': ':7'}):
            pilot = module.Pilot(tmp)
            checks = [{'name':'move','kind':'move','keys':['w'],'hold':.1}, {'name':'pause','kind':'freeze','key':'p','resume_key':'p'}]
            # Initial capture; move before, after, retry before, after; then pause sequence.
            frames = iter([blank, blank, blank, blank, blank, moved, moved, moved, moved, moved, blank])
            with patch.object(module, 'focus_window'), patch.object(module, 'is_black', return_value=False), patch.object(module, 'capture_image', side_effect=lambda w: next(frames)), patch.object(module, 'visible_text', return_value='[1] [2]'), patch.object(module.batch.time, 'sleep'), patch.object(module, 'hold_keys', return_value={'during':blank}) as held, patch.object(module.batch, 'displacement', side_effect=[(False, 'still'), (True, 'moved')]), patch.object(module, 'measurements', return_value={'changed_percent':0, 'panel_after_hint':False}):
                result = module.run_batch(pilot, 'Game', 42, checks, {'dismiss_keys':['1'], 'settle_seconds':0})
            self.assertEqual([x['verdict'] for x in result['checks']], ['PASS', 'PASS'])
            self.assertIn(['1'], [call.args[1] for call in held.call_args_list])
            self.assertEqual(pilot.report(result['run_id'])['report'], result['report'])
            self.assertEqual(module.on_pre_tool_call('playtest_run', {'checklist':checks, 'setup':{'dismiss_keys':['1']}})['action'], 'approve')

if __name__ == '__main__': unittest.main()
