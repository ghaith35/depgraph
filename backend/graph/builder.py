import logging
from pathlib import Path

from parsers.base import LanguageHandler, RawImport
from parsers.python import PythonHandler

logger = logging.getLogger(__name__)

# Map file extension → handler instance (one per language, reused)
_HANDLERS: dict[str, LanguageHandler] = {
    ".py": PythonHandler(),
}


def _loc(source_bytes: bytes) -> int:
    return source_bytes.count(b"\n") + 1


def _size_node(loc: int) -> int:
    return max(8, min(30, loc // 20))


def _cluster(path: str) -> str:
    parts = Path(path).parts[:-1]   # drop filename
    return str(Path(*parts[:2])) if len(parts) >= 2 else (parts[0] if parts else "")


def build_graph(repo_root: Path, files: list) -> dict:
    """
    files: list of FileEntry from file discovery.
    Returns {"nodes": [...], "edges": [...]}.
    """
    nodes = []
    edges = []

    # Pass 1: parse every supported file, collect imports
    file_imports: dict[str, tuple[list[RawImport], bool]] = {}

    for entry in files:
        suffix = Path(entry.path).suffix.lower()
        handler = _HANDLERS.get(suffix)
        if handler is None:
            continue

        abs_path = repo_root / entry.path
        try:
            source = abs_path.read_bytes()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", entry.path, exc)
            continue

        raw_imports, parse_error = handler.extract_imports(source)
        file_imports[entry.path] = (raw_imports, parse_error)

        loc = _loc(source)
        nodes.append({
            "id": entry.path,
            "label": Path(entry.path).name,
            "language": entry.language_hint,
            "size": _size_node(loc),
            "is_cycle": False,
            "cluster": _cluster(entry.path),
            "parse_error": parse_error,
        })

    # Also emit nodes for non-parsed files (other languages)
    parsed_paths = set(file_imports.keys())
    for entry in files:
        if entry.path not in parsed_paths:
            abs_path = repo_root / entry.path
            try:
                loc = _loc(abs_path.read_bytes())
            except OSError:
                loc = 1
            nodes.append({
                "id": entry.path,
                "label": Path(entry.path).name,
                "language": entry.language_hint,
                "size": _size_node(loc),
                "is_cycle": False,
                "cluster": _cluster(entry.path),
                "parse_error": False,
            })

    # Build a set of known file paths for fast lookup
    known_paths = {e.path for e in files}

    # Pass 2: resolve imports → edges
    for file_path, (raw_imports, _) in file_imports.items():
        suffix = Path(file_path).suffix.lower()
        handler = _HANDLERS.get(suffix)
        if handler is None:
            continue

        seen_targets: set[str] = set()
        for raw in raw_imports:
            target = handler.resolve_import(raw, file_path, repo_root)
            if target is None:
                continue
            # Normalise path separators
            target = target.replace("\\", "/")
            if target not in known_paths:
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
