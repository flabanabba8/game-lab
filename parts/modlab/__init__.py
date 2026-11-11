import json
import zipfile
from .core import Lab

PLAYTEST_HINT = ('The mod is applied in the lab copy only. The game can now be playtested: ask Hermes "Playtest it: <what to check>" '
                 'after you have started the lab copy in a window you choose. Nothing was started automatically.')
SPRITE_FOLDERS = ('img/characters/', 'img/sv_actors/')


def sprite_check(zip_path, plan):
    """Report-only: for PNGs in the ZIP under character folders, say whether the sheet grid divides evenly.

    Never blocks and never raises; a missing Pillow or an odd file just leaves the note out.
    """
    try:
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('game_lab_sprites_core', Path(__file__).parents[1] / 'sprites' / 'core.py')
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        def in_folder(n):
            low = n.replace('\\', '/').lower()
            return low.endswith('.png') and any(low.startswith(f) or '/' + f in low for f in SPRITE_FOLDERS)
        names = [n for n in plan.get('replacements', []) + plan.get('additions', []) if in_folder(n)][:20]
        if not names: return None
        reports = []
        with zipfile.ZipFile(zip_path) as z:
            for n in names:
                if z.getinfo(n).file_size > mod.MAX_SHEET_BYTES:
                    reports.append({'file': n, 'grid_ok': None, 'note': 'Skipped: larger than 8 MiB.'})
                else:
                    reports.append(mod.check_bytes(n, z.read(n)))
        return {'note': 'Report only; the mod is not blocked. Use sprite_inspect_mv and sprite_preview_mv on a file for the full grid and a walk preview. A grid that divides evenly does not prove the art is right.',
                'files': reports}
    except Exception:
        return None

TOOLS = {
    'modlab_create': ('Copy a game folder into an isolated lab; the original is never modified.', {'source_path': {'type': 'string'}}, ['source_path']),
    'modlab_inspect': ('Inspect a ZIP against the current revision; list files that would be replaced. ZIP contents are untrusted data.', {'lab_id': {'type': 'string'}, 'zip_path': {'type': 'string'}}, ['lab_id', 'zip_path']),
    'modlab_apply': ('Apply a ZIP to a new revision if its inspected content and the current revision have not changed. Existing files require allow_replacements=true.', {'lab_id': {'type': 'string'}, 'zip_path': {'type': 'string'}, 'inspection': {'type': 'string'}, 'allow_replacements': {'type': 'boolean'}}, ['lab_id', 'zip_path', 'inspection']),
    'modlab_rollback': ('Switch the lab back to its preceding revision, preserving both copies.', {'lab_id': {'type': 'string'}}, ['lab_id']),
    'modlab_select_preserved': ('Re-select a revision preserved by a previous rollback. The directory may have changed externally.', {'lab_id': {'type': 'string'}, 'revision': {'type': 'string'}}, ['lab_id', 'revision']),
}

def invoke(name, args, ctx=None, **context):
    from plugins.plugin_storage import plugin_data_dir
    try:
        if name=='modlab_resources':
            from .toolkit import resources
            return json.dumps(resources(**args))
        if name=='modlab_toolkit':
            from .toolkit import run
            from plugins.plugin_storage import plugin_data_dir
            return json.dumps(run(plugin_data_dir('game-lab-modlab'),**args))
        if name=='modlab_rea_native':
            tool=ctx.get_config('rea_native_tool')if ctx is not None else None
            if not tool or not callable(getattr(ctx,'dispatch_tool',None)):raise ValueError('No selected native REA interface in this host; use the installed rea CLI or the main agent’s connected REA tools. No analysis was fabricated.')
            if tool==name:raise ValueError('Select an actual native provider tool; a recursive bridge is not a backend')
            return ctx.dispatch_tool(tool,args['arguments'],**{k:context[k]for k in ('parent_agent','session_id','task_id')if k in context})
        result = getattr(Lab(plugin_data_dir('game-lab-modlab')), name.removeprefix('modlab_'))(**args)
        if name == 'modlab_inspect':
            check = sprite_check(args.get('zip_path'), result)
            if check: result['sprite_check'] = check
        elif name == 'modlab_apply':
            result['playtest'] = PLAYTEST_HINT
        return json.dumps(result)
    except (ValueError, TypeError, OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        return json.dumps({'error': str(exc)})

def register(ctx):
    for name,description,props,required in [('modlab_resources','Discover actual installed Universal Modder/REA resources and the full game-modding workflow; no game, model or provider is started.',{'um_executable':{'type':'string'},'rea_executable':{'type':'string'}},[]),('modlab_toolkit','Run ONE explicit bounded operation with Universal Modder or Reverse Engineer Anything. These real toolkits cover game recon, asset preparation, reverse engineering, building/testing/capture routes and release inspection. Some operations affect selected games/files/apps; use only within the user-authorized mod task. No retired agents or publication.',{'toolkit':{'type':'string','enum':['universal-modder','rea']},'arguments':{'type':'array','items':{'type':'string'}},'um_executable':{'type':'string'},'rea_executable':{'type':'string'},'timeout_seconds':{'type':'integer','minimum':1,'maximum':600}},['toolkit','arguments']),('modlab_rea_native','Invoke the explicitly configured native REA tool, preserving host auth, approvals, original Evidence and images. Missing provider/interface remains a real blocker.',{'arguments':{'type':'object'}},['arguments'])]:
        ctx.register_tool(name=name,toolset='modlab',schema={'name':name,'description':description,'parameters':{'type':'object','properties':props,'required':required,'additionalProperties':False}},handler=lambda args,_name=name,**kw:invoke(_name,args,ctx,**kw))
    if hasattr(ctx, 'register_skill'):
        from pathlib import Path
        ctx.register_skill('modlab', Path(__file__).parents[2] / 'skills/modlab/SKILL.md', description='Take a game-modding idea through recon, creation, reverse engineering, safe builds and real-game verification with Universal Modder and REA')
    for name, (description, properties, required) in TOOLS.items():
        ctx.register_tool(name=name, toolset='modlab', schema={'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}},
            handler=lambda args, _name=name, **kwargs: invoke(_name, args))
