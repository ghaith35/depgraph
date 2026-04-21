import logging
from pathlib import Path
from typing import Optional

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser

from .base import LanguageHandler, RawImport

logger = logging.getLogger(__name__)

_JS_LANGUAGE = Language(tsjs.language())
_JS_PARSER = Parser(_JS_LANGUAGE)

_JS_IMPORT_QUERY = _JS_LANGUAGE.query("""
(import_statement source: (string) @src)
(export_statement source: (string) @src)
(call_expression
  function: (identifier) @_fn (#eq? @_fn "require")
  arguments: (arguments (string) @src))
(call_expression
  function: (import)
  arguments: (arguments (string) @src))
""")

# Dynamic import with template string — flag it
_JS_DYNAMIC_QUERY = _JS_LANGUAGE.query("""
(call_expression
  function: (import)
  arguments: (arguments (template_string) @dyn))
""")

_JS_EXTENSIONS = [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]


def _strip_quotes(text: bytes) -> str:
    s = text.decode("utf-8", errors="replace")
    if len(s) >= 2 and s[0] in ('"', "'", "`") and s[-1] == s[0]:
        return s[1:-1]
    return s


class JavaScriptHandler(LanguageHandler):
    language_name = "JavaScript"

    def _parse(self, source_bytes: bytes):
        return _JS_PARSER.parse(source_bytes)

    def _parser_instance(self):
        return _JS_PARSER

    def _query(self):
        return _JS_IMPORT_QUERY

    def _dyn_query(self):
        return _JS_DYNAMIC_QUERY

    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        tree = self._parse(source_bytes)
        parse_error = tree.root_node.has_error
        imports: list[RawImport] = []

        for node in self._query().captures(tree.root_node).get("src", []):
            raw = _strip_quotes(node.text)
            if not raw:
                continue
            is_rel = raw.startswith("./") or raw.startswith("../")
            imports.append(RawImport(
                module=raw,
                is_relative=is_rel,
                symbol=None,
                line=node.start_point[0] + 1,
            ))

        for node in self._dyn_query().captures(tree.root_node).get("dyn", []):
            raw = node.text.decode("utf-8", errors="replace")
            # Replace ${...} with *
            pattern = re.sub(r"\$\{[^}]+\}", "*", raw.strip("`"))
            imports.append(RawImport(
                module=pattern,
                is_relative=pattern.startswith("./") or pattern.startswith("../"),
                symbol=None,
                line=node.start_point[0] + 1,
                is_dynamic=True,
                target_pattern=pattern,
            ))

        return imports, parse_error

    def resolve_import(self, raw: RawImport, file_path: str, ctx) -> Optional[str]:
        if raw.is_dynamic:
            return None   # don't resolve dynamic imports
        if not raw.is_relative:
            # Check workspace aliases
            target_dir = ctx.ts_workspace_aliases.get(raw.module)
            if target_dir:
                return _probe_dir_index(target_dir, ctx.all_files)
            # Check scoped package prefix (e.g. "@repo/shared")
            for pkg_name, pkg_dir in ctx.ts_workspace_aliases.items():
                if raw.module == pkg_name or raw.module.startswith(pkg_name + "/"):
                    suffix = raw.module[len(pkg_name):]
                    base = pkg_dir + suffix
                    hit = _probe_extensions(base, ctx.all_files)
                    if hit:
                        return hit
                    return _probe_dir_index(base, ctx.all_files)
            return None  # external

        # Relative
        base_dir = str(Path(file_path).parent)
        raw_path = raw.module
        if base_dir and base_dir != ".":
            joined = str(Path(base_dir) / raw_path)
        else:
            joined = raw_path
        # Normalise away any .. or . segments without making absolute
        joined = _normalise_path(joined)

        hit = _probe_extensions(joined, ctx.all_files)
        if hit:
            return hit
        return _probe_dir_index(joined, ctx.all_files)


def _probe_extensions(base: str, all_files: set[str]) -> Optional[str]:
    """Try base + each extension. Returns first match."""
    base = base.lstrip("./") if base.startswith("./") else base
    # If base already has an extension that exists
    if base in all_files:
        return base
    for ext in _JS_EXTENSIONS:
        candidate = base + ext
        if candidate in all_files:
            return candidate
    return None


def _probe_dir_index(base: str, all_files: set[str]) -> Optional[str]:
    """Try base/index.<ext>."""
    base = base.rstrip("/")
    for ext in _JS_EXTENSIONS:
        candidate = f"{base}/index{ext}"
        if candidate in all_files:
            return candidate
    return None


import re  # noqa: E402 — needed by extract_imports; imported here to keep top clean


def _normalise_path(path: str) -> str:
    """Resolve .. and . in a path string without making it absolute."""
    parts = []
    for p in path.replace("\\", "/").split("/"):
        if p == "..":
            if parts:
                parts.pop()
        elif p and p != ".":
            parts.append(p)
    return "/".join(parts)
