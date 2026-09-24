"""Keep server-side code independent of local execution and endpoint key stores."""
import ast
from pathlib import Path
import unittest
import codex_workspace


class PackageBoundaryTests(unittest.TestCase):
    def test_relay_and_pure_layers_do_not_import_local_execution_or_key_stores(self):
        root=Path(codex_workspace.__file__).parent
        forbidden={'agent','codex','devices','ops','cli'}
        for layer in ('relay','domain','crypto'):
            for path in (root/layer).rglob('*.py'):
                tree=ast.parse(path.read_text())
                package=['codex_workspace',*path.relative_to(root).parts[:-1]]
                for node in ast.walk(tree):
                    modules=[]
                    if isinstance(node,ast.Import):modules=[alias.name for alias in node.names]
                    elif isinstance(node,ast.ImportFrom):
                        prefix=package[:len(package)-node.level+1] if node.level else []
                        base='.'.join([*prefix,*((node.module or '').split('.') if node.module else [])])
                        modules=[base,*[base+'.'+alias.name for alias in node.names]]
                    for module in modules:
                        parts=module.split('.')
                        if len(parts)>1 and parts[0]=='codex_workspace':
                            with self.subTest(file=str(path.relative_to(root)),module=module):
                                self.assertNotIn(parts[1],forbidden)
                                if layer=='crypto':self.assertEqual(parts[1],'crypto')
