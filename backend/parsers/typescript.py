"""
TypeScript handler — wraps the JS handler and adds tsconfig path resolution.
Two grammars: .ts and .tsx.
"""
import logging
from pathlib import Path
from typing import Optional

import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from .base import RawImport
from .javascript import JavaScriptHandler, _probe_extensions, _probe_dir_index, _JS_EXTENSIONS

logger = logging.getLogger(__name__)

_TS_LANGUAGE = Language(tsts.language_typescript())
_TSX_LANGUAGE = Language(tsts.language_tsx())
_TS_PARSER = Parser(_TS_LANGUAGE)
_TSX_PARSER = Parser(_TSX_LANGUAGE)

_TS_IMPORT_QUERY = _TS_LANGUAGE.query("""
(import_statement source: (string) @src)
(export_statement source: (string) @src)
(call_expression
  function: (identifier) @_fn (#eq? @_fn "require")
  arguments: (arguments (string) @src))
(call_expression
  function: (import)
  arguments: (arguments (string) @src))
""")

_TSX_IMPORT_QUERY = _TSX_LANGUAGE.query("""
(import_statement source: (string) @src)
(export_statement source: (string) @src)
(call_expression
  function: (identifier) @_fn (#eq? @_fn "require")
  arguments: (arguments (string) @src))
(call_expression
  function: (import)
  arguments: (arguments (string) @src))
""")

_TS_DYN_QUERY = _TS_LANGUAGE.query("""
(call_expression
  function: (import)
  arguments: (arguments (template_string) @dyn))
""")

_TSX_DYN_QUERY = _TSX_LANGUAGE.query("""
(call_expression
  function: (import)
  arguments: (arguments (template_string) @dyn))
""")

_TS_EXTENSIONS = [".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs"]


class TypeScriptHandler(JavaScriptHandler):
    language_name = "TypeScript"

    def __init__(self, is_tsx: bool = False):
        self._is_tsx = is_tsx

    def _parse(self, source_bytes: bytes):
        return (_TSX_PARSER if self._is_tsx else _TS_PARSER).parse(source_bytes)

    def _query(self):
        return _TSX_IMPORT_QUERY if self._is_tsx else _TS_IMPORT_QUERY

    def _dyn_query(self):
        return _TSX_DYN_QUERY if self._is_tsx else _TS_DYN_QUERY

    def resolve_import(self, raw: RawImport, file_path: str, ctx) -> Optional[str]:
        if raw.is_dynamic:
            return None

        # Find governing tsconfig for this file
        ts_cfg = _find_tsconfig(file_path, ctx.ts_configs)

        # 1) Paths aliases (tsconfig)
        if ts_cfg and ts_cfg.paths:
            hit = _resolve_paths_alias(raw.module, ts_cfg, file_path, ctx)
            if hit:
                return hit

        # 2) Workspace aliases
        for pkg_name, pkg_dir in ctx.ts_workspace_aliases.items():
            if raw.module == pkg_name or raw.module.startswith(pkg_name + "/"):
                suffix = raw.module[len(pkg_name):].lstrip("/")
                base = f"{pkg_dir}/src/{suffix}" if suffix else f"{pkg_dir}/src"
                hit = _probe_extensions(base, ctx.all_files) or _probe_dir_index(base, ctx.all_files)
                if hit:
                    return hit
                base2 = f"{pkg_dir}/{suffix}" if suffix else pkg_dir
                hit = _probe_extensions(base2, ctx.all_files) or _probe_dir_index(base2, ctx.all_files)
                if hit:
                    return hit
                return None

        # 3) Relative
        if raw.is_relative:
            base_dir = str(Path(file_path).parent)
            joined = str(Path(base_dir) / raw.module).replace("\\", "/")
            hit = _probe_extensions(joined, ctx.all_files)
            if hit:
                return hit
            return _probe_dir_index(joined, ctx.all_files)

        # 4) baseUrl-relative
        if ts_cfg and ts_cfg.base_url:
            cfg_dir = ts_cfg.dir
            base = f"{cfg_dir}/{ts_cfg.base_url}/{raw.module}".lstrip("/").replace("\\", "/")
            base = _normalise(base)
            hit = _probe_extensions(base, ctx.all_files) or _probe_dir_index(base, ctx.all_files)
            if hit:
                return hit

        return None  # external


def _find_tsconfig(file_path: str, ts_configs):
    """Return the deepest tsconfig whose directory is an ancestor of file_path."""
    file_dir = str(Path(file_path).parent)
    for cfg in ts_configs:  # already sorted deepest-first
        if file_dir == cfg.dir or file_dir.startswith(cfg.dir + "/") or cfg.dir == "":
            return cfg
    return None


def _resolve_paths_alias(module: str, ts_cfg, file_path: str, ctx) -> Optional[str]:
    """Try tsconfig `paths` aliases. Longest matching prefix wins."""
    best_prefix_len = -1
    best_patterns = None

    for alias, patterns in ts_cfg.paths.items():
        if alias.endswith("/*"):
            prefix = alias[:-2]
            if module.startswith(prefix + "/") or module == prefix:
                if len(prefix) > best_prefix_len:
                    best_prefix_len = len(prefix)
                    best_patterns = (patterns, prefix, True)
        else:
            if module == alias:
                if len(alias) > best_prefix_len:
                    best_prefix_len = len(alias)
                    best_patterns = (patterns, alias, False)

    if best_patterns is None:
        return None

    patterns, prefix, is_glob = best_patterns
    cfg_dir = ts_cfg.dir

    for pattern in patterns:
        if is_glob:
            suffix = module[len(prefix):].lstrip("/")
            resolved_pattern = pattern.rstrip("/*") if pattern.endswith("/*") else pattern
            base = f"{cfg_dir}/{resolved_pattern}/{suffix}".lstrip("/")
        else:
            base = f"{cfg_dir}/{pattern}".lstrip("/")
        base = _normalise(base)
        hit = _probe_extensions(base, ctx.all_files) or _probe_dir_index(base, ctx.all_files)
        if hit:
            return hit

    return None


def _normalise(path: str) -> str:
    """Resolve .. and . in a relative path string."""
    parts = []
    for p in path.replace("\\", "/").split("/"):
        if p == "..":
            if parts:
                parts.pop()
        elif p != ".":
            parts.append(p)
    return "/".join(parts)
