import logging
from pathlib import Path
from typing import Optional

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

from .base import LanguageHandler, RawImport

logger = logging.getLogger(__name__)

_JAVA_LANGUAGE = Language(tsjava.language())
_JAVA_PARSER = Parser(_JAVA_LANGUAGE)

# Captures both regular and wildcard imports
_IMPORT_QUERY = _JAVA_LANGUAGE.query("""
(import_declaration (scoped_identifier) @fqcn)
""")

# Wildcard: import_declaration that has an asterisk child
_WILDCARD_QUERY = _JAVA_LANGUAGE.query("""
(import_declaration
  (scoped_identifier) @pkg
  (asterisk))
""")


class JavaHandler(LanguageHandler):
    language_name = "Java"

    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        tree = _JAVA_PARSER.parse(source_bytes)
        parse_error = tree.root_node.has_error
        imports: list[RawImport] = []

        wildcard_lines: set[int] = set()
        for node in _WILDCARD_QUERY.captures(tree.root_node).get("pkg", []):
            wildcard_lines.add(node.start_point[0])

        for node in _IMPORT_QUERY.captures(tree.root_node).get("fqcn", []):
            line = node.start_point[0]
            fqcn = node.text.decode("utf-8", errors="replace")
            is_wildcard = line in wildcard_lines
            imports.append(RawImport(
                module=fqcn + (".*" if is_wildcard else ""),
                is_relative=False,
                symbol=None,
                line=line + 1,
            ))

        return imports, parse_error

    def resolve_import(self, raw: RawImport, file_path: str, ctx) -> Optional[str]:
        fqcn = raw.module

        if fqcn.endswith(".*"):
            # Wildcard: resolve to all matching FQCNs
            prefix = fqcn[:-2]  # strip .*
            results = [
                path for f, path in ctx.java_fqcn_index.items()
                if f.startswith(prefix + ".")
            ]
            # Return first match only (builder will call us once per raw import)
            return results[0] if results else None

        return ctx.java_fqcn_index.get(fqcn)

    def resolve_import_all(self, raw: RawImport, file_path: str, ctx) -> list[str]:
        """Return all resolved paths (for wildcard imports)."""
        fqcn = raw.module
        if fqcn.endswith(".*"):
            prefix = fqcn[:-2]
            return [
                path for f, path in ctx.java_fqcn_index.items()
                if f.startswith(prefix + ".")
            ]
        result = ctx.java_fqcn_index.get(fqcn)
        return [result] if result else []
