"""String literals of a managed (.NET/Mono) assembly: list the ones code loads, and write a patched copy.

The literals live in the #US metadata heap and are referenced by `ldstr` instructions. To change one
without moving any code, the whole metadata block is copied to the end of the last PE section with the
new strings appended to #US, and only the `ldstr` operands of the changed literals are redirected.
Method bodies are walked instruction by instruction, so no byte pattern is guessed at.
"""
import struct

ONE = {0x0E: 1, 0x0F: 1, 0x10: 1, 0x11: 1, 0x12: 1, 0x13: 1, 0x1F: 1, 0x20: 4, 0x21: 8, 0x22: 4, 0x23: 8, 0x27: 4, 0x28: 4, 0x29: 4,
       0x6F: 4, 0x70: 4, 0x71: 4, 0x72: 4, 0x73: 4, 0x74: 4, 0x75: 4, 0x79: 4, 0x7B: 4, 0x7C: 4, 0x7D: 4, 0x7E: 4, 0x7F: 4, 0x80: 4,
       0x81: 4, 0x8C: 4, 0x8D: 4, 0x8F: 4, 0xA3: 4, 0xA4: 4, 0xA5: 4, 0xC2: 4, 0xC6: 4, 0xD0: 4, 0xDD: 4, 0xDE: 1}
ONE.update({op: 1 for op in range(0x2B, 0x38)}); ONE.update({op: 4 for op in range(0x38, 0x45)})
NO_OPERAND = (set(range(0x00, 0x0E)) | set(range(0x14, 0x1F)) | {0x25, 0x26, 0x2A} | set(range(0x46, 0x6F)) | {0x76, 0x7A}
              | set(range(0x82, 0x8C)) | {0x8E} | set(range(0x90, 0xA3)) | set(range(0xB3, 0xBB)) | {0xC3} | set(range(0xD1, 0xDD)) | {0xDF, 0xE0})
TWO = {0x00: 0, 0x01: 0, 0x02: 0, 0x03: 0, 0x04: 0, 0x05: 0, 0x06: 4, 0x07: 4, 0x09: 2, 0x0A: 2, 0x0B: 2, 0x0C: 2, 0x0D: 2, 0x0E: 2,
       0x0F: 0, 0x11: 0, 0x12: 1, 0x13: 0, 0x14: 0, 0x15: 4, 0x16: 4, 0x17: 0, 0x18: 0, 0x19: 1, 0x1A: 0, 0x1C: 4, 0x1D: 0, 0x1E: 0}
SPECIAL = set(range(0x01, 0x09)) | set(range(0x0E, 0x20)) | {0x27, 0x2D, 0x7F}


def compressed(data, pos):
    first = data[pos]
    if first & 0x80 == 0: return first, pos + 1
    if first & 0xC0 == 0x80: return (first & 0x3F) << 8 | data[pos + 1], pos + 2
    if first & 0xE0 == 0xC0: return (first & 0x1F) << 24 | data[pos + 1] << 16 | data[pos + 2] << 8 | data[pos + 3], pos + 4
    raise ValueError('bad compressed length')


def encode_literal(text):
    raw = text.encode('utf-16-le'); size = len(raw) + 1
    flag = any(raw[i + 1] or raw[i] in SPECIAL or raw[i] >= 0x80 for i in range(0, len(raw), 2))
    if size < 0x80: head = bytes([size])
    elif size < 0x4000: head = struct.pack('>H', size | 0x8000)
    else: head = struct.pack('>I', size | 0xC0000000)
    return head + raw + bytes([flag])


class Assembly:
    def __init__(self, data):
        self.data = data
        try: self._parse()
        except (struct.error, IndexError, KeyError) as exc:
            raise ValueError('Not a readable managed assembly (%s)' % type(exc).__name__) from None

    def _offset(self, rva):
        for sec in self.sections:
            if sec['va'] <= rva < sec['va'] + sec['raw_size']: return rva - sec['va'] + sec['raw']
        raise ValueError('address outside the file')

    def _parse(self):
        d = self.data
        if d[:2] != b'MZ': raise ValueError('Not a PE file')
        pe = struct.unpack_from('<I', d, 0x3C)[0]
        if d[pe:pe + 4] != b'PE\0\0': raise ValueError('Not a PE file')
        count, opt_size = struct.unpack_from('<H', d, pe + 6)[0], struct.unpack_from('<H', d, pe + 20)[0]
        self.opt = opt = pe + 24; magic = struct.unpack_from('<H', d, opt)[0]
        if magic not in (0x10B, 0x20B): raise ValueError('Unknown PE optional header')
        dirs = opt + (96 if magic == 0x10B else 112)
        if struct.unpack_from('<I', d, dirs - 4)[0] < 15: raise ValueError('No CLI header: not a managed assembly')
        self.signed = struct.unpack_from('<I', d, dirs + 4 * 8)[0] != 0
        self.sections = []
        for i in range(count):
            s = opt + opt_size + i * 40; vsize, va, raw_size, raw = struct.unpack_from('<IIII', d, s + 8)
            self.sections.append({'header': s, 'va': va, 'vsize': vsize, 'raw_size': raw_size, 'raw': raw})
        cli_rva = struct.unpack_from('<I', d, dirs + 14 * 8)[0]
        if not cli_rva: raise ValueError('No CLI header: not a managed assembly')
        self.cli = self._offset(cli_rva)
        md_rva, self.md_size = struct.unpack_from('<II', d, self.cli + 8)
        self.md = md = self._offset(md_rva)
        if d[md:md + 4] != b'BSJB': raise ValueError('No metadata signature')
        p = md + 16 + struct.unpack_from('<I', d, md + 12)[0]; streams = struct.unpack_from('<H', d, p + 2)[0]; p += 4
        self.streams = {}
        for _ in range(streams):
            offset, size = struct.unpack_from('<II', d, p); end = d.index(b'\0', p + 8)
            self.streams[d[p + 8:end].decode('ascii')] = (offset, size, p); p = (end + 4) & ~3
        if '#~' not in self.streams: raise ValueError('Unoptimized or missing metadata tables')
        self.us = self.streams.get('#US', (0, 0, None))
        self.sites = {}
        for body in self._method_bodies(): self._walk(body)
        heap = d[md + self.us[0]:md + self.us[0] + self.us[1]]
        self.texts = {}
        for offset in self.sites:
            if not 0 < offset < len(heap): raise ValueError('ldstr outside the string heap')
            size, start = compressed(heap, offset)
            if size == 0: self.texts[offset] = ''; continue
            if start + size > len(heap) or size % 2 == 0: raise ValueError('bad string heap entry')
            self.texts[offset] = heap[start:start + size - 1].decode('utf-16-le', 'replace')

    def _method_bodies(self):
        d = self.data; base = self.md + self.streams['#~'][0]
        heap_sizes = d[base + 6]; valid = struct.unpack_from('<Q', d, base + 8)[0]
        rows, p = [0] * 64, base + 24
        for table in range(64):
            if valid >> table & 1: rows[table] = struct.unpack_from('<I', d, p)[0]; p += 4
        S, G, B = (4 if heap_sizes & 1 else 2), (4 if heap_sizes & 2 else 2), (4 if heap_sizes & 4 else 2)
        index = lambda table: 4 if rows[table] > 0xFFFF else 2
        coded = lambda bits, *tables: 4 if max(rows[t] for t in tables) >= 1 << (16 - bits) else 2
        sizes = [2 + S + 3 * G, coded(2, 0, 26, 35, 1) + 2 * S, 4 + 2 * S + coded(2, 2, 1, 27) + index(4) + index(6),
                 index(4), 2 + S + B, index(6), 8 + S + B + index(8)]
        p += sum(sizes[t] * rows[t] for t in range(6))
        for _ in range(rows[6]):
            rva, impl = struct.unpack_from('<IH', d, p); p += sizes[6]
            if rva and impl & 3 == 0: yield self._offset(rva)

    def _walk(self, body):
        d = self.data; head = d[body]
        if head & 3 == 2: p, size = body + 1, head >> 2
        elif head & 3 == 3: p, size = body + 4 * (struct.unpack_from('<H', d, body)[0] >> 12), struct.unpack_from('<I', d, body + 4)[0]
        else: raise ValueError('bad method header')
        end = p + size
        if end > len(d): raise ValueError('method outside the file')
        while p < end:
            op = d[p]; p += 1
            if op == 0x72:
                token = struct.unpack_from('<I', d, p)[0]
                if token >> 24 != 0x70: raise ValueError('ldstr without a string token')
                self.sites.setdefault(token & 0xFFFFFF, []).append(p); p += 4
            elif op == 0x45: p += 4 + 4 * struct.unpack_from('<I', d, p)[0]
            elif op == 0xFE:
                p += 1 + TWO[d[p]]
            elif op in ONE: p += ONE[op]
            elif op not in NO_OPERAND: raise ValueError('unknown IL opcode 0x%02X' % op)
        if p != end: raise ValueError('method body does not end on an instruction')

    def literals(self):
        """[(heap offset, text)] of every literal some method loads."""
        return sorted(self.texts.items())

    def patch(self, edits):
        """edits: {heap offset: (expected source text, new text)}. Returns the bytes of a patched copy."""
        if self.signed: raise ValueError('Assembly carries a signature; refusing to change it')
        if self.us[2] is None: raise ValueError('Assembly has no string heap')
        d = self.data; last = max(self.sections, key=lambda s: s['raw'])
        if last is not max(self.sections, key=lambda s: s['va']) or last['raw'] + last['raw_size'] != len(d):
            raise ValueError('Unexpected data after the last PE section; refusing to extend it')
        heap = bytearray(d[self.md + self.us[0]:self.md + self.us[0] + self.us[1]])
        out = bytearray(d); moved = {}
        for offset, (source, new) in sorted(edits.items()):
            if self.texts.get(offset) != source: raise ValueError('String literal at %d changed' % offset)
            moved[offset] = len(heap); heap += encode_literal(new)
            for site in self.sites[offset]: struct.pack_into('<I', out, site, 0x70000000 | moved[offset])
        if len(heap) >= 1 << 24: raise ValueError('String heap too large')
        heap += b'\0' * (-len(heap) % 4)
        metadata = bytearray(d[self.md:self.md + self.md_size]); metadata += b'\0' * (-len(metadata) % 4)
        struct.pack_into('<II', metadata, self.us[2] - self.md, len(metadata), len(heap)); metadata += heap
        file_align, section_align = struct.unpack_from('<I', d, self.opt + 36)[0], struct.unpack_from('<I', d, self.opt + 32)[0]
        new_rva = last['va'] + last['raw_size']
        struct.pack_into('<II', out, self.cli + 8, new_rva, len(metadata))
        out += metadata; out += b'\0' * (-len(out) % file_align)
        raw_size = len(out) - last['raw']; flags = struct.unpack_from('<I', d, last['header'] + 36)[0]
        struct.pack_into('<I', out, last['header'] + 8, last['raw_size'] + len(metadata))
        struct.pack_into('<I', out, last['header'] + 16, raw_size)
        struct.pack_into('<I', out, last['header'] + 36, (flags | 0x40000040) & ~0x02000000)  # readable data, not discardable
        struct.pack_into('<I', out, self.opt + 56, (last['va'] + raw_size + section_align - 1) // section_align * section_align)
        result = bytes(out); again = Assembly(result)
        if {again.texts[moved.get(o, o)] for o in self.texts} != {edits[o][1] if o in edits else t for o, t in self.texts.items()} \
                or sum(map(len, again.sites.values())) != sum(map(len, self.sites.values())):
            raise ValueError('Patched assembly does not read back')
        return result
