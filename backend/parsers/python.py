import logging
from pathlib import Path
from typing import Optional

import tree_sitter_python as tsp
from tree_sitter import Language, Parser

from .base import LanguageHandler, RawImport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# One Language + Parser instance, reused across all requests
# ---------------------------------------------------------------------------

_PY_LANGUAGE = Language(tsp.language())
_PARSER = Parser(_PY_LANGUAGE)

# ---------------------------------------------------------------------------
# Pre-compiled query — compiled once at import time
# ---------------------------------------------------------------------------

_IMPORT_QUERY = _PY_LANGUAGE.query("""
(import_statement
  name: (dotted_name) @import.abs)

(import_statement
  name: (aliased_import
    name: (dotted_name) @import.abs))

(import_from_statement
  module_name: (dotted_name) @import.from)

(import_from_statement
  module_name: (relative_import) @import.rel)
""")

# Capture the first imported name in a from-import for edge symbol annotation
_SYMBOL_QUERY = _PY_LANGUAGE.query("""
(import_from_statement
  name: (dotted_name) @sym)
""")


class PythonHandler(LanguageHandler):

    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        tree = _PARSER.parse(source_bytes)
        parse_error = tree.root_node.has_error

        # Build a line → first-symbol map so edges can carry symbol info
        sym_caps: dict[int, str] = {}
        for node in _SYMBOL_QUERY.captures(tree.root_node).get("sym", []):
            line = node.start_point[0]
            if line not in sym_caps:
                sym_caps[line] = node.text.decode("utf-8", errors="replace")

        captures = _IMPORT_QUERY.captures(tree.root_node)
        imports: list[RawImport] = []

        for node in captures.get("import.abs", []):
            module = node.text.decode("utf-8", errors="replace")
            line = node.start_point[0]
            imports.append(RawImport(
                module=module,
                is_relative=False,
                symbol=sym_caps.get(line),
                line=line + 1,
            ))

        for node in captures.get("import.from", []):
            module = node.text.decode("utf-8", errors="replace")
            line = node.start_point[0]
            imports.append(RawImport(
                module=module,
                is_relative=False,
                symbol=sym_caps.get(line),
                line=line + 1,
            ))

        for node in captures.get("import.rel", []):
            # text is like ".", "..", "..utils", "..utils.helpers"
            raw_text = node.text.decode("utf-8", errors="replace")
            line = node.start_point[0]
            imports.append(RawImport(
                module=raw_text,
                is_relative=True,
                symbol=sym_caps.get(line),
                line=line + 1,
            ))

        return imports, parse_error

    def resolve_import(
        self,
        raw: RawImport,
        file_path: str,
        ctx,
    ) -> Optional[str]:
        repo_root = ctx.repo_root
        if raw.is_relative:
            return _resolve_relative(raw.module, file_path, repo_root)
        return _resolve_absolute(raw.module, repo_root)


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def _candidates(base: Path) -> list[Path]:
    """Ordered list of paths to try for a module rooted at `base`."""
    return [
        base.with_suffix(".py"),
        base / "__init__.py",
    ]


def _resolve_absolute(module: str, repo_root: Path) -> Optional[str]:
    parts = module.split(".")
    # Try progressively shorter prefixes:
    # "a.b.c" → try a/b/c.py, a/b/c/__init__.py, then a/b.py, etc.
    for length in range(len(parts), 0, -1):
        base = repo_root.joinpath(*parts[:length])
        for candidate in _candidates(base):
            if candidate.is_file():
                return str(candidate.relative_to(repo_root))
    return None


def _resolve_relative(module: str, file_path: str, repo_root: Path) -> Optional[str]:
    # Count leading dots
    dot_count = 0
    while dot_count < len(module) and module[dot_count] == ".":
        dot_count += 1
    remainder = module[dot_count:]  # everything after the dots

    # Start from the directory containing the importing file
    current_dir = (repo_root / file_path).parent

    # Walk up (dot_count - 1) levels
    # 1 dot  = current package directory (no upward movement)
    # 2 dots = parent package (move up once)
    for _ in range(dot_count - 1):
        current_dir = current_dir.parent
        if current_dir == current_dir.parent:  # hit filesystem root — bail
            return None

    if not remainder:
        # "from . import x" or "from .. import x" — target is the package itself
        candidate = current_dir / "__init__.py"
        if candidate.is_file():
            return str(candidate.relative_to(repo_root))
        return None

    parts = remainder.split(".")
    base = current_dir.joinpath(*parts)
    for candidate in _candidates(base):
        if candidate.is_file():
            return str(candidate.relative_to(repo_root))

    return None
