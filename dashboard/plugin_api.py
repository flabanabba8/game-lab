"""Authenticated Hermes-owned route mount; no independent web server."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from fastapi import APIRouter, HTTPException

# The dashboard loads this file as a standalone module. Give our own source
# package a path-specific namespace; never modify Hermes modules or sys.path.
root = Path(__file__).resolve().parents[1] / 'parts' / 'localization'
name = 'game_lab_localization_ui_' + hashlib.sha256(str(root).encode()).hexdigest()[:16]
spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules[name] = package
spec.loader.exec_module(package)
router = APIRouter()


@router.post('/action')
def action(body: dict):
    operation, arguments = body.get('operation'), body.get('arguments', {})
    if operation not in package.TOOLS or not isinstance(arguments, dict):
        raise HTTPException(400, 'Unknown Game Lab localization operation')
    result = json.loads(package.invoke(operation, arguments))
    if 'error' in result:
        raise HTTPException(400, result['error'])
    return result
