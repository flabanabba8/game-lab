"""Guarded, source-addressed RPG Maker MV/MZ JSON translation drafts."""
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
import re
import uuid
from . import locking


TOKENS = re.compile(r'\\\\|\\[A-Za-z]+(?:\[[^\]\r\n]*\])?|\\[.$|!><^{}]|%\d+')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tokens(text):
    return Counter(TOKENS.findall(text))


def visible_width(text):
    """Characters a player sees on one message row: control codes such as \\c[2] or \\i[68] take no space."""
    return max((len(TOKENS.sub('', line)) for line in str(text).split('\n')), default=0)


def compatible_controls(source, translated):
    before, after = TOKENS.findall(source), TOKENS.findall(translated)
    if Counter(before) != Counter(after):
        return False
    # Variables, actor/party names, icons and positional substitutions can move
    # with grammar; formatting and wait controls retain their original order.
    def stateful(items):
        return [token for token in items if not (
            token.startswith('%') or re.fullmatch(r'\\[VNPGI](?:\[[^\]]*\])?', token, re.I))]
    return stateful(before) == stateful(after)


DATABASE_FIELDS = {
    'Actors.json': ('name', 'nickname', 'profile'),
    'Classes.json': ('name',),
    'Skills.json': ('name', 'description', 'message1', 'message2'),
    'Items.json': ('name', 'description'),
    'Weapons.json': ('name', 'description'),
    'Armors.json': ('name', 'description'),
    'Enemies.json': ('name',),
    'States.json': ('name', 'message1', 'message2', 'message3', 'message4'),
}


def command_lists(obj, path=()):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == 'list' and isinstance(value, list) and all(isinstance(x, dict) and 'code' in x for x in value):
                yield path + (key,), value
            else:
                yield from command_lists(value, path + (key,))
    elif isinstance(obj, list):
        for index, value in enumerate(obj): yield from command_lists(value, path + (index,))


def locate(obj, path):
    for part in path: obj = obj[part]
    return obj


class Studio:
    def __init__(self, root):
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _draft(self, draft_id):
        if not isinstance(draft_id, str) or not re.fullmatch('[0-9a-f]{32}', draft_id): raise ValueError('Invalid draft ID')
        folder = self.root / draft_id
        if not folder.is_dir() or folder.is_symlink(): raise ValueError('Unknown draft')
        return folder

    @contextmanager
    def _lock(self, folder):
        with locking.exclusive_lock(folder/'draft.lock', 'This draft is busy; wait for the current operation'):
            yield

    def inspect(self, source_path, message_rows=None, include_system_types=False, message_columns=None):
        if type(include_system_types) is not bool: raise ValueError('include_system_types must be boolean')
        source = Path(source_path).expanduser()
        if not source.is_absolute() or source.is_symlink() or source.suffix.lower() != '.json': raise ValueError('Choose an absolute RPG Maker JSON file path')
        if include_system_types and source.name != 'System.json': raise ValueError('System-type opt-in applies only to System.json')
        original_parts = source.parts
        source = source.resolve(strict=True)
        private = ('.ssh', '.gnupg', '.aws', '.azure', '.codex', '.docker', '.kube', '.pki', '.config')
        own_output = source.is_relative_to(self.root)
        profile_home = self.root.parent.parent if self.root.parent.name.casefold() == 'plugin-data' else None
        protected = any(p.casefold() == '.hermes' for p in (*original_parts, *source.parts)) or (profile_home is not None and source.is_relative_to(profile_home))
        if any(p.casefold() in private for p in (*original_parts, *source.parts)) or protected and not own_output:
            raise ValueError('Credential/configuration directories are not game data')
        if message_columns is not None and (isinstance(message_columns, bool) or not isinstance(message_columns, int) or not 10 <= message_columns <= 200): raise ValueError('Message columns must be an integer between 10 and 200')
        if message_rows is not None and (isinstance(message_rows, bool) or not isinstance(message_rows, int) or not 1 <= message_rows <= 20): raise ValueError('Message rows must be an integer between 1 and 20')
        fd = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 8 * 1024 * 1024:
                raise ValueError('Game JSON must be a regular file up to 8 MiB')
            raw = stream.read(8 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        current = source.lstat()
        identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns)
        if len(raw) > 8 * 1024 * 1024 or identity(before) != identity(after) or identity(after) != identity(current) or not stat.S_ISREG(current.st_mode):
            raise ValueError('Game JSON changed or exceeded the size limit during import')
        obj = json.loads(raw.decode('utf-8-sig'))
        units, groups, skipped = [], [], 0
        if source.name in DATABASE_FIELDS and isinstance(obj, list):
            for index, item in enumerate(obj):
                if not isinstance(item, dict): continue
                for field in DATABASE_FIELDS[source.name]:
                    value = item.get(field)
                    if isinstance(value, str) and value:
                        units.append({'id': len(units), 'path': [index, field], 'source': value, 'group': None, 'translation': None, 'kind': 'database'})
        if isinstance(obj, dict):
            fields = ('gameTitle', 'currencyUnit') if source.name == 'System.json' else ('displayName',) if re.fullmatch(r'Map\d{3,}\.json', source.name) else ()
            for field in fields:
                value = obj.get(field)
                if isinstance(value, str) and value:
                    units.append({'id': len(units), 'path': [field], 'source': value, 'group': None, 'translation': None, 'kind': 'database'})
            if source.name == 'System.json' and include_system_types:
                for field in ('armorTypes', 'elements', 'equipTypes', 'skillTypes', 'weaponTypes'):
                    values = obj.get(field)
                    if isinstance(values, list):
                        for index, value in enumerate(values):
                            if isinstance(value, str) and value:
                                units.append({'id': len(units), 'path': [field, index], 'source': value, 'group': None, 'translation': None, 'kind': 'system_type'})
            if source.name == 'System.json' and isinstance(obj.get('terms'), dict):
                terms = obj['terms']
                for field in ('basic', 'commands', 'params'):
                    values = terms.get(field)
                    if isinstance(values, list):
                        for index, value in enumerate(values):
                            if isinstance(value, str) and value:
                                units.append({'id': len(units), 'path': ['terms', field, index], 'source': value, 'group': None, 'translation': None, 'kind': 'system_term'})
                messages = terms.get('messages')
                if isinstance(messages, dict):
                    for key, value in messages.items():
                        if isinstance(value, str) and value:
                            units.append({'id': len(units), 'path': ['terms', 'messages', key], 'source': value, 'group': None, 'translation': None, 'kind': 'system_term'})
        for base, commands in command_lists(obj):
            current = None
            for index, cmd in enumerate(commands):
                code, params = cmd.get('code'), cmd.get('parameters', [])
                if code == 101:
                    current = {'id': len(groups), 'rows': []}; groups.append(current)
                elif code == 401 and isinstance(params, list) and params and isinstance(params[0], str):
                    if current is None: current = {'id': len(groups), 'rows': []}; groups.append(current)
                    address = list(base + (index, 'parameters', 0)); current['rows'].append(address)
                    if params[0]: units.append({'id': len(units), 'path': address, 'source': params[0], 'group': current['id'], 'translation': None})
                elif code == 102 and isinstance(params, list) and params and isinstance(params[0], list):
                    current = None
                    indent = cmd.get('indent')
                    for choice_index, choice in enumerate(params[0]):
                        if not isinstance(choice, str): continue
                        aliases, mismatch, found_end = [], False, False
                        for branch_index in range(index + 1, len(commands)):
                            branch = commands[branch_index]
                            if branch.get('indent') == indent and branch.get('code') == 404:
                                found_end = True; break
                            if branch.get('indent') == indent and branch.get('code') == 102: break
                            branch_params = branch.get('parameters', [])
                            if branch.get('indent') == indent and branch.get('code') == 402 and isinstance(branch_params, list) and len(branch_params) >= 2 and branch_params[0] == choice_index:
                                if branch_params[1] == choice: aliases.append(list(base + (branch_index, 'parameters', 1)))
                                else: mismatch = True
                        units.append({'id': len(units), 'path': list(base + (index, 'parameters', 0, choice_index)),
                                      'source': choice, 'group': None, 'translation': None, 'aliases': aliases,
                                      'blocked_reason': 'Choice branch is incomplete or its label differs; inspect it before changing' if mismatch or not found_end or not aliases else None})
                else:
                    current = None
                    if code in (355, 356, 357, 655): skipped += 1
        if len(units) > 20000: raise ValueError('File exceeds 20,000 translatable lines')
        identifier = uuid.uuid4().hex; folder = self.root / identifier; folder.mkdir(mode=0o700)
        with os.fdopen(os.open(folder/'source.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(raw)
        longest = max((visible_width(u['source']) for u in units if u['group'] is not None), default=0)
        row_chars = message_columns or (longest if longest >= 10 else None)  # the game author already fitted every original row on screen: translated rows must not be wider than the widest original one
        state = {'id': identifier, 'source_name': source.name, 'source_sha256': sha(raw), 'message_rows': message_rows, 'row_chars': row_chars, 'row_chars_source': 'given' if message_columns else 'widest original row',
                 'units': units, 'groups': groups, 'skipped_script_commands': skipped, 'include_system_types': include_system_types}
        self._save(folder, state)
        return {'draft_id': identifier, 'source_name': source.name, 'source_sha256': state['source_sha256'],
                'units': len(units), 'message_groups': len(groups), 'skipped_script_commands': skipped, 'row_width_limit_chars': row_chars,
                'layout_status': 'configured' if message_rows else 'unknown; supply a measured row limit before layout validation',
                'system_type_notice': 'Opted-in type names may be used by custom scripts; inspect those scripts and test the game.' if include_system_types else 'System type names are excluded unless explicitly requested.'}

    def _save(self, folder, data):
        path = folder/'draft.json'; temporary = folder/('draft-'+uuid.uuid4().hex+'.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, draft_id, offset=0, limit=50):
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100: raise ValueError('Use nonnegative offset and limit 1–100')
        data = json.loads((self._draft(draft_id)/'draft.json').read_text())
        return {'draft_id': draft_id, 'units': data['units'][offset:offset+limit], 'total': len(data['units']),
                'next_offset': offset+limit if offset+limit < len(data['units']) else None}

    def list_drafts(self):
        folders = sorted(p for p in self.root.iterdir() if re.fullmatch('[0-9a-f]{32}', p.name))
        if len(folders) > 1000: raise ValueError('More than 1,000 drafts; narrow the workspace first')
        drafts, unreadable = [], 0
        for folder in folders:
            try:
                folder = self._draft(folder.name)
                state_path = folder/'draft.json'
                if state_path.is_symlink(): raise ValueError('Invalid draft state')
                state = json.loads(state_path.read_text(encoding='utf-8'))
                units = state['units']
                if not isinstance(units, list) or state['id'] != folder.name: raise ValueError('Invalid draft state')
                drafts.append({'draft_id': folder.name, 'source_name': state['source_name'], 'units': len(units),
                               'translated': sum(u.get('translation') is not None for u in units)})
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                unreadable += 1
        return {'drafts': drafts, 'unreadable_records': unreadable}

    def translate(self, draft_id, unit_id, text):
        if isinstance(unit_id, bool) or not isinstance(unit_id, int) or not isinstance(text, str) or len(text) > 10000: raise ValueError('Invalid unit or translation')
        folder = self._draft(draft_id)
        with self._lock(folder):
            data = json.loads((folder/'draft.json').read_text())
            if not 0 <= unit_id < len(data['units']): raise ValueError('Unknown unit')
            unit = data['units'][unit_id]
            if unit.get('blocked_reason'): raise ValueError(unit['blocked_reason'])
            if not compatible_controls(unit['source'], text): raise ValueError('Translation must preserve control tokens, placeholders and formatting-control order')
            unit['translation'] = text; self._save(folder, data)
        return {'unit_id': unit_id, 'saved': True}

    def validate(self, draft_id):
        folder = self._draft(draft_id); data = json.loads((folder/'draft.json').read_text()); raw = (folder/'source.json').read_bytes()
        if sha(raw) != data['source_sha256']: raise ValueError('Stored source bytes changed; refusing output')
        obj = json.loads(raw.decode('utf-8-sig')); replacements = {tuple(u['path']): u['translation'] for u in data['units'] if u['translation'] is not None}
        errors = []
        for unit in data['units']:
            if locate(obj, unit['path']) != unit['source']: errors.append({'unit': unit['id'], 'error': 'source changed'})
            if any(locate(obj, alias) != unit['source'] for alias in unit.get('aliases', [])): errors.append({'unit': unit['id'], 'error': 'choice branch label changed'})
            if unit['translation'] is not None and not compatible_controls(unit['source'], unit['translation']): errors.append({'unit': unit['id'], 'error': 'control tokens or formatting-control order changed'})
            if unit['translation'] is not None and unit.get('blocked_reason'): errors.append({'unit': unit['id'], 'error': unit['blocked_reason']})
        if data.get('row_chars'):
            for unit in data['units']:
                if unit['translation'] is not None and unit['group'] is not None and visible_width(unit['translation']) > data['row_chars']:
                    errors.append({'unit': unit['id'], 'error': 'row wider than the message box estimate', 'visible_chars': visible_width(unit['translation']), 'limit_chars': data['row_chars'], 'hint': 'Split it across rows (one row per line, within the row limit) or shorten it; the limit is the widest original row.'})
        if data['message_rows']:
            for group in data['groups']:
                rows = sum((replacements.get(tuple(path), locate(obj, path)).count('\n') + 1) for path in group['rows'])
                if rows > data['message_rows']: errors.append({'group': group['id'], 'error': 'message row limit exceeded', 'rows': rows})
        return {'structural_ok': not errors, 'errors': errors, 'translated': len(replacements), 'total': len(data['units']),
                'layout_status': ('message-command row limit checked; system-text and pixel layout unverified' if data['groups'] else 'no message-command groups to check; system-text and pixel layout unverified') if data['message_rows'] else 'unknown; no row limit supplied',
                'coverage': 'Message/choice commands, system terms/messages and selected database fields are extracted; scripts, other fields and graphics are not covered.',
                'system_type_notice': 'Opted-in type names may be used by custom scripts; inspect those scripts and test the game.' if data.get('include_system_types') else 'System type names are excluded unless explicitly requested.'}

    def export(self, draft_id):
        folder = self._draft(draft_id)
        with self._lock(folder):
            result = self.validate(draft_id)
            if not result['structural_ok']: raise ValueError('Validation failed; review errors before export')
            data = json.loads((folder/'draft.json').read_text()); raw = (folder/'source.json').read_bytes(); obj = json.loads(raw.decode('utf-8-sig'))
            for unit in data['units']:
                if unit['translation'] is not None:
                    locate(obj, unit['path'][:-1])[unit['path'][-1]] = unit['translation']
                    for alias in unit.get('aliases', []): locate(obj, alias[:-1])[alias[-1]] = unit['translation']
            source_name = data['source_name']
            if not isinstance(source_name, str) or Path(source_name).name != source_name or '/' in source_name or '\\' in source_name or not source_name.lower().endswith('.json'):
                raise ValueError('Invalid source filename in draft')
            out_dir = folder/'exports'/uuid.uuid4().hex
            out_dir.mkdir(parents=True, mode=0o700)
            output = out_dir/source_name
            with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
                json.dump(obj, stream, ensure_ascii=False, indent=2)
            return {'path': str(output), 'source_sha256': data['source_sha256'], 'output_sha256': sha(output.read_bytes()), **result}
