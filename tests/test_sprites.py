import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

spec = importlib.util.spec_from_file_location('sprite_core', Path(__file__).parents[1] / 'parts' / 'sprites' / 'core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

class SpriteTests(unittest.TestCase):
    def test_mixed_case_private_directory_is_rejected(self):
        folder=self.root/'.CoDeX';folder.mkdir();source=folder/'fixture.png';source.write_bytes(b'fixture')
        with self.assertRaises(ValueError):core.load(str(source))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.root = Path(self.tmp.name)
        self.sprite = self.root / '$single.png'
        image = Image.new('RGBA', (12, 16), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.save(self.sprite)
        self.plugin = core.Sprites(self.root / 'outputs')

    def tearDown(self):
        self.tmp.cleanup()

    def test_replaced_png_snapshot_is_rejected(self):
        replacement = self.root/'replacement.png'; replacement.write_bytes(self.sprite.read_bytes())
        original = core.os.fstat; calls = 0
        def replace(fd):
            nonlocal calls
            calls += 1
            value = original(fd)
            if calls == 2: os.replace(replacement, self.sprite)
            return value
        with patch.object(core.os, 'fstat', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'changed while reading'): self.plugin.inspect_mv(str(self.sprite))

    def test_single_grid_and_preview(self):
        result = self.plugin.inspect_mv(str(self.sprite))
        self.assertTrue(result['single_character'])
        self.assertEqual((result['frame_width'], result['frame_height']), (4, 4))
        self.assertFalse(result['cells'][0]['empty'])
        self.assertTrue(result['cells'][1]['empty'])
        preview = self.plugin.preview_mv(str(self.sprite), result['fingerprint'], 0, 'down')
        with Image.open(preview['output_path']) as img:
            self.assertEqual(img.format, 'GIF')
            self.assertEqual(img.size, (4, 4))
            self.assertEqual(preview['sequence_frames'], 4)
            self.assertEqual(preview['encoded_frames'], img.n_frames)
            self.assertEqual(preview['frames'], img.n_frames)

    def test_invalid_grid_and_stale(self):
        result = self.plugin.inspect_mv(str(self.sprite))
        Image.new('RGBA', (13, 16)).save(self.sprite)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.plugin.preview_mv(str(self.sprite), result['fingerprint'], 0, 'down')
        with self.assertRaisesRegex(ValueError, 'divide evenly'):
            self.plugin.inspect_mv(str(self.sprite))

    def test_eight_slot_layout(self):
        path = self.root / 'ordinary.png'
        Image.new('RGBA', (48, 32)).save(path)
        result = self.plugin.inspect_mv(str(path))
        self.assertFalse(result['single_character'])
        self.assertEqual(len(result['cells']), 96)

if __name__ == '__main__':
    unittest.main()
