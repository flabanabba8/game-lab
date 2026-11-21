"""Godot 4 importer/exporter for translation drafts.

Reads an unencrypted Godot 4 resource pack (``GDPC`` format 2 or 3; repack needs format 3) and finds text in:

* Dialogue Manager resources (``*.dialogue-<hash>.tres``): the ``text`` of ``dialogue``/``response`` lines and the
  ``character`` speaker names. ``raw_text`` keeps the source and is never shown, so it is not touched.
* Binary scenes/resources (``RSRC``, uncompressed): length-prefixed strings in the body.
* Compiled scripts (``GDSC``, zstd body): String constants (Variant type 4).

Export writes ONE new .pck: every entry is copied, changed entries are replaced. Only entries holding text change.
Texts that equal a script/scene key (animation names, StringName keys) are blocked by default; see ``scan``.
Text drawn into images is not covered (see the godot wiki page for the image workflow).
"""
import hashlib
import os
import re
import struct
from collections import Counter
from pathlib import Path

try:  # Python 3.14+
    from compression import zstd as _zstd
except ImportError:  # pragma: no cover - older Python: zstd optional
    _zstd = None

MAX_PACK = 8 * 1024 * 1024 * 1024
MAX_ENTRY = 64 * 1024 * 1024
MAX_STRING = 20000
CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff66-\uff9f]')
FILTERS = {'cjk': lambda s: bool(CJK.search(s)),
           'non_ascii': lambda s: any(ord(c) > 127 and c.isalpha() for c in s),
           'all': lambda s: sum(c.isalpha() for c in s) >= 2}
# Only real BBCode tags are markup; a bracketed word such as [Bind] is text.
TAG = (r'\[/?(?:color|font_size|font|b|i|u|s|center|right|left|wait|speed|shake|wave|rainbow|pulse|tornado|fade|url|img|br|next|'
       r'outline_size|outline_color|fill)(?:[= ][^\]]*)?\]')
TOKENS = re.compile(TAG + r'|\{\{[^}]*\}\}|%[-+0-9.]*[sdif%]')
DIALOGUE = re.compile(r'\.dialogue-[0-9a-f]{32}\.tres$')
SKIP_PREFIX = ('res://', 'uid://', 'user://', 'local://')
ENTRY = re.compile(r'^"(\d+)": \{$', re.M)
FIELD = re.compile(r'^&"(text|character|type)": "((?:[^"\\]|\\.)*)"', re.M)


def tokens(text):
    return Counter(TOKENS.findall(text))


def plain(text):
    return re.sub(TAG, '', text)


def display_width(text):
    return max((sum(2 if ord(c) > 0x2e7f else 1 for c in line) for line in plain(text).split('\n')), default=0)


# ---------------------------------------------------------------- pack

def read_pack(path):
    """Directory of a .pck: {'fmt','version','head','base','entries':[{name,off,size,md5,flags}]}"""
    size = os.path.getsize(path)
    if size > MAX_PACK: raise ValueError('Pack exceeds 8 GiB')
    with open(path, 'rb') as f:
        head = f.read(112)
        if head[:4] != b'GDPC': raise ValueError('Not a Godot resource pack (no GDPC magic); an exe with an embedded pack is not supported')
        fmt, major, minor, patch = struct.unpack('<4I', head[4:20])
        if fmt not in (2, 3): raise ValueError('Unsupported pack format %d' % fmt)
        flags, base = struct.unpack('<IQ', head[20:32])
        if flags & 1: raise ValueError('Encrypted pack directory is not supported')
        if fmt == 3:
            dir_off, = struct.unpack('<Q', head[32:40]); f.seek(dir_off)
        else:
            base = 0; f.seek(24 + 64)
        n, = struct.unpack('<I', f.read(4))
        if n > 500000: raise ValueError('Pack lists too many files')
        entries = []
        for _ in range(n):
            ln, = struct.unpack('<I', f.read(4))
            if ln > 4096: raise ValueError('Pack path too long')
            name = f.read(ln).rstrip(b'\0').decode('utf-8')
            off, esize = struct.unpack('<2Q', f.read(16)); md5 = f.read(16); efl, = struct.unpack('<I', f.read(4))
            if efl & 1: raise ValueError('Encrypted file in pack is not supported: ' + name)
            if base + off + esize > size: raise ValueError('Pack entry runs past end of file: ' + name)
            entries.append({'name': name, 'off': base + off, 'size': esize, 'md5': md5, 'flags': efl})
    return {'fmt': fmt, 'version': '%d.%d.%d' % (major, minor, patch), 'head': head, 'entries': entries}


def read_entry(path, entry):
    if entry['size'] > MAX_ENTRY: raise ValueError('Pack entry too large: ' + entry['name'])
    with open(path, 'rb') as f:
        f.seek(entry['off']); return f.read(entry['size'])


def write_pack(src_path, index, replacements, out_path):
    """Copy every entry of src into a new format-3 pack, substituting replacements {name: bytes}."""
    if index['fmt'] != 3: raise ValueError('Writing is implemented for pack format 3 only')
    base = 112
    with open(src_path, 'rb') as f, open(out_path, 'xb') as o:
        o.write(index['head']); new = []
        for e in index['entries']:
            o.write(b'\0' * (-o.tell() % 16)); off = o.tell() - base
            if e['name'] in replacements:
                data = replacements[e['name']]; o.write(data); new.append((e, off, len(data), hashlib.md5(data).digest()))
            else:
                f.seek(e['off']); left = e['size']
                while left:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk: raise ValueError('Short read in source pack')
                    o.write(chunk); left -= len(chunk)
                new.append((e, off, e['size'], e['md5']))
        o.write(b'\0' * (-o.tell() % 16)); dir_off = o.tell()
        o.write(struct.pack('<I', len(new)))
        for e, off, size, md5 in new:
            nb = e['name'].encode('utf-8'); nb += b'\0' * (-len(nb) % 4)
            o.write(struct.pack('<I', len(nb)) + nb + struct.pack('<2Q', off, size) + md5 + struct.pack('<I', e['flags']))
        o.seek(24); o.write(struct.pack('<2Q', base, dir_off))


# ---------------------------------------------------------------- RSRC (binary scene/resource)

def rsrc_offset_table(b):
    """Positions of u64 offsets that shift when the body grows: import-metadata offset + one per internal resource."""
    if b[:4] != b'RSRC': raise ValueError('not RSRC (compressed RSCC is not supported)')
    big, = struct.unpack_from('<I', b, 4)
    if big: raise ValueError('big-endian resource')
    p = 24

    def ustr(p):
        ln, = struct.unpack_from('<I', b, p); return b[p + 4:p + 4 + ln].rstrip(b'\0').decode('utf-8'), p + 4 + ln
    _, p = ustr(p); pos = [p]; p += 8
    flags, = struct.unpack_from('<I', b, p); p += 12
    if flags & 8: _, p = ustr(p)
    p += 44
    n, = struct.unpack_from('<I', b, p); p += 4
    for _ in range(n): _, p = ustr(p)
    n, = struct.unpack_from('<I', b, p); p += 4
    for _ in range(n):
        _, p = ustr(p); _, p = ustr(p)
        if flags & 2: p += 8
    n, = struct.unpack_from('<I', b, p); p += 4
    for _ in range(n):
        path, p = ustr(p)
        if not path.startswith(('local://', 'res://')): raise ValueError('unexpected internal resource path')
        pos.append(p); p += 8
    return pos


def _enc_rsrc(s):
    raw = s.encode('utf-8') + b'\0'; return struct.pack('<I', len(raw)) + raw


def _enc_gdc(s):
    raw = s.encode('utf-8'); return struct.pack('<I', len(raw)) + raw + b'\0' * (-len(raw) % 4)


def scan_rsrc(b, wanted):
    table = rsrc_offset_table(b)
    starts = [struct.unpack_from('<Q', b, p)[0] for p in table[1:]]
    body = min(starts) if starts else len(b)
    out, i, n = [], body, len(b)
    while i + 4 <= n:
        ln, = struct.unpack_from('<I', b, i)
        if 1 < ln < MAX_STRING and i + 4 + ln <= n and b[i + 4 + ln - 1] == 0:
            try: s = b[i + 4:i + 4 + ln - 1].decode('utf-8')
            except UnicodeDecodeError: s = None
            if s and '\0' not in s and not s.startswith(SKIP_PREFIX) and wanted(s):
                out.append((i, s)); i += 4 + ln; continue
        i += 1
    return out


def gdc_unpack(b):
    if b[:4] != b'GDSC': raise ValueError('not GDSC')
    ver, size = struct.unpack_from('<2I', b, 4)
    if not size: return ver, b[12:]
    if _zstd is None: raise ValueError('compiled scripts need Python 3.14+ (compression.zstd)')
    raw = _zstd.decompress(b[12:])
    if len(raw) != size: raise ValueError('compiled script size mismatch')
    return ver, raw


def gdc_pack(ver, raw):
    if _zstd is None: raise ValueError('compiled scripts need Python 3.14+ (compression.zstd)')
    return b'GDSC' + struct.pack('<2I', ver, len(raw)) + _zstd.compress(raw)


def scan_gdc(raw, wanted):
    out, i, n = [], 0, len(raw)
    while i + 8 <= n:
        ln, = struct.unpack_from('<I', raw, i + 4)
        if raw[i:i + 4] == b'\x04\0\0\0' and 0 < ln < MAX_STRING and i + 8 + ln <= n:
            try: s = raw[i + 8:i + 8 + ln].decode('utf-8')
            except UnicodeDecodeError: s = None
            if s and '\0' not in s and not s.startswith(SKIP_PREFIX) and wanted(s):
                out.append((i + 4, s)); i += 8 + ln + (-ln) % 4; continue
        i += 1
    return out


def patch_strings(b, edits, kind):
    """edits: [(offset_of_length, old, new)]; kind 'rsrc' shifts the RSRC offset table, 'gdc' is an unpacked body."""
    enc = _enc_rsrc if kind == 'rsrc' else _enc_gdc
    table = rsrc_offset_table(b) if kind == 'rsrc' else []
    orig = [struct.unpack_from('<Q', b, p)[0] for p in table]; shift = [0] * len(table)
    out, cur = bytearray(), 0
    for off, old, new in sorted(edits):
        eo, en = enc(old), enc(new)
        if off < cur or b[off:off + len(eo)] != eo: raise ValueError('source string changed at offset %d' % off)
        out += b[cur:off] + en; cur = off + len(eo)
        for k, o in enumerate(orig):
            if o > off: shift[k] += len(en) - len(eo)
    out += b[cur:]
    for p, o, d in zip(table, orig, shift):
        if o: struct.pack_into('<Q', out, p, o + d)
    return bytes(out)


# ---------------------------------------------------------------- Dialogue Manager

_ESC = {'n': '\n', 't': '\t', '"': '"', '\\': '\\', 'r': '\r'}


def _unesc(s):
    return re.sub(r'\\(.)', lambda m: _ESC.get(m.group(1), '\\' + m.group(1)), s)


def _esc(s):
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def scan_dialogue(text, wanted):
    """[(field, span_start, span_end, value, line_id, speaker)] for line text and speaker names, before raw_text."""
    head = text.partition('\nraw_text = ')[0]
    starts = [(m.start(), m.group(1)) for m in ENTRY.finditer(head)]
    out = []
    for k, (pos, lid) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(head)
        fields = {}
        for m in FIELD.finditer(head, pos, end): fields.setdefault(m.group(1), (_unesc(m.group(2)), m.start(2), m.end(2)))
        typ = fields.get('type', ('',))[0]
        if typ not in ('dialogue', 'response'): continue
        who = fields.get('character', ('', 0, 0))[0]
        if 'text' in fields and wanted(fields['text'][0]):
            out.append(('text', fields['text'][1], fields['text'][2], fields['text'][0], lid, who, typ))
        if 'character' in fields and wanted(who):
            out.append(('character', fields['character'][1], fields['character'][2], who, lid, who, typ))
    return out


def patch_dialogue(text, edits):
    """edits: [(start, end, old_value, new_value)] on the escaped spans; the span must still decode to old_value."""
    out, cur = [], 0
    for a, b, old, new in sorted(edits):
        if a < cur or _unesc(text[a:b]) != old: raise ValueError('dialogue line changed')
        out.append(text[cur:a]); out.append(_esc(new)); cur = b
    out.append(text[cur:]); return ''.join(out)


# ---------------------------------------------------------------- scan / patch a whole pack

def scan(pack_path, text_filter='cjk', allow_name_matches=False):
    """Units, the source bytes of every entry holding text, and a report."""
    if text_filter not in FILTERS: raise ValueError('text_filter must be cjk, non_ascii or all')
    wanted = FILTERS[text_filter]
    index = read_pack(pack_path)
    units, sources, notes = [], {}, []
    gdc_failed = 0
    for e in index['entries']:
        name = e['name']
        if name.endswith('.tres') and DIALOGUE.search(name):
            raw = read_entry(pack_path, e)
            try: text = raw.decode('utf-8')
            except UnicodeDecodeError: continue
            found = scan_dialogue(text, wanted)
            if found: sources[name] = raw
            for field, a, b, value, lid, who, typ in found:
                kind = 'speaker' if field == 'character' else typ
                units.append({'path': [name, 'dialogue', a, b], 'source': value, 'kind': kind,
                              'context': {'file': name.rsplit('/', 1)[-1].split('.dialogue-')[0], 'line': lid, 'speaker': who}})
        elif name.endswith(('.scn', '.res')):
            raw = read_entry(pack_path, e)
            if raw[:4] != b'RSRC': continue
            try: found = scan_rsrc(raw, wanted)
            except (ValueError, struct.error): continue
            if found: sources[name] = raw
            for off, s in found:
                units.append({'path': [name, 'rsrc', off], 'source': s, 'kind': 'resource', 'context': {'file': name.rsplit('/', 1)[-1]}})
        elif name.endswith('.gdc'):
            raw = read_entry(pack_path, e)
            try: _, body = gdc_unpack(raw)
            except ValueError: gdc_failed += 1; continue
            found = scan_gdc(body, wanted)
            if found: sources[name] = raw
            for off, s in found:
                units.append({'path': [name, 'gdc', off], 'source': s, 'kind': 'script', 'context': {'file': name.rsplit('/', 1)[-1]}})
    # A UI string equal to a script constant may be looked up by value (animation names, dictionary keys). Block
    # such resource strings and the matching constants unless allowed: the player then sees the source text,
    # which is safer than a broken lookup. Dialogue lines and speaker names are display-only and stay open.
    script_values = {u['source'] for u in units if u['kind'] == 'script'}
    resource_values = {u['source'] for u in units if u['kind'] == 'resource'}
    shared = script_values & resource_values
    blocked = 0
    for k, u in enumerate(units):
        u['id'] = k; u['translation'] = None; u['group'] = None
        if not allow_name_matches and u['kind'] in ('resource', 'script') and u['source'] in shared:
            u['blocked_reason'] = 'Same text is both a scene/resource string and a script constant; code may look it up by value. Re-inspect with allow_name_matches after checking where it is used.'
            blocked += 1
    if gdc_failed: notes.append('%d compiled scripts could not be read and were skipped' % gdc_failed)
    images = sum(1 for e in index['entries'] if e['name'].endswith('.ctex'))
    notes.append('%d textures are not scanned: text drawn into images needs the image workflow' % images)
    return units, sources, {'godot_version': index['version'], 'pack_format': index['fmt'], 'blocked_name_matches': blocked, 'notes': notes}


def patch_entry(name, raw, edits):
    """edits: [(unit, translation)] for one pack entry. Returns the new bytes."""
    mode = edits[0][0]['path'][1]
    if mode == 'dialogue':
        text = raw.decode('utf-8')
        return patch_dialogue(text, [(u['path'][2], u['path'][3], u['source'], t) for u, t in edits]).encode('utf-8')
    if mode == 'rsrc':
        return patch_strings(raw, [(u['path'][2], u['source'], t) for u, t in edits], 'rsrc')
    if mode == 'gdc':
        ver, body = gdc_unpack(raw)
        return gdc_pack(ver, patch_strings(body, [(u['path'][2], u['source'], t) for u, t in edits], 'gdc'))
    raise ValueError('unknown unit address')


def find_pack(source):
    """A .pck file, or a game folder holding exactly one .pck."""
    source = Path(source)
    if source.is_file():
        if source.suffix.lower() != '.pck': raise ValueError('Choose the game .pck file or the folder holding it')
        return source
    packs = sorted(p for p in source.iterdir() if p.suffix.lower() == '.pck' and p.is_file() and not p.is_symlink())
    if len(packs) != 1: raise ValueError('Folder must hold exactly one .pck (found %d); pass the .pck itself' % len(packs))
    return packs[0]


# ---------------------------------------------------------------- textures (.ctex with lossless WebP)

CTEX_HEADER = 56


def ctex_decode(b):
    """PIL image from a CompressedTexture2D whose payload is lossless WebP (the common Godot 4 import)."""
    import io
    from PIL import Image
    if b[:4] != b'GST2' or b[CTEX_HEADER:CTEX_HEADER + 4] != b'RIFF': raise ValueError('not a lossless-WebP GST2 texture')
    n, = struct.unpack_from('<I', b, CTEX_HEADER - 4)
    if n != len(b) - CTEX_HEADER: raise ValueError('WebP length field disagrees with file size')
    im = Image.open(io.BytesIO(b[CTEX_HEADER:])); im.load(); return im


def ctex_encode(original, image):
    """Replace the picture inside texture bytes; size must match."""
    import io
    old = ctex_decode(original)
    if image.size != old.size: raise ValueError('image size %r differs from texture %r' % (image.size, old.size))
    buf = io.BytesIO(); image.convert(old.mode).save(buf, 'WEBP', lossless=True, quality=100, method=6, exact=True)
    data = buf.getvalue(); head = bytearray(original[:CTEX_HEADER]); struct.pack_into('<I', head, CTEX_HEADER - 4, len(data))
    return bytes(head) + data
