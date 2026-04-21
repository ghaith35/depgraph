import logging
from pathlib import Path
from typing import Optional

import tree_sitter_go as tsgo
from tree_sitter import Language, Parser

from .base import LanguageHandler, RawImport

logger = logging.getLogger(__name__)

_GO_LANGUAGE = Language(tsgo.language())
_GO_PARSER = Parser(_GO_LANGUAGE)

_IMPORT_QUERY = _GO_LANGUAGE.query("""
(import_spec path: (interpreted_string_literal) @path)
""")

# Standard lib packages (single-segment names or well-known prefixes)
_STDLIB_PREFIXES = {
    "archive", "bufio", "builtin", "bytes", "cmd", "compress", "container",
    "context", "crypto", "database", "debug", "encoding", "errors", "expvar",
    "flag", "fmt", "go", "hash", "html", "image", "index", "io", "log",
    "math", "mime", "net", "os", "path", "plugin", "reflect", "regexp",
    "runtime", "sort", "strconv", "strings", "sync", "syscall", "testing",
    "text", "time", "unicode", "unsafe", "vendor",
}


def _is_stdlib(path: str) -> bool:
    first = path.split("/")[0]
    return first in _STDLIB_PREFIXES or "." not in first


class GoHandler(LanguageHandler):
    language_name = "Go"

    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        tree = _GO_PARSER.parse(source_bytes)
        parse_error = tree.root_node.has_error
        imports: list[RawImport] = []

        for node in _IMPORT_QUERY.captures(tree.root_node).get("path", []):
            # Strip surrounding quotes: "github.com/foo" → github.com/foo
            raw = node.text.decode("utf-8", errors="replace").strip('"')
            imports.append(RawImport(
                module=raw,
                is_relative=False,
                symbol=None,
                line=node.start_point[0] + 1,
            ))

        return imports, parse_error

    def resolve_import(self, raw: RawImport, file_path: str, ctx) -> Optional[str]:
        path = raw.module

        if not ctx.go_module or _is_stdlib(path):
            return None

        # Must start with our module path
        if not (path == ctx.go_module or path.startswith(ctx.go_module + "/")):
            return None

        # Strip module prefix → relative package dir
        suffix = path[len(ctx.go_module):].lstrip("/")
        if not suffix:
            suffix = "."

        pkg_dir = suffix  # e.g. "internal/auth"

        # Find all .go files in that directory (non-test)
        importing_is_test = file_path.endswith("_test.go")
        matches = []
        for f in ctx.all_files:
            if not f.endswith(".go"):
                continue
            f_dir = str(Path(f).parent)
            if f_dir == pkg_dir or (pkg_dir == "." and "/" not in f):
                if not importing_is_test and f.endswith("_test.go"):
                    continue
                matches.append(f)

        # Return first match; builder will see the first file in the package
        return matches[0] if matches else None

    def resolve_import_all(self, raw: RawImport, file_path: str, ctx) -> list[str]:
        """Return all .go files in the target package (for multi-file package edges)."""
        path = raw.module
        if not ctx.go_module or _is_stdlib(path):
            return []
        if not (path == ctx.go_module or path.startswith(ctx.go_module + "/")):
            return []

        suffix = path[len(ctx.go_module):].lstrip("/") or "."
        pkg_dir = suffix
        importing_is_test = file_path.endswith("_test.go")

        matches = []
        for f in ctx.all_files:
            if not f.endswith(".go"):
                continue
            f_dir = str(Path(f).parent)
            if f_dir == pkg_dir or (pkg_dir == "." and "/" not in f):
                if not importing_is_test and f.endswith("_test.go"):
                    continue
                matches.append(f)
        return matches
