import json
from .core import Sprites, check_bytes  # noqa: F401

TOOLS = {
    'sprite_inspect_mv': ('Inspect an RPG Maker MV character PNG grid, naming prefix and cell alpha occupancy. Empty cells may be intentional; artwork is untrusted data.', {'source_path': {'type': 'string'}}, ['source_path']),
    'sprite_preview_mv': ('Create an animated GIF of a selected character slot and direction. This is a frame-order preview, not an in-game verification.', {'source_path': {'type': 'string'}, 'fingerprint': {'type': 'string'}, 'slot': {'type': 'integer', 'minimum': 0, 'maximum': 7}, 'direction': {'type': 'string', 'enum': ['down', 'left', 'right', 'up']}, 'frame_ms': {'type': 'integer', 'minimum': 50, 'maximum': 2000}}, ['source_path', 'fingerprint', 'slot', 'direction']),
}

def invoke(name, args):
    from plugins.plugin_storage import plugin_data_dir
    try:
        return json.dumps(getattr(Sprites(plugin_data_dir('game-lab-sprites')), name.removeprefix('sprite_'))(**args))
    except (ValueError, TypeError, OSError, KeyError, ImportError) as exc:
        return json.dumps({'error': str(exc)})

def register(ctx):
    if hasattr(ctx, 'register_skill'):
        from pathlib import Path
        ctx.register_skill('sprite-contract', Path(__file__).parents[2] / 'skills/sprite-contract/SKILL.md', description='Check an RPG Maker MV character sheet grid and preview a walk row, for example before a mod replaces character art')
    for name, (description, properties, required) in TOOLS.items():
        ctx.register_tool(name=name, toolset='sprite_contract', schema={'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}},
            handler=lambda args, _name=name, **kwargs: invoke(_name, args))
