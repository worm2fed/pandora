#!/usr/bin/env python3
"""The layout of ``scripts/_journal/`` holds its layer order (ADR 0027, #61).

Each module imports only modules earlier in ``_LAYERS``, so the package has no import
cycle. Modules import each other relatively, never as ``_journal``. No module runs as a
script, so ``journal.py`` stays the only way to run the journal. Every module file is
in ``_LAYERS``, so ``journal.py`` copies its names. The checks read the source with
``ast``; they import nothing.
"""

from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "scripts" / "_journal"


def _layers(package):
    """The module names of ``_LAYERS`` in ``__init__.py``, in order."""
    tree = ast.parse((package / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple) and any(
                isinstance(t, ast.Name) and t.id == "_LAYERS" for t in node.targets):
            return [e.id for e in node.value.elts if isinstance(e, ast.Name)]
    raise AssertionError("__init__.py defines no _LAYERS")


def _imported(package):
    """The module names that ``from . import`` in ``__init__.py`` loads, in order."""
    tree = ast.parse((package / "__init__.py").read_text(encoding="utf-8"))
    return [alias.name for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None
            for alias in node.names]


def layout_problems(package):
    """Every break of the layout rules in ``package``, one line each."""
    problems = []
    layers = _layers(package)
    if (package / "__main__.py").exists():
        problems.append("__main__.py exists")
    files = sorted(p.stem for p in package.glob("*.py") if p.name != "__init__.py")
    for name in sorted(set(files) - set(layers)):
        problems.append(f"{name}.py is not in _LAYERS")
    for name in sorted(set(layers) - set(files)):
        problems.append(f"_LAYERS names {name}, which has no file")
    for name in files:
        tree = ast.parse((package / f"{name}.py").read_text(encoding="utf-8"))
        earlier = set(layers[:layers.index(name)]) if name in layers else set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "_journal":
                        problems.append(f"{name}: absolute import of {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    if (node.module or "").split(".")[0] == "_journal":
                        problems.append(f"{name}: absolute import of {node.module}")
                    continue
                if node.level > 1:
                    problems.append(f"{name}: import from outside the package")
                    continue
                targets = [node.module] if node.module else [a.name for a in node.names]
                for target in targets:
                    if target.split(".")[0] not in earlier:
                        problems.append(f"{name}: imports {target}, which is not earlier")
        for node in tree.body:
            if isinstance(node, ast.If) and "__name__" in ast.dump(node.test):
                problems.append(f"{name}: has a __main__ guard")
    return problems


class TestJournalLayout(unittest.TestCase):
    def test_the_package_holds_the_layer_order(self):
        self.assertEqual(layout_problems(PACKAGE), [])

    def test_every_module_and_only_those_are_layers(self):
        layers = _layers(PACKAGE)
        self.assertEqual(len(layers), len(set(layers)))
        self.assertEqual(_imported(PACKAGE), layers, "__init__.py loads the layers in order")
        self.assertEqual(sorted(layers), sorted(
            p.stem for p in PACKAGE.glob("*.py") if p.name != "__init__.py"))

    def test_a_break_of_each_rule_is_reported(self):
        """The checks catch what they guard against, on a scratch copy of the package."""
        layers = _layers(PACKAGE)
        first, last = layers[0], layers[-1]
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "_journal"
            shutil.copytree(str(PACKAGE), str(copy))
            with open(copy / f"{first}.py", "a", encoding="utf-8") as f:
                f.write(f"\nfrom .{last} import main\nimport _journal.{last}\n"
                        "\nif __name__ == '__main__':\n    main()\n")
            (copy / "__main__.py").write_text("", encoding="utf-8")
            (copy / "stray.py").write_text("", encoding="utf-8")
            problems = layout_problems(copy)
        self.assertIn(f"{first}: imports {last}, which is not earlier", problems)
        self.assertIn(f"{first}: absolute import of _journal.{last}", problems)
        self.assertIn(f"{first}: has a __main__ guard", problems)
        self.assertIn("__main__.py exists", problems)
        self.assertIn("stray.py is not in _LAYERS", problems)


if __name__ == "__main__":
    unittest.main()
