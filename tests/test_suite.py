import importlib.util
import re
import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_lab_fixture', root / '__init__.py', submodule_search_locations=[str(root)])
suite = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = suite
spec.loader.exec_module(suite)


def manifest_list(key):
    """Read a top-level list from plugin.yaml without a YAML dependency."""
    out, on = [], False
    for line in (root / 'plugin.yaml').read_text().splitlines():
        if line.startswith(key + ':'):
            on = True
        elif on and line.startswith('  - '):
            out.append(line[4:].strip())
        elif on:
            break
    return out


class Ctx:
    def __init__(self):
        self.tools, self.hooks, self.skills = [], [], []

    def register_tool(self, name, toolset, schema, handler, **kw):
        assert schema['name'] == name and callable(handler)
        self.tools.append(name)

    def register_hook(self, hook, fn):
        self.hooks.append(hook)

    def register_skill(self, name, path, description=''):
        assert Path(path).is_file(), path
        self.skills.append(name)

    def get_config(self, key):
        return None


class SuiteTest(unittest.TestCase):
    def test_register_matches_manifest(self):
        ctx = Ctx()
        suite.register(ctx)
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list('provides_tools')))
        self.assertEqual(len(ctx.tools), len(set(ctx.tools)))
        self.assertEqual(len(ctx.tools), 21)
        self.assertEqual(ctx.hooks, manifest_list('provides_hooks'))
        self.assertEqual(sorted(ctx.skills), ['game-localization-studio', 'modlab', 'playtest-pilot', 'sprite-contract'])

    def test_tool_reference_lists_exactly_the_tools(self):
        text = (root / 'llmwiki' / 'tools.md').read_text()
        headings = [line[3:].strip() for line in text.splitlines() if line.startswith('## ')]
        self.assertEqual(sorted(headings), sorted(manifest_list('provides_tools')))

    def test_parts_use_separate_data_folders(self):
        names = set()
        for part in ('modlab', 'localization', 'playtest', 'sprites'):
            names.update(re.findall(r"plugin_data_dir\('([^']+)'\)", (root / 'parts' / part / '__init__.py').read_text()))
        self.assertEqual(names, {'game-lab-modlab', 'game-lab-localization', 'game-lab-playtest', 'game-lab-sprites'})


if __name__ == '__main__':
    unittest.main()
