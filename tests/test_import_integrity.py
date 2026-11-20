"""Every intra-package import resolves, without Home Assistant installed.

0.18.0 regression: ``settings_entity.py`` still imported the removed
``settings.RETIRED``. The offline suite never imported the HA platform modules
(number.py, switch.py, ...), so only the isolated Home Assistant job failed.
This test resolves every ``from .module import name`` statically, for every
module, including HA-only platforms.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGES = [ROOT / "custom_components/thermann_shadow", ROOT / "thermowatt-heater"]


def defined_names(path):
    """Top-level names a module binds (assignments, defs, classes, imports)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for item in ast.walk(target):
                    if isinstance(item, ast.Name):
                        names.add(item.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.If, ast.Try)):
            for child in ast.walk(node):
                if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                    names.add(child.name)
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
    return names


def imports(package):
    for path in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                if node.level == 1 and node.module:
                    target = package / f"{node.module}.py"
                elif node.level == 0 and node.module and (package / f"{node.module}.py").exists():
                    target = package / f"{node.module}.py"  # add-on flat imports
                else:
                    continue
                for alias in node.names:
                    yield path.name, target, alias.name


CASES = [case for package in PACKAGES for case in imports(package)]


@pytest.mark.parametrize("source,target,name", CASES, ids=lambda v: getattr(v, "name", v))
def test_every_intra_package_import_resolves(source, target, name):
    assert target.exists(), f"{source} imports missing module {target.name}"
    assert name in defined_names(target), f"{source}: {target.stem}.{name} is not defined"


def test_every_ha_platform_module_is_covered():
    platforms = {
        "sensor.py",
        "number.py",
        "time.py",
        "switch.py",
        "select.py",
        "text.py",
        "button.py",
        "date.py",
        "config_flow.py",
        "diagnostics.py",
        "settings_entity.py",
    }
    covered = {source for source, _, _ in CASES}
    assert platforms <= covered, platforms - covered
