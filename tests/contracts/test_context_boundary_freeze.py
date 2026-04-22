from __future__ import annotations

import ast
import configparser
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
CONTEXTS_ROOT = SRC_ROOT / "autospider" / "contexts"
INTERFACE_ROOT = SRC_ROOT / "autospider" / "interface"
BOUNDARY_MAP_PATH = REPO_ROOT / "tests" / "contracts" / "fixtures" / "context-boundaries-phase1.json"
IMPORT_LINTER_PATH = REPO_ROOT / ".importlinter"


def _load_boundary_map() -> dict[str, object]:
    return json.loads(BOUNDARY_MAP_PATH.read_text(encoding="utf-8"))


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts)


def _module_path(module_name: str) -> Path:
    file_path = SRC_ROOT / Path(*module_name.split(".")).with_suffix(".py")
    if file_path.exists():
        return file_path
    return SRC_ROOT / Path(*module_name.split(".")) / "__init__.py"


def _resolve_import(source_module: str, module: str | None, level: int) -> str:
    if level == 0:
        return module or ""
    package_parts = source_module.split(".")[:-1]
    base = package_parts[: len(package_parts) - level + 1]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _extract_all_exports(module_name: str) -> list[str]:
    tree = ast.parse(_module_path(module_name).read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                return list(ast.literal_eval(node.value))
    return []


def _edge_kind(source: str, target: str) -> str | None:
    if target.startswith("autospider.composition"):
        return "composition_backedges"
    if not target.startswith("autospider.contexts."):
        return None
    source_context = source.split(".")[2]
    target_parts = target.split(".")
    target_context = target_parts[2]
    if source_context == target_context:
        return None
    if len(target_parts) == 3:
        return "facade_imports"
    return "temporary_internal_imports"


def _collect_edge_inventory() -> dict[str, list[dict[str, str]]]:
    buckets: dict[str, list[dict[str, str]]] = {
        "composition_backedges": [],
        "facade_imports": [],
        "temporary_internal_imports": [],
    }
    for path in CONTEXTS_ROOT.rglob("*.py"):
        source = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = _targets_for_node(source, node)
            for target in targets:
                kind = _edge_kind(source, target)
                if kind is None:
                    continue
                buckets[kind].append({"source": source, "target": target})
    return {name: sorted(values, key=lambda item: (item["source"], item["target"])) for name, values in buckets.items()}


def _targets_for_node(source_module: str, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [_resolve_import(source_module, node.module, node.level)]
    return []


def _collect_wrapper_inventory() -> list[dict[str, str]]:
    wrappers: list[dict[str, str]] = []
    for path in CONTEXTS_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "sys.modules[__name__] = _impl" not in text:
            continue
        wrappers.append(
            {
                "module": _module_name(path),
                "target": _wrapper_target(_module_name(path), ast.parse(text)),
            }
        )
    return sorted(wrappers, key=lambda item: item["module"])


def _collect_interface_context_imports() -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for path in INTERFACE_ROOT.rglob("*.py"):
        source = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for target in _targets_for_node(source, node):
                if target.startswith("autospider.contexts"):
                    edges.append({"source": source, "target": target})
    return sorted(edges, key=lambda item: (item["source"], item["target"]))


def _wrapper_target(source_module: str, tree: ast.Module) -> str:
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.asname != "_impl":
                continue
            base = _resolve_import(source_module, node.module, node.level)
            return f"{base}.{alias.name}"
    return ""


def _load_importlinter_composition_ignores() -> list[dict[str, str]]:
    parser = configparser.ConfigParser()
    parser.read(IMPORT_LINTER_PATH, encoding="utf-8")
    raw_value = parser["importlinter:contract:layers"]["ignore_imports"]
    edges: list[dict[str, str]] = []
    for raw_line in raw_value.splitlines():
        line = raw_line.strip()
        if not line or "->" not in line:
            continue
        source, target = (part.strip() for part in line.split("->", maxsplit=1))
        if not source.startswith("autospider.contexts."):
            continue
        if not target.startswith("autospider.composition."):
            continue
        edges.append({"source": source, "target": target})
    return sorted(edges, key=lambda item: (item["source"], item["target"]))


def test_context_public_exports_match_boundary_map() -> None:
    boundary_map = _load_boundary_map()
    expected = boundary_map["public_exports"]
    actual = {module_name: _extract_all_exports(module_name) for module_name in expected}
    assert actual == expected


def test_context_boundary_inventory_matches_boundary_map() -> None:
    boundary_map = _load_boundary_map()
    edges = _collect_edge_inventory()

    assert _collect_wrapper_inventory() == boundary_map["compatibility_wrappers"]
    assert edges["facade_imports"] == boundary_map["facade_imports"]
    assert edges["temporary_internal_imports"] == boundary_map["temporary_internal_imports"]
    assert edges["composition_backedges"] == boundary_map["composition_backedges"]


def test_importlinter_ignores_match_composition_backedges() -> None:
    boundary_map = _load_boundary_map()
    assert _load_importlinter_composition_ignores() == boundary_map["composition_backedges"]


def test_interface_modules_do_not_directly_import_contexts() -> None:
    assert _collect_interface_context_imports() == []
