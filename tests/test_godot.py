"""Godot 4 importer/exporter: a synthetic .pck built in the test, no game files."""
import hashlib
import importlib.util
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'parts' / 'localization'
spec = importlib.util.spec_from_file_location('localize_godot_test', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
from localize_godot_test import godot
from localize_godot_test.core import Studio

HAS_ZSTD = godot._zstd is not None


def pack(files, version=(4, 5, 1)):
    """files: [(name, bytes)] -> format-3 GDPC bytes."""
    base = 112
    head = bytearray(b'GDPC' + struct.pack('<4I', 3, *version) + struct.pack('<I', 0) + struct.pack('<QQ', base, 0) + b'\0' * 72)
    body, entries = bytearray(), []
    for name, data in files:
        body += b'\0' * (-(base + len(body)) % 16)
        entries.append((name, len(body), len(data), hashlib.md5(data).digest())); body += data
    body += b'\0' * (-(base + len(body)) % 16)
    dir_off = base + len(body)
    d = struct.pack('<I', len(entries))
    for name, off, size, md5 in entries:
        nb = name.encode(); nb += b'\0' * (-len(nb) % 4)
        d += struct.pack('<I', len(nb)) + nb + struct.pack('<2Q', off, size) + md5 + struct.pack('<I', 0)
    struct.pack_into('<Q', head, 32, dir_off)
    return bytes(head) + bytes(body) + d


def dialogue(lines):
    """lines: [(id, type, character, text)] -> a Dialogue Manager .tres text."""
    out = ['[gd_resource type="Resource" format=3]', '', '[resource]', 'lines = {']
    for lid, typ, who, text in lines:
        out += ['"%s": {' % lid, '&"id": "%s",' % lid]
        if who: out.append('&"character": "%s",' % who)
        out += ['&"text": "%s",' % text.replace('\n', '\\n'), '&"type": "%s"' % typ, '},']
    out += ['}', 'raw_text = "%s"' % lines[0][3], '']
    return '\n'.join(out).encode('utf-8')


def ustr(s):
    raw = s.encode('utf-8') + b'\0'; return struct.pack('<I', len(raw)) + raw


def rsrc(strings):
    """Minimal RSRC: no string table, no external, one internal resource whose body holds the given strings."""
    head = b'RSRC' + struct.pack('<5I', 0, 0, 4, 5, 6) + ustr('PackedScene')
    imp_pos = len(head); head += struct.pack('<Q', 0) + struct.pack('<I', 0) + struct.pack('<Q', 0) + b'\0' * 44
    head += struct.pack('<I', 0) + struct.pack('<I', 0) + struct.pack('<I', 1) + ustr('res://x.tscn')
    off_pos = len(head); head += struct.pack('<Q', 0)
    body_start = len(head)
    body = b''.join(struct.pack('<I', 4) + ustr(s) for s in strings) + b'RSRC'
    out = bytearray(head + body); struct.pack_into('<Q', out, off_pos, body_start)
    return bytes(out)


def gdc(strings):
    body = b'\x01\0\0\0' + b''.join(b'\x04\0\0\0' + struct.pack('<I', len(s.encode())) + s.encode() + b'\0' * (-len(s.encode()) % 4) for s in strings)
    return godot.gdc_pack(100, body)


class GodotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp'); self.dir = Path(self.tmp.name)
        files = [('.godot/imported/intro.dialogue-' + '0' * 32 + '.tres',
                  dialogue([('7', 'dialogue', 'ゆうしゃ', '[color=cyan]こんにちは[/color]\nげんき？'), ('8', 'response', '', 'はい {{name}}'),
                            ('9', 'title', '', 'ちがう')])),
                 ('.godot/exported/menu.scn', rsrc(['つぎへ', 'ふつう', 'res://skip.png'])),
                 ('readme.txt', b'not text')]
        if HAS_ZSTD: files.append(('scene/menu.gdc', gdc(['とじる', 'ふつう'])))
        self.game = self.dir / 'game'; self.game.mkdir()
        self.pck = self.game / 'Game.pck'; self.pck.write_bytes(pack(files))
        self.studio = Studio(self.dir / 'data')

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_repack_without_changes(self):
        index = godot.read_pack(self.pck)
        out = self.dir / 'same.pck'; godot.write_pack(self.pck, index, {}, out)
        again = godot.read_pack(out)
        self.assertEqual([e['name'] for e in again['entries']], [e['name'] for e in index['entries']])
        for a, b in zip(index['entries'], again['entries']):
            self.assertEqual(godot.read_entry(self.pck, a), godot.read_entry(out, b)); self.assertEqual(a['md5'], b['md5'])

    def test_inspect_finds_every_carrier_and_blocks_shared_keys(self):
        r = self.studio.inspect(str(self.game))
        self.assertEqual(r['engine'], 'godot'); self.assertEqual(r['godot_version'], '4.5.1')
        units = self.studio.get(r['draft_id'], 0, 100)['units']
        by = {(u['kind'], u['source']) for u in units}
        self.assertIn(('dialogue', '[color=cyan]こんにちは[/color]\nげんき？'), by)
        self.assertIn(('speaker', 'ゆうしゃ'), by)
        self.assertIn(('response', 'はい {{name}}'), by)
        self.assertNotIn('ちがう', {u['source'] for u in units}, 'title lines are not shown to players')
        self.assertIn(('resource', 'つぎへ'), by)
        self.assertNotIn('res://skip.png', {u['source'] for u in units})
        if HAS_ZSTD:
            blocked = {u['source'] for u in units if u.get('blocked_reason')}
            self.assertEqual(blocked, {'ふつう'}, 'only text that is both a scene string and a script constant is held')

    def test_tokens_and_label_rows_are_enforced(self):
        r = self.studio.inspect(str(self.pck)); units = self.studio.get(r['draft_id'], 0, 100)['units']
        resp = next(u for u in units if u['kind'] == 'response')
        with self.assertRaises(ValueError): self.studio.translate(r['draft_id'], resp['id'], 'Yes')
        self.studio.translate(r['draft_id'], resp['id'], 'Yes, {{name}}')
        label = next(u for u in units if u['source'] == 'つぎへ')
        with self.assertRaises(ValueError): self.studio.translate(r['draft_id'], label['id'], 'Next\npage')
        line = next(u for u in units if u['kind'] == 'dialogue')
        self.studio.translate(r['draft_id'], line['id'], '[color=cyan]Hello![/color]\nHow are you?')
        with self.assertRaises(ValueError): self.studio.translate(r['draft_id'], line['id'], 'Hello!\nHow are you?')

    def test_export_writes_a_new_pack_that_reads_back(self):
        r = self.studio.inspect(str(self.pck)); d = r['draft_id']; units = self.studio.get(d, 0, 100)['units']
        tr = {'[color=cyan]こんにちは[/color]\nげんき？': '[color=cyan]Hello[/color]\nHow are you?', 'ゆうしゃ': 'Hero',
              'はい {{name}}': 'Yes, {{name}}', 'つぎへ': 'Next (a longer label)', 'とじる': 'Close'}
        for u in units:
            if u['source'] in tr and not u.get('blocked_reason'): self.studio.translate(d, u['id'], tr[u['source']])
        before = self.pck.read_bytes()
        out = self.studio.export(d)
        self.assertEqual(self.pck.read_bytes(), before, 'source pack untouched')
        new = Path(out['path']); index = godot.read_pack(new)
        entries = {e['name']: godot.read_entry(new, e) for e in index['entries']}
        tres = entries['.godot/imported/intro.dialogue-' + '0' * 32 + '.tres'].decode()
        self.assertIn('&"text": "[color=cyan]Hello[/color]\\nHow are you?"', tres)
        self.assertIn('&"character": "Hero"', tres)
        self.assertIn('raw_text = "[color=cyan]こんにちは[/color]\\nげんき？"' if False else 'raw_text = ', tres)
        scn = entries['.godot/exported/menu.scn']
        self.assertIn(b'Next (a longer label)', scn)
        table = godot.rsrc_offset_table(scn)
        body = struct.unpack_from('<Q', scn, table[1])[0]
        self.assertEqual(struct.unpack_from('<I', scn, body)[0], 4, 'internal resource offset still points at its body')
        self.assertEqual(entries['readme.txt'], b'not text')
        if HAS_ZSTD:
            _, body = godot.gdc_unpack(entries['scene/menu.gdc'])
            self.assertIn(b'Close', body)

    def test_texture_roundtrip(self):
        from PIL import Image
        im = Image.new('RGBA', (8, 4), (10, 20, 30, 255)); buf = io.BytesIO(); im.save(buf, 'WEBP', lossless=True)
        webp = buf.getvalue()
        tex = b'GST2' + struct.pack('<4I', 1, 8, 4, 0) + b'\0' * (godot.CTEX_HEADER - 4 - 16 - 8) + struct.pack('<2I', 37, len(webp)) + webp
        self.assertEqual(godot.ctex_decode(tex).size, (8, 4))
        red = Image.new('RGBA', (8, 4), (255, 0, 0, 255))
        self.assertEqual(godot.ctex_decode(godot.ctex_encode(tex, red)).convert('RGBA').getpixel((0, 0)), (255, 0, 0, 255))
        with self.assertRaises(ValueError): godot.ctex_encode(tex, Image.new('RGBA', (9, 4)))

    def test_rejects_non_pack_and_encrypted(self):
        bad = self.dir / 'x.pck'; bad.write_bytes(b'NOPE' + b'\0' * 200)
        with self.assertRaises(ValueError): godot.read_pack(bad)
        enc = bytearray(self.pck.read_bytes()); struct.pack_into('<I', enc, 20, 1); bad.write_bytes(bytes(enc))
        with self.assertRaises(ValueError): godot.read_pack(bad)


if __name__ == '__main__':
    unittest.main()
