"""Unity importer/exporter: synthetic serialized files and a synthetic managed assembly, no game files."""
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'parts' / 'localization'
spec = importlib.util.spec_from_file_location('localize_unity_test', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
from localize_unity_test import dotnet, unity
from localize_unity_test.core import Studio


def ustr(text):
    raw = text.encode('utf-8')
    return struct.pack('<I', len(raw)) + raw + b'\0' * (-len(raw) % 4)


def text_asset(name, body):
    return ustr(name) + ustr(body)


def mono_script(class_name, namespace=''):
    return ustr(class_name) + struct.pack('<i', 0) + b'\0' * 16 + ustr(class_name) + ustr(namespace) + ustr('Assembly-CSharp.dll')


def behaviour(script_path_id, name, *fields, file_id=0):
    body = b'\0' * 12 + struct.pack('<I', 1) + struct.pack('<iq', file_id, script_path_id) + ustr(name)
    for field in fields:
        body += ustr(field) if isinstance(field, str) else field
    return body


def game_object(name):
    return struct.pack('<I', 1) + b'\0' * 12 + struct.pack('<I', 0) + ustr(name) + struct.pack('<HB', 0, 1)


def serialized(objects, externals=(), align=16, version=22):
    """objects: [(path_id, class_id, payload)]. Builds a little-endian format-22 file without type trees."""
    classes = sorted({class_id for _, class_id, _ in objects})
    meta = b'6000.0.45f1\0' + struct.pack('<i', 19) + b'\0' + struct.pack('<i', len(classes))
    for class_id in classes:
        meta += struct.pack('<i', class_id) + b'\0' + struct.pack('<h', -1) + b'\0' * (32 if class_id == 114 else 16)
    meta += struct.pack('<i', len(objects))
    data, table = b'', []
    for path_id, class_id, payload in objects:
        data += b'\0' * (-len(data) % align)
        table.append((path_id, len(data), len(payload), classes.index(class_id))); data += payload
    for entry in table:
        meta += b'\0' * (-(48 + len(meta)) % 4) + struct.pack('<qqIi', *entry)
    meta += struct.pack('<i', 0) + struct.pack('<i', len(externals))
    for name in externals:
        meta += b'\0' + b'\0' * 16 + struct.pack('<i', 0) + name.encode() + b'\0'
    meta += struct.pack('<i', 0) + b'\0'
    data_offset = (48 + len(meta) + 15) & ~15
    head = b'\0' * 8 + struct.pack('>I', version) + b'\0' * 8 + struct.pack('>Iqq', len(meta), data_offset + len(data), data_offset) + b'\0' * 8
    return head + meta + b'\0' * (data_offset - 48 - len(meta)) + data


def assembly(strings):
    """A minimal PE32 managed assembly: methods 0..n-1 each load one literal; one fat method holds a decoy."""
    heap, offsets = b'\0', []
    for text in strings:
        offsets.append(len(heap)); heap += dotnet.encode_literal(text)
    heap += b'\0' * (-len(heap) % 4)
    bodies, rvas, base = b'', [], 0x2000 + 72
    for offset in offsets:
        code = b'\x72' + struct.pack('<I', 0x70000000 | offset) + b'\x26\x2a'
        rvas.append(base + len(bodies)); bodies += bytes([len(code) << 2 | 2]) + code
        bodies += b'\0' * (-len(bodies) % 4)
    # ldc.i4 whose operand looks like "ldstr 0x70000001", a switch, a two-byte opcode, then a real ldstr of string 0.
    code = (b'\x20\x72\x01\x00\x00' + b'\x70' * 0 + b'\x26' + b'\x16\x45' + struct.pack('<Iii', 2, 0, 0) + b'\xfe\x01\x26'[:0]
            + b'\x16\x16\xfe\x01\x26' + b'\x72' + struct.pack('<I', 0x70000000 | offsets[0]) + b'\x26\x2a')
    rvas.append(base + len(bodies)); bodies += struct.pack('<HHII', 0x3003, 8, len(code), 0) + code
    bodies += b'\0' * (-len(bodies) % 4)
    rows = len(rvas)
    tables = b'\0' * 4 + bytes([2, 0, 0, 1]) + struct.pack('<QQ', 1 | 1 << 6, 0) + struct.pack('<II', 1, rows) + b'\0' * 10
    for rva in rvas: tables += struct.pack('<IHHHHH', rva, 0, 0x16, 1, 1, 1)
    tables += b'\0' * (-len(tables) % 4)
    names = b'\0M\0\0'; blob = b'\0\0\0\0'
    version = b'v4.0.30319\0\0'
    streams = [(b'#~\0\0', tables), (b'#Strings\0\0\0\0', names), (b'#US\0', heap), (b'#Blob\0\0\0', blob)]
    header_size = 16 + len(version) + 4 + sum(8 + len(name) for name, _ in streams)
    header = b'BSJB' + struct.pack('<HHII', 1, 1, 0, len(version)) + version + struct.pack('<HH', 0, len(streams))
    position, body = header_size, b''
    for name, content in streams:
        header += struct.pack('<II', position, len(content)) + name; position += len(content); body += content
    metadata = header + body
    md_rva = base + len(bodies)
    cli = struct.pack('<IHHIIII', 72, 2, 5, md_rva, len(metadata), 1, 0) + b'\0' * 48
    text = cli + bodies + metadata
    raw_size = (len(text) + 0x1ff) & ~0x1ff
    dos = b'MZ' + b'\0' * 58 + struct.pack('<I', 0x80) + b'\0' * 64
    coff = struct.pack('<HHIIIHH', 0x14c, 1, 0, 0, 0, 224, 0x2102)
    opt = bytearray(224); struct.pack_into('<H', opt, 0, 0x10b)
    struct.pack_into('<II', opt, 32, 0x2000, 0x200); struct.pack_into('<II', opt, 56, 0x4000, 0x200)
    struct.pack_into('<I', opt, 92, 16); struct.pack_into('<II', opt, 96 + 14 * 8, 0x2000, 72)
    section = b'.text\0\0\0' + struct.pack('<IIII', len(text), 0x2000, raw_size, 0x200) + b'\0' * 12 + struct.pack('<I', 0x60000020)
    head = dos + b'PE\0\0' + coff + bytes(opt) + section
    return head + b'\0' * (0x200 - len(head)) + text + b'\0' * (raw_size - len(text))


SCENARIO = '\ufeff[\r\n  {\r\n    "id": "0001",\r\n    "type": 1,\r\n    "characterID": "0007",\r\n    "text": "こんにちは\\n元気ですか？",\r\n    "voice": 606\r\n  },\r\n  {"name": "会話１", "id": "0002", "type": 9, "arguments": [{"value": "お待ちください"}, {"value": "0002"}]}\r\n]\r\n'


def game(tmp, with_dll=True):
    data = Path(tmp) / 'Game' / 'Game_Data'; (data / 'Managed').mkdir(parents=True)
    (data / 'globalgamemanagers').write_bytes(serialized([(1, 1, game_object('Settings'))]))
    objects = [
        (1, 49, text_asset('scene_one', SCENARIO)),
        (2, 49, text_asset('LineBreaking Following Characters', '）］｝、。ぁぃ')),
        (3, 115, mono_script('Item')),
        (4, 115, mono_script('TextMeshProUGUI', 'TMPro')),
        (5, 114, behaviour(3, 'Chocolate', 'チョコレート', struct.pack('<ii', 120, 3), 'あまいおかし', struct.pack('<f', 1.5))),
        (6, 114, behaviour(4, '', struct.pack('<iiii', 0, 0, 0, 0), '閉じる', struct.pack('<ii', 7, 9), '<color=#ff0000>{0}円</color>')),
        (7, 1, game_object('口わらい')),
        (8, 114, behaviour(3, 'Mouth', '口わらい')),
        (9, 115, mono_script('TMP_FontAsset', 'TMPro')),
        (10, 114, behaviour(9, 'Noto SDF', 'ABCあいう')),
        (11, 28, ustr('ランク1a') + b'\x07' * 40),
    ]
    (data / 'resources.assets').write_bytes(serialized(objects))
    (data / 'sharedassets0.assets').write_bytes(serialized([(1, 114, behaviour(3, 'Curry', 'カレー', file_id=1))], externals=['resources.assets']))
    (data / 'sharedassets0.assets.resS').write_bytes(b'\x89' * 64)
    (data / 'boot.config').write_text('x=1')
    if with_dll: (data / 'Managed' / 'Assembly-CSharp.dll').write_bytes(assembly(['お金が足りません！', 'Assets/Prefabs', '{0}は{1}個です']))
    return data.parent


class FormatTests(unittest.TestCase):
    def test_object_table_reads_and_rebuilds_identically(self):
        raw = serialized([(1, 49, text_asset('a', '[]')), (5, 1, game_object('g')), (9, 114, behaviour(3, 'n', 'x'))])
        parsed = unity.SerializedFile(raw)
        self.assertEqual([(o['path_id'], o['class_id']) for o in parsed.objects], [(1, 49), (5, 1), (9, 114)])
        self.assertEqual(parsed.unity_version, '6000.0.45f1')
        self.assertEqual(parsed.rebuild({}), raw)

    def test_growing_one_object_moves_the_rest_and_keeps_them_aligned(self):
        tail = game_object('tail')
        raw = serialized([(1, 49, text_asset('a', '["x"]')), (2, 114, behaviour(3, 'n', 'y')), (3, 1, tail)])
        for body in (text_asset('a', '["' + 'long ' * 40 + '"]'), text_asset('a', '[]')):
            again = unity.SerializedFile(unity.SerializedFile(raw).rebuild({1: body}))
            self.assertEqual(again.file_size, len(again.data))
            self.assertEqual(again.payload(again.by_id[1]), body)
            self.assertEqual(again.payload(again.by_id[3]), tail)
            self.assertTrue(all(o['start'] % 16 == 0 for o in again.objects))

    def test_other_formats_and_garbage_are_refused(self):
        raw = serialized([(1, 49, text_asset('a', '[]'))])
        for bad in (serialized([(1, 49, b'')], version=21), raw[:40], raw[:-1], b'UnityFS\0' + raw[8:], raw[:16] + b'\x01' + raw[17:]):
            with self.assertRaisesRegex(ValueError, 'Not a supported Unity serialized file'): unity.SerializedFile(bad)

    def test_json_spans_address_values_not_keys_and_keep_formatting(self):
        spans = {path: (start, end, value) for path, start, end, value in unity.json_spans(SCENARIO)}
        self.assertEqual(spans[(0, 'text')][2], 'こんにちは\n元気ですか？')
        self.assertEqual(spans[(1, 'arguments', 0, 'value')][2], 'お待ちください')
        start, end, _ = spans[(0, 'text')]
        self.assertEqual(SCENARIO[start:end], '"こんにちは\\n元気ですか？"')
        self.assertNotIn(('text',), spans)
        for bad in ('{"a": 1, "a": "x"}', '[1,]', '{"a" 1}', '[] x'):
            with self.assertRaises(ValueError): unity.json_spans(bad)

    def test_assembly_literals_ignore_lookalike_bytes(self):
        raw = assembly(['げんき', 'second'])
        parsed = dotnet.Assembly(raw)
        self.assertEqual([text for _, text in parsed.literals()], ['げんき', 'second'])
        self.assertEqual(len(parsed.sites[1]), 2)  # the tiny method and the fat one; the ldc.i4 decoy is not counted
        patched = dotnet.Assembly(parsed.patch({1: ('げんき', 'Motivation, at some length, é')}))
        self.assertEqual(sorted(text for _, text in patched.literals()), ['Motivation, at some length, é', 'second'])
        self.assertIn(b'\x20\x72\x01\x00\x00', patched.data)
        with self.assertRaisesRegex(ValueError, 'changed'): parsed.patch({1: ('other', 'x')})
        with self.assertRaises(ValueError): dotnet.Assembly(raw[:600])
        with self.assertRaises(ValueError): dotnet.Assembly(b'MZ' + b'\0' * 200)

    def test_width_counts_full_width_cells_and_ignores_tags(self):
        self.assertEqual(unity.display_width('閉じる'), 6)
        self.assertEqual(unity.display_width('Close\nit now'), 6)
        self.assertEqual(unity.display_width('<b>{0}</b>ab'), 2)


class StudioUnityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp'); self.game = game(self.tmp.name)
        self.studio = Studio(Path(self.tmp.name) / 'data')
        self.before = {p: p.read_bytes() for p in self.game.rglob('*') if p.is_file()}

    def tearDown(self):
        self.assertEqual({p: p.read_bytes() for p in self.game.rglob('*') if p.is_file()}, self.before, 'the game folder was modified')
        self.tmp.cleanup()

    def units(self, draft):
        return {u['source']: u for u in self.studio.get(draft, limit=100)['units']}

    def test_inspect_finds_text_in_all_three_carriers_and_nothing_else(self):
        info = self.studio.inspect(str(self.game))
        self.assertEqual(info['engine'], 'unity'); self.assertEqual(info['unity_version'], '6000.0.45f1')
        units = self.units(info['draft_id'])
        self.assertEqual(set(units), {'こんにちは\n元気ですか？', '会話１', 'お待ちください', 'チョコレート', 'あまいおかし', '閉じる',
                                      '<color=#ff0000>{0}円</color>', '口わらい', 'カレー', 'お金が足りません！', '{0}は{1}個です'})
        self.assertEqual(units['チョコレート']['kind'], 'mono:Item'); self.assertEqual(units['閉じる']['kind'], 'mono:TMPro.TextMeshProUGUI')
        self.assertEqual(units['カレー']['kind'], 'mono:Item')  # script resolved through the external file reference
        self.assertEqual(units['こんにちは\n元気ですか？']['kind'], 'textasset:text')
        self.assertEqual(units['こんにちは\n元気ですか？']['context'], {'asset': 'scene_one', 'id': '0001', 'type': 1, 'characterID': '0007', 'voice': 606})
        self.assertEqual(units['お金が足りません！']['kind'], 'code:string')
        self.assertEqual(info['files'], {'resources.assets': 8, 'sharedassets0.assets': 1, 'Managed/Assembly-CSharp.dll': 2})
        self.assertIn('1 font/sprite table strings left out', info['notes'])
        self.assertEqual(self.studio.inspect(str(self.game / 'Game_Data'))['units'], 11)

    def test_object_name_matches_are_blocked_until_allowed(self):
        draft = self.studio.inspect(str(self.game))['draft_id']; unit = self.units(draft)['口わらい']
        self.assertIn('name of a game object', unit['blocked_reason'])
        with self.assertRaisesRegex(ValueError, 'name of a game object'): self.studio.translate(draft, unit['id'], 'Mouth')
        allowed = self.studio.inspect(str(self.game), allow_name_matches=True)
        self.assertEqual(allowed['blocked_name_matches'], 0)
        self.studio.translate(allowed['draft_id'], self.units(allowed['draft_id'])['口わらい']['id'], 'Mouth')

    def test_placeholders_and_tags_must_survive(self):
        draft = self.studio.inspect(str(self.game))['draft_id']; units = self.units(draft)
        with self.assertRaisesRegex(ValueError, 'placeholder'): self.studio.translate(draft, units['{0}は{1}個です']['id'], 'Needs {0} or more')
        with self.assertRaisesRegex(ValueError, 'placeholder'): self.studio.translate(draft, units['<color=#ff0000>{0}円</color>']['id'], '{0} yen')
        with self.assertRaisesRegex(ValueError, 'empty'): self.studio.translate(draft, units['閉じる']['id'], '  ')
        with self.assertRaisesRegex(ValueError, 'control characters'): self.studio.translate(draft, units['閉じる']['id'], 'Clo\x00se')
        self.studio.translate(draft, units['{0}は{1}個です']['id'], 'Needs {1} or more {0}')
        self.studio.translate(draft, units['<color=#ff0000>{0}円</color>']['id'], '<color=#ff0000>{0} yen</color>')
        self.assertTrue(self.studio.validate(draft)['structural_ok'])

    def test_export_writes_patched_copies_that_read_back(self):
        draft = self.studio.inspect(str(self.game))['draft_id']; units = self.units(draft)
        wanted = {'こんにちは\n元気ですか？': 'Um...\nIs this seat "free"? \\ é', '会話１': 'Talk 1', 'チョコレート': 'Chocolate', 'あまいおかし': 'A single piece of happiness, much longer than before',
                  '閉じる': 'X', 'カレー': 'Curry', 'お金が足りません！': 'Not enough motivation!', '{0}は{1}個です': 'Requires {0} of {1} or more'}
        for source, text in wanted.items(): self.studio.translate(draft, units[source]['id'], text)
        report = self.studio.validate(draft)
        self.assertEqual((report['translated'], report['untranslated'], report['blocked']), (8, 2, 1))
        self.assertIn(units['あまいおかし']['id'], [w['unit'] for w in report['wider_than_source_units']])
        result = self.studio.export(draft); out = Path(result['path'])
        self.assertEqual(out.name, 'Game_Data')
        self.assertEqual(sorted(f['file'] for f in result['files']), ['Managed/Assembly-CSharp.dll', 'resources.assets', 'sharedassets0.assets'])
        self.assertEqual(sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file()), ['Managed/Assembly-CSharp.dll', 'resources.assets', 'sharedassets0.assets'])
        for path in out.rglob('*'):
            if path.is_file(): self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        # Re-inspecting the exported copy shows the translations in place and everything else unchanged.
        original, patched = unity.SerializedFile(self.before[self.game / 'Game_Data' / 'resources.assets']), unity.SerializedFile((out / 'resources.assets').read_bytes())
        for path_id in (2, 3, 4, 7, 8, 9, 10, 11):
            self.assertEqual(patched.payload(patched.by_id[path_id]), original.payload(original.by_id[path_id]))
        name, text, _ = unity.text_asset(patched.payload(patched.by_id[1]))
        document = json.loads(text.lstrip('\ufeff'))
        self.assertEqual(document[0]['text'], wanted['こんにちは\n元気ですか？']); self.assertEqual(document[1]['name'], 'Talk 1')
        self.assertEqual(document[1]['arguments'], [{'value': 'お待ちください'}, {'value': '0002'}])
        self.assertEqual(text.replace(json.dumps(wanted['こんにちは\n元気ですか？'], ensure_ascii=False), '"こんにちは\\n元気ですか？"').replace('"Talk 1"', '"会話１"'), SCENARIO)
        item = patched.payload(patched.by_id[5])
        self.assertEqual(item, behaviour(3, 'Chocolate', 'Chocolate', struct.pack('<ii', 120, 3), wanted['あまいおかし'], struct.pack('<f', 1.5)))
        self.assertEqual(patched.payload(patched.by_id[6]), behaviour(4, '', struct.pack('<iiii', 0, 0, 0, 0), 'X', struct.pack('<ii', 7, 9), '<color=#ff0000>{0}円</color>'))
        literals = [text for _, text in dotnet.Assembly((out / 'Managed' / 'Assembly-CSharp.dll').read_bytes()).literals()]
        self.assertEqual(sorted(literals), sorted(['Not enough motivation!', 'Assets/Prefabs', 'Requires {0} of {1} or more']))
        (Path(self.tmp.name) / 'copy').mkdir(); copy = Path(self.tmp.name) / 'copy' / 'Game_Data'
        import shutil; shutil.copytree(self.game / 'Game_Data', copy); shutil.copytree(out, copy, dirs_exist_ok=True)
        again = self.units(self.studio.inspect(str(copy.parent), text_filter='cjk')['draft_id'])
        self.assertEqual(set(again), {'お待ちください', '<color=#ff0000>{0}円</color>', '口わらい'})

    def test_units_file_round_trip_reports_bad_lines_and_keeps_good_ones(self):
        draft = self.studio.inspect(str(self.game))['draft_id']; units = self.units(draft)
        listing = self.studio.units_file(draft); path = Path(listing['path'])
        self.assertEqual((listing['units'], listing['blocked_left_out']), (10, 1)); self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertNotIn('口わらい', [row['source'] for row in rows])
        filled = Path(self.tmp.name) / 'filled.jsonl'; lines = []
        for row in rows:
            if row['source'] == '閉じる': row['translation'] = 'Close'
            elif row['source'] == 'カレー': row['translation'] = 'Curry'
            elif row['source'] == '{0}は{1}個です': row['translation'] = 'dropped the placeholders'
            lines.append(json.dumps(row, ensure_ascii=False))
        lines += ['not json', json.dumps({'id': 999, 'translation': 'x'}), json.dumps({'id': units['チョコレート']['id'], 'source': 'something else', 'translation': 'Chocolate'}),
                  json.dumps({'id': units['口わらい']['id'], 'translation': 'Mouth'}), '']
        filled.write_text('\n'.join(lines), encoding='utf-8')
        result = self.studio.import_translations(draft, str(filled))
        self.assertEqual((result['saved'], result['rejected'], result['without_translation'], result['translated']), (2, 5, 7, 2))
        self.assertEqual(sorted(r['line'] for r in result['rejected_lines']), [10, 11, 12, 13, 14])  # the dropped placeholders, then the four appended bad lines
        self.assertEqual(self.studio.import_translations(draft, str(filled))['unchanged'], 2)
        self.assertEqual(self.studio.units_file(draft, only_untranslated=True)['units'], 8)
        with self.assertRaises(ValueError): self.studio.import_translations(draft, 'relative.jsonl')

    def test_tampered_stored_source_refuses_export(self):
        draft = self.studio.inspect(str(self.game))['draft_id']
        self.studio.translate(draft, self.units(draft)['カレー']['id'], 'Curry')
        (self.studio.root / draft / 'source' / 'sharedassets0.assets').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'source bytes changed'): self.studio.export(draft)

    def test_export_without_translations_and_wrong_arguments(self):
        draft = self.studio.inspect(str(self.game))['draft_id']
        with self.assertRaisesRegex(ValueError, 'Nothing is translated'): self.studio.export(draft)
        with self.assertRaisesRegex(ValueError, 'apply only to RPG Maker'): self.studio.inspect(str(self.game), message_rows=4)
        with self.assertRaisesRegex(ValueError, 'text_filter must be'): self.studio.inspect(str(self.game), text_filter='klingon')
        source = Path(self.tmp.name) / 'Actors.json'; source.write_text('[null]')
        with self.assertRaisesRegex(ValueError, 'apply only to a Unity'): self.studio.inspect(str(source), text_filter='all')
        empty = Path(self.tmp.name) / 'empty'; empty.mkdir()
        with self.assertRaisesRegex(ValueError, 'Choose a Unity game folder'): self.studio.inspect(str(empty))
        hidden = Path(self.tmp.name) / '.config' / 'Game'; hidden.parent.mkdir(); hidden.mkdir()
        with self.assertRaisesRegex(ValueError, 'Credential/configuration'): self.studio.inspect(str(hidden))

    def test_packed_and_il2cpp_builds_say_so(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            packed = Path(tmp) / 'P' / 'P_Data'; packed.mkdir(parents=True); (packed / 'data.unity3d').write_bytes(b'UnityFS\0')
            with self.assertRaisesRegex(ValueError, 'data.unity3d'): self.studio.inspect(str(packed.parent))
            native = game(tmp, with_dll=False); (native / 'GameAssembly.dll').write_bytes(b'MZ')
            info = self.studio.inspect(str(native))
            self.assertIn('IL2CPP build: text compiled into code is not covered', info['notes'])
            self.assertNotIn('Managed/Assembly-CSharp.dll', info['files'])

    def test_all_filter_reaches_ascii_text(self):
        info = self.studio.inspect(str(self.game), text_filter='all')
        sources = set(self.units(info['draft_id']))
        self.assertIn('Assets/Prefabs', sources); self.assertIn('チョコレート', sources)

    def test_rpg_maker_drafts_still_work_beside_unity_ones(self):
        source = Path(self.tmp.name) / 'Actors.json'; source.write_text(json.dumps([None, {'name': 'Original'}]))
        draft = self.studio.inspect(str(source))['draft_id']
        listing = self.studio.units_file(draft); row = json.loads(Path(listing['path']).read_text())
        self.assertEqual((row['id'], row['source'], row['kind']), (0, 'Original', 'database'))
        filled = Path(self.tmp.name) / 't.jsonl'; filled.write_text(json.dumps({'id': 0, 'translation': 'Translated'}))
        self.assertEqual(self.studio.import_translations(draft, str(filled))['saved'], 1)
        self.assertEqual(json.loads(Path(self.studio.export(draft)['path']).read_text())[1]['name'], 'Translated')
        self.studio.inspect(str(self.game))
        self.assertEqual(sorted(d['source_name'] for d in self.studio.list_drafts()['drafts']), ['Actors.json', 'Game_Data'])


if __name__ == '__main__':
    unittest.main()
