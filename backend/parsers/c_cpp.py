import logging
from pathlib import Path
from typing import Optional

import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser

from .base import LanguageHandler, RawImport

logger = logging.getLogger(__name__)

_C_LANGUAGE = Language(tsc.language())
_CPP_LANGUAGE = Language(tscpp.language())
_C_PARSER = Parser(_C_LANGUAGE)
_CPP_PARSER = Parser(_CPP_LANGUAGE)

_C_INCLUDE_QUERY = _C_LANGUAGE.query("""
(preproc_include path: (string_literal) @local)
(preproc_include path: (system_lib_string) @system)
""")

_CPP_INCLUDE_QUERY = _CPP_LANGUAGE.query("""
(preproc_include path: (string_literal) @local)
(preproc_include path: (system_lib_string) @system)
""")

# Common include search dirs (relative to repo root)
_INCLUDE_DIRS = ["include", "inc", "src/include", "src", "."]


def _strip_quotes(text: bytes) -> str:
    s = text.decode("utf-8", errors="replace")
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


class CHandler(LanguageHandler):
    language_name = "C"

    def _get_parser(self) -> Parser:
        return _C_PARSER

    def _get_query(self):
        return _C_INCLUDE_QUERY

    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        tree = self._get_parser().parse(source_bytes)
        parse_error = tree.root_node.has_error
        imports: list[RawImport] = []

        caps = self._get_query().captures(tree.root_node)

        # Local includes (#include "foo.h")
        for node in caps.get("local", []):
            path = _strip_quotes(node.text)
            imports.append(RawImport(
                module=path,
                is_relative=True,
                symbol=None,
                line=node.start_point[0] + 1,
            ))

        # System includes (#include <stdio.h>) — mark as external
        for node in caps.get("system", []):
            path = node.text.decode("utf-8", errors="replace").strip("<>")
            imports.append(RawImport(
                module=path,
                is_relative=False,
                symbol=None,
                line=node.start_point[0] + 1,
            ))

        return imports, parse_error

    def resolve_import(self, raw: RawImport, file_path: str, ctx) -> Optional[str]:
        if not raw.is_relative:
            return None  # system include → external

        header = raw.module
        file_dir = str(Path(file_path).parent)

        # Probe order: same dir, then common include dirs
        search_dirs = [file_dir] + _INCLUDE_DIRS
        for search_dir in search_dirs:
            if search_dir == ".":
                candidate = header
            else:
                candidate = f"{search_dir}/{header}".lstrip("/")
            candidate = candidate.replace("\\", "/")
            if candidate in ctx.all_files:
                return candidate

        return None


class CppHandler(CHandler):
    language_name = "C++"

    def _get_parser(self) -> Parser:
        return _CPP_PARSER

    def _get_query(self):
        return _CPP_INCLUDE_QUERY
