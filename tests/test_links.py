"""Links between parts: sprite check in ModLab inspect, and the Playtest-it hint after apply and export."""
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_lab_links', root / '__init__.py', submodule_search_locations=[str(root)])
suite = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = suite
spec.loader.exec_module(suite)
modlab = suite.modlab
localization = suite.localization


def png(width, height):
    buf = io.BytesIO()
    Image.new('RGBA', (width, height), (0, 0, 0, 0)).save(buf, format='PNG')
    return buf.getvalue()


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.root = Path(self.tmp.name)
        data = self.root / 'data'
        storage = types.ModuleType('plugins.plugin_storage')
        storage.plugin_data_dir = lambda name: (data / name).mkdir(parents=True, exist_ok=True) or data / name
        self.patch = patch.dict(sys.modules, {'plugins': types.ModuleType('plugins'), 'plugins.plugin_storage': storage})
        self.patch.start()
        profile = data / 'game-lab-modlab' / 'modlab-profile'; profile.mkdir(parents=True)
        (profile / 'profile.json').write_text(json.dumps({'answered': True, 'game': 'fixture', 'idea': 'x', 'single_player_offline': True, 'experience': 'some experience', 'publish': 'private', 'ai_assets': False, 'has': '', 'route': None}))
        self.limits = patch.object(modlab, 'limits_from', lambda *a, **k: modlab.core.Limits(max_total=1 << 40, min_free=1, keep=50)); self.limits.start()
        self.game = self.root / 'game'
        (self.game / 'img' / 'characters').mkdir(parents=True)
        (self.game / 'data.txt').write_text('x')
        self.id = json.loads(modlab.invoke('modlab_create', {'source_path': str(self.game)}))['lab_id']

    def tearDown(self):
        self.limits.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def zip(self, entries):
        path = self.root / 'mod.zip'
        with zipfile.ZipFile(path, 'w') as z:
            for name, content in entries.items():
                z.writestr(name, content)
        return str(path)

    def test_inspect_reports_sprite_grid_and_never_blocks(self):
        z = self.zip({'img/characters/Hero.png': png(576, 384), '$Big.png': png(10, 10),
                      'img/characters/$Bad.png': png(10, 10), 'img/characters/Odd.png': png(13, 7), 'notes.txt': 'hi'})
        out = json.loads(modlab.invoke('modlab_inspect', {'lab_id': self.id, 'zip_path': z}))
        self.assertNotIn('error', out)
        files = {f['file']: f for f in out['sprite_check']['files']}
        self.assertEqual(set(files), {'img/characters/Hero.png', 'img/characters/$Bad.png', 'img/characters/Odd.png'})
        self.assertTrue(files['img/characters/Hero.png']['grid_ok'])
        self.assertEqual(files['img/characters/Hero.png']['frame_width'], 48)
        self.assertFalse(files['img/characters/Odd.png']['grid_ok'])
        self.assertTrue(files['img/characters/$Bad.png']['grid_ok'] is False)

    def test_inspect_without_character_art_has_no_sprite_check(self):
        out = json.loads(modlab.invoke('modlab_inspect', {'lab_id': self.id, 'zip_path': self.zip({'data.txt': 'y'})}))
        self.assertNotIn('sprite_check', out)

    def test_bad_png_is_reported_not_raised(self):
        out = json.loads(modlab.invoke('modlab_inspect', {'lab_id': self.id, 'zip_path': self.zip({'img/characters/Broken.png': 'not a png'})}))
        self.assertNotIn('error', out)
        self.assertIsNone(out['sprite_check']['files'][0]['grid_ok'])

    def test_apply_says_it_can_be_playtested_and_starts_nothing(self):
        z = self.zip({'new.txt': 'n'})
        token = json.loads(modlab.invoke('modlab_inspect', {'lab_id': self.id, 'zip_path': z}))['inspection']
        out = json.loads(modlab.invoke('modlab_apply', {'lab_id': self.id, 'zip_path': z, 'inspection': token}))
        self.assertIn('Playtest it:', out['playtest'])
        self.assertIn('Nothing was started', out['playtest'])

    def test_export_says_it_can_be_playtested(self):
        src = self.root / 'Map001.json'
        src.write_text(json.dumps({'events': [None, {'pages': [{'list': [{'code': 101, 'indent': 0, 'parameters': ['', 0, 0, 2]},
                                                                      {'code': 401, 'indent': 0, 'parameters': ['Hello']}]}]}]}))
        draft = json.loads(localization.invoke('localize_inspect', {'source_path': str(src), 'message_rows': 4}))
        did = draft['draft_id']
        page = json.loads(localization.invoke('localize_get', {'draft_id': did}))
        for unit in page['units']:
            localization.invoke('localize_translate', {'draft_id': did, 'unit_id': unit['id'], 'text': 'Hola'})
        out = json.loads(localization.invoke('localize_export', {'draft_id': did}))
        self.assertNotIn('error', out, out)
        self.assertIn('Playtest it:', out['playtest'])
        self.assertIn('path', out)

    def test_skills_offer_the_playtest(self):
        for skill in ('modlab', 'game-localization-studio'):
            text = (root / 'skills' / skill / 'SKILL.md').read_text()
            self.assertIn('Playtest it:', text)
        self.assertIn('sprite_check', (root / 'skills' / 'modlab' / 'SKILL.md').read_text())


if __name__ == '__main__':
    unittest.main()
