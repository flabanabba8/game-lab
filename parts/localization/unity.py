"""Unity player builds (Mono, loose serialized files): find translatable text and write patched copies.

Pure Python, no type trees needed. Three text carriers are read:

* TextAsset objects whose content is JSON: every string value, addressed by its JSON path;
* MonoBehaviour objects (scene/prefab components and ScriptableObjects): length-prefixed UTF-8 fields;
* string literals of Managed/Assembly-CSharp*.dll (see dotnet.py).

Only serialized-file format 22, little-endian, is read. Asset bundles (UnityFS), IL2CPP code and
text drawn into images are not covered. Nothing here starts a game or proves it still loads.
"""
import json
import re
import struct
import unicodedata
from json.decoder import scanstring
from pathlib import Path

from . import dotnet

FORMAT = 22
MAX_FILE = 256 * 1024 * 1024
MAX_STRING = 65536
TEXT_ASSET, MONO_BEHAVIOUR, MONO_SCRIPT, GAME_OBJECT = 49, 114, 115, 1
CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff66-\uff9f]')
FILTERS = {
    'cjk': lambda s: bool(CJK.search(s)),
    'non_ascii': lambda s: any(ord(c) > 0x7f and c.isalpha() for c in s),
    'all': lambda s: sum(c.isalpha() for c in s) >= 2,
}
# Composite-format placeholders ({0}, {2:#,0}) and TextMeshPro rich-text tags (<color=#fff>, </b>).
TOKENS = re.compile(r'\{\d+(?:[,:][^{}\r\n]*)?\}|</?[A-Za-z#][^<>\r\n]*>')
HIGH = re.compile(rb'[\x80-\xff]')
NOT_TEXT = {'mono:TMPro.TMP_FontAsset', 'mono:TMPro.TMP_SpriteAsset', 'mono:TMPro.TMP_Settings', 'mono:TMPro.TMP_StyleSheet'}
SKIP_SUFFIXES = ('.ress', '.resource', '.json', '.config', '.info', '.txt', '.xml', '.dll', '.exe')


def tokens(text):
    return sorted(TOKENS.findall(text))


def display_width(text):
    """Widest row in terminal-style cells: full-width characters count 2."""
    return max((sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in TOKENS.sub('', row))
                for row in str(text).replace('\r', '').split('\n')), default=0)


def read_string(blob, pos, limit=MAX_STRING):
    """Unity aligned string: int32 length, UTF-8 bytes, zero padding to 4. Returns (bytes, next position)."""
    if pos < 0 or pos + 4 > len(blob): raise ValueError('string outside object')
    size = struct.unpack_from('<I', blob, pos)[0]
    if size > limit or pos + 4 + size > len(blob): raise ValueError('string outside object')
    return blob[pos + 4:pos + 4 + size], (pos + 4 + size + 3) & ~3


def pack_string(raw):
    return struct.pack('<I', len(raw)) + raw + b'\0' * (-len(raw) % 4)


def plain_text(raw):
    """Decode a candidate field; None unless it is clean text."""
    try: text = raw.decode('utf-8')
    except UnicodeDecodeError: return None
    if any(ord(c) < 0x20 and c not in '\t\r\n' for c in text): return None
    return text


class SerializedFile:
    """Object table of one serialized file (format 22). Object payloads are opaque byte strings."""

    def __init__(self, data):
        self.data = data
        try: self._parse()
        except (struct.error, IndexError, ValueError) as exc:
            raise ValueError('Not a supported Unity serialized file (%s)' % (exc or 'truncated')) from None

    def _parse(self):
        d = self.data
        if len(d) < 64 or d[:8] != b'\0' * 8: raise ValueError('no format-22 header')
        version = struct.unpack_from('>I', d, 8)[0]
        if version != FORMAT: raise ValueError('serialized-file format %d; only %d is supported' % (version, FORMAT))
        if d[16] != 0: raise ValueError('big-endian file')
        self.metadata_size, self.file_size, self.data_offset = struct.unpack_from('>Iqq', d, 20)
        if self.file_size != len(d) or not 48 < self.data_offset <= len(d): raise ValueError('header sizes do not match the file')
        p = d.index(b'\0', 48); self.unity_version = d[48:p].decode('ascii', 'replace'); p += 1 + 4
        type_tree = d[p]; p += 1
        count = struct.unpack_from('<i', d, p)[0]; p += 4
        classes = []
        for _ in range(count):
            class_id = struct.unpack_from('<i', d, p)[0]; p += 7
            p += 32 if class_id == MONO_BEHAVIOUR else 16
            if type_tree:
                nodes, strings = struct.unpack_from('<ii', d, p); p += 8 + nodes * 32 + strings
                p += 4 + 4 * struct.unpack_from('<i', d, p)[0]
            classes.append(class_id)
        count = struct.unpack_from('<i', d, p)[0]; p += 4
        self.objects = []
        for _ in range(count):
            p = (p + 3) & ~3
            path_id, start, size, type_index = struct.unpack_from('<qqIi', d, p)
            if start < 0 or self.data_offset + start + size > len(d): raise ValueError('object outside the file')
            self.objects.append({'path_id': path_id, 'start': start, 'size': size, 'class_id': classes[type_index], 'entry': p}); p += 24
        count = struct.unpack_from('<i', d, p)[0]; p += 4
        for _ in range(count): p = ((p + 4 + 3) & ~3) + 8
        count = struct.unpack_from('<i', d, p)[0]; p += 4
        self.externals = []
        for _ in range(count):
            p = d.index(b'\0', p) + 1 + 16 + 4
            end = d.index(b'\0', p); self.externals.append(d[p:end].decode('utf-8', 'replace')); p = end + 1
        if p > self.data_offset: raise ValueError('metadata overruns the data section')
        self.by_id = {o['path_id']: o for o in self.objects}
        if len(self.by_id) != len(self.objects): raise ValueError('duplicate object IDs')

    def payload(self, obj):
        start = self.data_offset + obj['start']
        return self.data[start:start + obj['size']]

    def rebuild(self, replacements):
        """Return new file bytes with some object payloads replaced; later objects move, nothing else changes."""
        objs = self.objects
        if any(a['start'] + a['size'] > b['start'] for a, b in zip(objs, objs[1:])):
            raise ValueError('Objects are not stored in table order; refusing to rewrite this file')
        align = next(a for a in (16, 8, 4, 1) if all(o['start'] % a == 0 for o in objs))
        d = self.data; out = bytearray(d[:self.data_offset + (objs[0]['start'] if objs else 0)])
        old_end = new_end = None
        for obj in objs:
            body = replacements.get(obj['path_id'])
            if body is None: body = self.payload(obj)
            if old_end is None or new_end == old_end:
                new_start = obj['start']
                if old_end is not None: out += d[self.data_offset + old_end:self.data_offset + obj['start']]
            else:
                extra = max(0, obj['start'] - old_end - (-old_end % align))  # spacing beyond plain alignment
                new_start = new_end + extra; new_start += -new_start % align
                out += b'\0' * (self.data_offset + new_start - len(out))
            out += body
            struct.pack_into('<qI', out, obj['entry'] + 8, new_start, len(body))
            old_end, new_end = obj['start'] + obj['size'], new_start + len(body)
        if objs: out += d[self.data_offset + old_end:]
        struct.pack_into('>q', out, 24, len(out))
        return bytes(out)


def json_spans(text):
    """[(path, start, end, value)] for every string VALUE of a JSON document, with its exact character span."""
    spans, blank = [], re.compile(r'[ \t\r\n]*')
    scalar = re.compile(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null')
    ws = lambda i: blank.match(text, i).end()

    def value(i, path):
        i = ws(i); c = text[i:i + 1]
        if c == '"':
            parsed, end = scanstring(text, i + 1); spans.append((path, i, end, parsed)); return end
        if c in ('{', '['):
            close, index = ('}', None) if c == '{' else (']', 0)
            i = ws(i + 1); keys = set()
            if text[i:i + 1] == close: return i + 1
            while True:
                if index is None:
                    if text[i:i + 1] != '"': raise ValueError('key expected')
                    key, i = scanstring(text, i + 1); i = ws(i)
                    if key in keys: raise ValueError('duplicate keys')
                    keys.add(key)
                    if text[i:i + 1] != ':': raise ValueError('colon expected')
                    i += 1
                else: key = index; index += 1
                i = ws(value(i, path + (key,)))
                if text[i:i + 1] == ',': i = ws(i + 1)
                elif text[i:i + 1] == close: return i + 1
                else: raise ValueError('separator expected')
        match = scalar.match(text, i)
        if not match: raise ValueError('value expected')
        return match.end()

    if ws(value(1 if text[:1] == '\ufeff' else 0, ())) != len(text): raise ValueError('trailing data')
    return spans


def text_asset(blob):
    """(name, script text, position of the script field) of a TextAsset holding a JSON document, else None."""
    try:
        name, pos = read_string(blob, 0); script, _ = read_string(blob, pos, MAX_FILE)
        text = script.decode('utf-8')
    except (ValueError, UnicodeDecodeError): return None
    if text.lstrip('\ufeff \t\r\n')[:1] not in ('[', '{'): return None
    return name.decode('utf-8', 'replace'), text, pos


def mono_strings(blob, wanted):
    """[(offset, text)] of aligned string fields after m_Name in a MonoBehaviour payload."""
    try: _, pos = read_string(blob, 28)
    except ValueError: return []
    found = []
    while pos + 4 <= len(blob):
        size = struct.unpack_from('<I', blob, pos)[0]
        end = pos + 4 + size
        if 0 < size <= MAX_STRING and end <= len(blob) and not blob[end:(end + 3) & ~3].strip(b'\0'):
            text = plain_text(blob[pos + 4:end])
            if text is not None and wanted(text):
                found.append((pos, text)); pos = (end + 3) & ~3; continue
        pos += 4
    return found


def object_name(obj, blob):
    try:
        if obj['class_id'] == GAME_OBJECT: pos = 8 + 12 * struct.unpack_from('<I', blob, 0)[0]
        elif obj['class_id'] == MONO_BEHAVIOUR: pos = 28
        else: pos = 0
        raw, _ = read_string(blob, pos)
    except (ValueError, struct.error): return None
    return plain_text(raw) if 0 < len(raw) <= 256 else None


def find_data_dir(source):
    """The <Game>_Data folder for a game folder, or the folder itself when it is one."""
    if (source / 'globalgamemanagers').is_file() or (source / 'data.unity3d').is_file(): return source
    found = sorted(p for p in source.iterdir() if p.is_dir() and not p.is_symlink() and p.name.endswith('_Data')
                   and ((p / 'globalgamemanagers').is_file() or (p / 'data.unity3d').is_file()))
    if len(found) != 1: raise ValueError('Choose a Unity game folder (the one holding <Game>_Data) or the _Data folder itself')
    return found[0]


def scan(data_dir, text_filter='cjk', allow_name_matches=False):
    """Read a _Data folder. Returns (units, {relative path: bytes of every file that has units}, report)."""
    if text_filter not in FILTERS: raise ValueError('text_filter must be one of: ' + ', '.join(FILTERS))
    wanted = FILTERS[text_filter]; quick = text_filter != 'all'
    if (data_dir / 'data.unity3d').is_file(): raise ValueError('This build packs its data into data.unity3d (UnityFS); only loose serialized files are supported')
    notes, units, sources, names, scripts, pending = [], [], {}, set(), {}, []
    if (data_dir.parent / 'GameAssembly.dll').exists() or (data_dir / 'il2cpp_data').exists():
        notes.append('IL2CPP build: text compiled into code is not covered')
    unity_version = None
    for path in sorted(data_dir.iterdir()):
        if path.is_symlink() or not path.is_file() or path.name.lower().endswith(SKIP_SUFFIXES): continue
        size = path.stat().st_size
        with path.open('rb') as stream: head = stream.read(12)
        if len(head) < 12 or head[:8] != b'\0' * 8 or struct.unpack('>I', head[8:])[0] > 64: continue
        if size > MAX_FILE: notes.append('%s skipped: larger than 256 MiB' % path.name); continue
        data = path.read_bytes()
        try: parsed = SerializedFile(data)
        except ValueError as exc: notes.append('%s skipped: %s' % (path.name, exc)); continue
        unity_version = unity_version or parsed.unity_version
        used = False
        for obj in parsed.objects:
            blob = parsed.payload(obj); class_id = obj['class_id']
            if class_id == MONO_SCRIPT:
                try:
                    _, p = read_string(blob, 0); cls, p = read_string(blob, p + 20); namespace, _ = read_string(blob, p)
                    scripts[(path.name, obj['path_id'])] = '.'.join(x.decode('utf-8', 'replace') for x in (namespace, cls) if x)
                except (ValueError, struct.error): pass
                continue
            if quick and not HIGH.search(blob): continue
            name = object_name(obj, blob)
            if class_id == TEXT_ASSET:
                asset = text_asset(blob)
                if not asset: continue
                try: spans = json_spans(asset[1]); document = json.loads(asset[1].lstrip('\ufeff'))
                except (ValueError, RecursionError): notes.append('%s: text asset %r is not plain JSON, skipped' % (path.name, asset[0])); continue
                for jpath, _, _, value in spans:
                    if not value or not wanted(value): continue
                    parent = document
                    for part in jpath[:-1]: parent = parent[part]
                    context = {'asset': asset[0]}
                    if isinstance(parent, dict):
                        context.update({k: v for k, v in parent.items() if k != jpath[-1] and isinstance(v, (str, int)) and not isinstance(v, bool) and len(str(v)) <= 24 and not wanted(str(v))})
                    key = next((p for p in reversed(jpath) if isinstance(p, str)), '')
                    units.append({'path': [path.name, obj['path_id'], 'json', *jpath], 'source': value, 'kind': 'textasset:' + key, 'context': context}); used = True
                continue
            if name and wanted(name): names.add(name)
            if class_id != MONO_BEHAVIOUR or len(blob) < 32: continue
            file_id, script_id = struct.unpack_from('<iq', blob, 16)
            target = path.name if file_id == 0 else Path(parsed.externals[file_id - 1]).name if 0 < file_id <= len(parsed.externals) else None
            for offset, text in mono_strings(blob, wanted):
                unit = {'path': [path.name, obj['path_id'], 'mb', offset], 'source': text, 'kind': 'mono:?', 'context': {'object': name or ''}}
                units.append(unit); pending.append((unit, (target, script_id))); used = True
        if used: sources[path.name] = data
    for unit, key in pending: unit['kind'] = 'mono:' + scripts.get(key, '?')
    dropped = sum(u['kind'] in NOT_TEXT for u in units)  # font character tables and the like are data, not wording
    if dropped:
        units = [u for u in units if u['kind'] not in NOT_TEXT]
        notes.append('%d font/sprite table strings left out' % dropped)
    managed = data_dir / 'Managed'
    if managed.is_dir() and not managed.is_symlink():
        for path in sorted(managed.glob('Assembly-CSharp*.dll')):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE: continue
            data = path.read_bytes(); rel = 'Managed/' + path.name
            try: literals = dotnet.Assembly(data).literals()
            except ValueError as exc: notes.append('%s skipped: %s' % (rel, exc)); continue
            found = [(offset, text) for offset, text in literals if wanted(text)]
            for offset, text in found:
                units.append({'path': [rel, 0, 'us', offset], 'source': text, 'kind': 'code:string', 'context': {'assembly': path.name}})
            if found: sources[rel] = data
    blocked = 0
    for index, unit in enumerate(units):
        unit.update(id=index, group=None, translation=None)
        if unit['source'] in names and not allow_name_matches:
            unit['blocked_reason'] = 'The same text is the name of a game object or asset, so code may look it up by name; re-inspect with allow_name_matches=true to translate it anyway'
            blocked += 1
    sources = {rel: data for rel, data in sources.items() if any(u['path'][0] == rel for u in units)}
    if not sources: notes.append('No matching text was found')
    return units, sources, {'unity_version': unity_version, 'notes': notes, 'blocked_name_matches': blocked}


def patch_serialized(data, edits):
    """edits: [(unit, translation)] of one serialized file. Returns the new bytes, re-read and checked."""
    parsed = SerializedFile(data); per_object = {}
    for unit, text in edits: per_object.setdefault(unit['path'][1], []).append((unit, text))
    replacements, expected = {}, {}
    for path_id, items in per_object.items():
        obj = parsed.by_id.get(path_id)
        if obj is None: raise ValueError('Source object %d is missing' % path_id)
        blob = parsed.payload(obj); mode = items[0][0]['path'][2]
        if any(unit['path'][2] != mode for unit, _ in items): raise ValueError('Mixed addresses in object %d' % path_id)
        if mode == 'json':
            asset = text_asset(blob)
            if not asset: raise ValueError('Object %d is no longer a JSON text asset' % path_id)
            _, text, pos = asset
            spans = {span[0]: span for span in json_spans(text)}; chosen = []
            for unit, new in items:
                span = spans.get(tuple(unit['path'][3:]))
                if span is None or span[3] != unit['source']: raise ValueError('Source text changed at unit %d' % unit['id'])
                chosen.append((span[1], span[2], new))
            for start, end, new in sorted(chosen, reverse=True):
                text = text[:start] + json.dumps(new, ensure_ascii=False) + text[end:]
            _, after = read_string(blob, pos, MAX_FILE)
            body = blob[:pos] + pack_string(text.encode('utf-8')) + blob[after:]
            check = {tuple(u['path'][3:]): new for u, new in items}
            expected[path_id] = ('json', check)
        elif mode == 'mb':
            body = blob; shift = 0; placed = []
            for unit, new in sorted(items, key=lambda item: item[0]['path'][3]):
                offset = unit['path'][3]
                raw, end = read_string(blob, offset)
                if raw != unit['source'].encode('utf-8'): raise ValueError('Source text changed at unit %d' % unit['id'])
                packed = pack_string(new.encode('utf-8'))
                body = body[:offset + shift] + packed + body[end + shift:]
                placed.append((offset + shift, new)); shift += len(packed) - (end - offset)
            expected[path_id] = ('mb', placed)
        else: raise ValueError('Unknown address kind %r' % mode)
        replacements[path_id] = body
    output = parsed.rebuild(replacements)
    again = SerializedFile(output)
    if [(o['path_id'], o['class_id']) for o in again.objects] != [(o['path_id'], o['class_id']) for o in parsed.objects]:
        raise ValueError('Rebuilt file lost its object table')
    for before, after in zip(parsed.objects, again.objects):
        blob = again.payload(after); want = expected.get(after['path_id'])
        if want is None:
            if blob != parsed.payload(before): raise ValueError('An untouched object changed during rebuild')
        elif want[0] == 'json':
            asset = text_asset(blob)
            got = {span[0]: span[3] for span in json_spans(asset[1])} if asset else {}
            if any(got.get(key) != value for key, value in want[1].items()): raise ValueError('Rebuilt text asset does not read back')
        elif any(read_string(blob, offset)[0] != value.encode('utf-8') for offset, value in want[1]):
            raise ValueError('Rebuilt component does not read back')
    return output


def patch_file(rel, data, edits):
    if not edits: return data
    if edits[0][0]['path'][2] == 'us':
        return dotnet.Assembly(data).patch({unit['path'][3]: (unit['source'], text) for unit, text in edits})
    return patch_serialized(data, edits)
