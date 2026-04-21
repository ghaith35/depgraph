import logging
from pathlib import Path
from typing import Optional

import tree_sitter_rust as tsrust
from tree_sitter import Language, Parser

from .base import LanguageHandler, RawImport

logger = logging.getLogger(__name__)

_RUST_LANGUAGE = Language(tsrust.language())
_RUST_PARSER = Parser(_RUST_LANGUAGE)

_USE_QUERY = _RUST_LANGUAGE.query("""
(use_declaration argument: (_) @path)
""")

_EXTERN_QUERY = _RUST_LANGUAGE.query("""
(extern_crate_declaration name: (identifier) @name)
""")


def _use_node_to_paths(node) -> list[str]:
    """
    Recursively expand a use_declaration argument node to a list of path strings.
    E.g. `tokio::{runtime, task}` → ["tokio::runtime", "tokio::task"]
    """
    t = node.type
    text = node.text.decode("utf-8", errors="replace")

    if t in ("scoped_identifier", "identifier", "self", "super", "crate"):
        return [text]

    if t == "scoped_use_list":
        # e.g. "tokio::{runtime, task}"
        # first child is the prefix, last child is the use_list
        prefix = ""
        results = []
        for child in node.children:
            if child.type in ("scoped_identifier", "identifier", "crate", "super", "self"):
                prefix = child.text.decode("utf-8", errors="replace")
            elif child.type == "use_list":
                for sub_path in _use_node_to_paths(child):
                    results.append(f"{prefix}::{sub_path}" if prefix else sub_path)
        return results

    if t == "use_list":
        results = []
        for child in node.children:
            if child.type in ("{", "}", ","):
                continue
            results.extend(_use_node_to_paths(child))
        return results

    if t == "use_as_clause":
        # `foo::Bar as Alias` → just use the original path
        for child in node.children:
            if child.type not in ("as", "identifier"):
                return _use_node_to_paths(child)

    return [text]


class RustHandler(LanguageHandler):
    language_name = "Rust"

    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        tree = _RUST_PARSER.parse(source_bytes)
        parse_error = tree.root_node.has_error
        imports: list[RawImport] = []

        for node in _USE_QUERY.captures(tree.root_node).get("path", []):
            paths = _use_node_to_paths(node)
            line = node.start_point[0] + 1
            for p in paths:
                is_rel = p.startswith("self::") or p.startswith("super::") or p.startswith("crate::")
                imports.append(RawImport(
                    module=p,
                    is_relative=is_rel,
                    symbol=None,
                    line=line,
                ))

        for node in _EXTERN_QUERY.captures(tree.root_node).get("name", []):
            name = node.text.decode("utf-8", errors="replace")
            imports.append(RawImport(
                module=name,
                is_relative=False,
                symbol=None,
                line=node.start_point[0] + 1,
            ))

        return imports, parse_error

    def resolve_import(self, raw: RawImport, file_path: str, ctx) -> Optional[str]:
        path = raw.module

        # Find which mod_tree this file belongs to
        mod_tree, crate_root = _find_mod_tree(file_path, ctx.rust_mod_trees)

        if path.startswith("crate::"):
            # Absolute path within crate
            lookup = path  # e.g. "crate::foo::bar"
            # Try the path itself
            target = mod_tree.get(lookup)
            if target:
                return target
            # Try dropping the last segment (it might be a type/fn, not a module)
            parts = lookup.split("::")
            for end in range(len(parts), 1, -1):
                candidate = "::".join(parts[:end])
                target = mod_tree.get(candidate)
                if target:
                    return target
            return None

        if path.startswith("super::"):
            return _resolve_relative_rust(path, file_path, mod_tree)

        if path.startswith("self::"):
            return _resolve_relative_rust(path, file_path, mod_tree)

        # Check if it's a workspace crate (extern crate or use workspace_pkg::)
        crate_name = path.split("::")[0]
        for crate_root_file in ctx.rust_mod_trees:
            # Derive crate name from root file path
            root_crate_name = _crate_name_from_root(crate_root_file)
            if root_crate_name == crate_name:
                return crate_root_file

        return None  # external crate


def _find_mod_tree(
    file_path: str,
    mod_trees: dict[str, dict[str, str]],
) -> tuple[dict[str, str], str]:
    """Find the mod tree and crate root file for a given source file."""
    for root_file, tree in mod_trees.items():
        if file_path in tree.values():
            return tree, root_file
    return {}, ""


def _resolve_relative_rust(
    path: str,
    file_path: str,
    mod_tree: dict[str, str],
) -> Optional[str]:
    """Resolve super:: / self:: paths."""
    # Find the module path for the current file
    current_mod = None
    for mod_path, f in mod_tree.items():
        if f == file_path:
            current_mod = mod_path
            break
    if current_mod is None:
        return None

    parts = path.split("::")
    current_parts = current_mod.split("::")

    resolved_parts = list(current_parts)
    for part in parts:
        if part == "self":
            pass  # stay
        elif part == "super":
            if resolved_parts:
                resolved_parts.pop()
        elif part == "crate":
            resolved_parts = ["crate"]
        else:
            resolved_parts.append(part)

    candidate = "::".join(resolved_parts)
    # Try progressively shorter
    for end in range(len(resolved_parts), 0, -1):
        c = "::".join(resolved_parts[:end])
        target = mod_tree.get(c)
        if target:
            return target
    return None


def _crate_name_from_root(root_file: str) -> str:
    """Derive crate name: src/lib.rs → parent dir name, src/main.rs → same."""
    p = Path(root_file)
    # If root is src/lib.rs or src/main.rs, crate name is the project dir (parent of src/)
    if p.parent.name == "src":
        return p.parent.parent.name
    return p.stem
