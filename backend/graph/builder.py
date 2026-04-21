import logging
from pathlib import Path

from parsers.base import RawImport
from parsers.python import PythonHandler
from parsers.javascript import JavaScriptHandler
from parsers.typescript import TypeScriptHandler
from parsers.java import JavaHandler
from parsers.go_lang import GoHandler
from parsers.rust import RustHandler
from parsers.c_cpp import CHandler, CppHandler
from graph.context import RepoContext, build_context

logger = logging.getLogger(__name__)

# Map extension → handler instance (one per language, reused across requests)
_HANDLERS = {
    ".py":   PythonHandler(),
    ".js":   JavaScriptHandler(),
    ".jsx":  JavaScriptHandler(),
    ".mjs":  JavaScriptHandler(),
    ".cjs":  JavaScriptHandler(),
    ".ts":   TypeScriptHandler(is_tsx=False),
    ".tsx":  TypeScriptHandler(is_tsx=True),
    ".java": JavaHandler(),
    ".go":   GoHandler(),
    ".rs":   RustHandler(),
    ".c":    CHandler(),
    ".h":    CHandler(),
    ".cpp":  CppHandler(),
    ".cc":   CppHandler(),
    ".cxx":  CppHandler(),
    ".hpp":  CppHandler(),
    ".hxx":  CppHandler(),
}


def _loc(source_bytes: bytes) -> int:
    return source_bytes.count(b"\n") + 1


def _size_node(loc: int) -> int:
    return max(8, min(30, loc // 20))


def _cluster(path: str) -> str:
    parts = Path(path).parts[:-1]
    return str(Path(*parts[:2])) if len(parts) >= 2 else (parts[0] if parts else "")


def build_graph(repo_root: Path, files: list) -> dict:
    """Build dependency graph from discovered files. Returns {nodes, edges}."""
    all_file_paths = {f.path for f in files}

    # Build per-language resolution context
    ctx = build_context(repo_root, all_file_paths)

    nodes = []
    edges = []

    # Pass 1: parse all supported files
    file_imports: dict[str, tuple[list[RawImport], bool]] = {}

    for entry in files:
        suffix = Path(entry.path).suffix.lower()
        handler = _HANDLERS.get(suffix)

        abs_path = repo_root / entry.path
        try:
            source = abs_path.read_bytes()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", entry.path, exc)
            source = b""

        parse_error = False
        if handler and source:
            raw_imports, parse_error = handler.extract_imports(source)
            file_imports[entry.path] = (raw_imports, parse_error)

        loc = _loc(source) if source else 1
        nodes.append({
            "id": entry.path,
            "label": Path(entry.path).name,
            "language": entry.language_hint,
            "size": _size_node(loc),
            "is_cycle": False,
            "cluster": _cluster(entry.path),
            "parse_error": parse_error,
        })

    # Pass 2: resolve imports → edges
    for file_path, (raw_imports, _) in file_imports.items():
        suffix = Path(file_path).suffix.lower()
        handler = _HANDLERS.get(suffix)
        if handler is None:
            continue

        seen_targets: set[str] = set()

        for raw in raw_imports:
            if raw.is_dynamic:
                continue

            # Go and Java can resolve to multiple targets
            if hasattr(handler, "resolve_import_all"):
                targets = handler.resolve_import_all(raw, file_path, ctx)
            else:
                t = handler.resolve_import(raw, file_path, ctx)
                targets = [t] if t else []

            for target in targets:
                if not target:
                    continue
                target = target.replace("\\", "/")
                if target not in all_file_paths:
                    continue
                if target == file_path:
                    continue
                if target in seen_targets:
                    continue
                seen_targets.add(target)
                edges.append({
                    "source": file_path,
                    "target": target,
                    "type": "import",
                    "is_cycle": False,
                    "symbol": raw.symbol,
                    "line": raw.line,
                })

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Phase 5 helpers — used by the streaming pipeline
# ---------------------------------------------------------------------------

def parse_one_file(entry, repo_root: Path) -> tuple[dict, list, bool]:
    """Parse a single file. Returns (node_dict, raw_imports, parse_error).
    Safe to call from any thread (no shared mutable state).
    """
    suffix = Path(entry.path).suffix.lower()
    handler = _HANDLERS.get(suffix)

    abs_path = repo_root / entry.path
    try:
        source = abs_path.read_bytes()
    except OSError as exc:
        logger.warning("Cannot read %s: %s", entry.path, exc)
        source = b""

    parse_error = False
    raw_imports: list = []
    if handler and source:
        raw_imports, parse_error = handler.extract_imports(source)

    loc = _loc(source) if source else 1
    node_dict = {
        "id": entry.path,
        "label": Path(entry.path).name,
        "language": entry.language_hint,
        "size": _size_node(loc),
        "is_cycle": False,
        "cluster": _cluster(entry.path),
        "parse_error": parse_error,
    }
    return node_dict, raw_imports, parse_error


def resolve_imports_batch(
    file_imports: dict[str, tuple[list, bool]],
    ctx,
    all_file_paths: set[str],
) -> list[dict]:
    """Resolve all raw imports collected during parsing into edge dicts."""
    edges: list[dict] = []

    for file_path, (raw_imports, _) in file_imports.items():
        suffix = Path(file_path).suffix.lower()
        handler = _HANDLERS.get(suffix)
        if handler is None:
            continue

        seen_targets: set[str] = set()

        for raw in raw_imports:
            if raw.is_dynamic:
                continue

            if hasattr(handler, "resolve_import_all"):
                targets = handler.resolve_import_all(raw, file_path, ctx)
            else:
                t = handler.resolve_import(raw, file_path, ctx)
                targets = [t] if t else []

            for target in targets:
                if not target:
                    continue
                target = target.replace("\\", "/")
                if target not in all_file_paths:
                    continue
                if target == file_path:
                    continue
                if target in seen_targets:
                    continue
                seen_targets.add(target)
                edges.append({
                    "source": file_path,
                    "target": target,
                    "type": "import",
                    "is_cycle": False,
                    "symbol": raw.symbol,
                    "line": raw.line,
                })

    return edges
