# DepGraph — Phase 2: Tree-sitter Integration (Python Only)

## Goal

Parse every `.py` file in the cloned repo using `py-tree-sitter`. Extract imports. Resolve them to file paths within the repo. Build an in-memory directed graph. Return it as JSON.

At the end of Phase 2, submitting a Python repo returns the real dependency graph for that repo. No other languages yet, no cycles, no SSE.

## Deliverable

```
POST /analyze { "url": "https://github.com/psf/requests" }

→ 200
{
  "job_id": "...",
  "commit_sha": "...",
  "nodes": [
    {"id": "src/requests/api.py", "label": "api.py", "language": "python", "size": 15},
    ...
  ],
  "edges": [
    {"source": "src/requests/api.py", "target": "src/requests/sessions.py", "type": "import"},
    ...
  ]
}
```

---

## Pipeline stages to implement

### Stage 5 — AST parsing per file

- **Input:** `FileEntry` + `Language`.
- **Output:** `tree_sitter.Tree`.
- **Logic:** One `Parser` instance per language, reused across files (parsers are stateless after `set_language`). **For Phase 2, start single-threaded.** Add `ProcessPoolExecutor` in Phase 5.
- **Latency:** 5–15 ms per file FFI overhead + parse.
- **Failures:** Parse error (malformed source) → still emit the file as a node with `parse_error=true`, no edges from it.

### Stage 6 — Import/export extraction

- **Input:** `Tree` + source bytes.
- **Output:** `ImportSet`, `ExportSet` (per file).
- **Logic:** Pre-compiled Tree-sitter `Query` objects per language. Run query, capture import-statement nodes, extract the literal string. Do NOT resolve to a filesystem path here — just collect raw import strings. Resolution happens in Stage 7 because it needs the full file inventory.
- **Latency:** ~1ms per file.
- **Failures:** Missing capture (unusual import syntax) → log to `unresolved_imports[]`, do not fail.

### Stage 7 — Graph construction

- **Input:** `dict[file_path, (ImportSet, ExportSet)]`.
- **Output:** `Graph { nodes[], edges[] }`.
- **Logic:** Two passes. Pass 1: build a `ResolverIndex` mapping every possible "what an import string could mean" to a real file path. For Python: package name → `__init__.py` path; relative dot notation → resolved path. Pass 2: for each file's imports, look up in `ResolverIndex`; on hit, emit edge. On miss, classify as `external` and emit no edge.
- **Latency:** ~200ms for 500 files.
- **Failures:** Resolver miss is normal (external packages) — silent.

---

## Python-specific extraction

Grammar: `tree-sitter-python` v0.21+.

### Import extraction — Tree-sitter node types

Query nodes for **imports**:
- `import_statement` (children: `dotted_name`, `aliased_import`)
- `import_from_statement` (children: `dotted_name` for module, `relative_import`, `import_list`, `wildcard_import`)

Query nodes for **exports**: Python has no syntactic `export`. Emit all top-level `function_definition`, `class_definition`, and assignments to `identifier` at module scope as exports, UNLESS the file has an `__all__` assignment, in which case honor it.

### Hardest case — relative imports with `__init__.py` packages and namespace packages

`from ..utils.helpers import x` requires knowing:
1. The file's package depth.
2. Whether `utils/` has an `__init__.py` (regular package) or not (PEP 420 namespace package).
3. Whether `helpers` is a submodule, a class, or a re-exported symbol from `utils/__init__.py`.

**Decision:** build a `PackageIndex` that maps directory paths to package status (regular/namespace/not-a-package) by scanning for `__init__.py` files during file discovery.

Resolve `..utils.helpers` by:
1. Walking up `parent_dir` count of dots from the importing file.
2. Descending the dotted path from there.
3. At each level, checking whether the name resolves to `<n>.py`, `<n>/__init__.py`, or a namespace `<n>/`.
4. The leaf import (`x`) is treated as a symbol *within* the resolved module — link the edge to the module file, not to a hypothetical "x" node.

### Example queries to implement

```scheme
; Standard import: `import os`, `import os.path`
(import_statement
  name: (dotted_name) @import_path)

; Aliased: `import numpy as np`
(import_statement
  name: (aliased_import
    name: (dotted_name) @import_path))

; From import: `from x.y import z`
(import_from_statement
  module_name: (dotted_name) @import_path)

; Relative from import: `from ..utils import helper`
(import_from_statement
  module_name: (relative_import) @relative_path)
```

Capture these as strings, pass to the resolver.

---

## Graph JSON schema (target shape)

Each node:
```json
{
  "id": "src/requests/api.py",
  "label": "api.py",
  "language": "python",
  "size": 15,
  "is_cycle": false,
  "cluster": "src/requests",
  "parse_error": false
}
```

Each edge:
```json
{
  "source": "src/requests/api.py",
  "target": "src/requests/sessions.py",
  "type": "import",
  "is_cycle": false,
  "symbol": "Session",
  "line": 12
}
```

`size` = file LOC / 20, clamped to [8, 30]. `cluster` = top-2-levels of the path. `is_cycle` filled in later (Phase 4). `symbol` and `line` populated from the Tree-sitter capture location.

---

## Tests (write these as you go, not after)

Create `backend/tests/fixtures/python_simple/` with a hand-built 5-file repo:

```
python_simple/
├── main.py          # imports from utils, from ./helpers
├── helpers.py       # no imports
├── utils/
│   ├── __init__.py  # re-exports from .io
│   └── io.py        # imports from ..helpers (relative)
└── orphan.py        # imports nothing, imported by nothing
```

Assertions:
1. `main.py → helpers.py` edge exists.
2. `main.py → utils/__init__.py` edge exists.
3. `utils/io.py → helpers.py` edge exists (relative `..` resolved).
4. `orphan.py` appears as a node with no edges.
5. Total edge count equals exactly what you hand-counted.

**Run this test. If any assertion fails, stop and fix — do not proceed to Phase 3 with a broken Python resolver.** The other 6 languages will inherit this class's structure.

---

## Code structure

```
backend/
├── main.py
├── parsers/
│   ├── __init__.py
│   ├── base.py          # abstract LanguageHandler
│   └── python.py        # PythonHandler
├── graph/
│   ├── __init__.py
│   ├── resolver.py      # ResolverIndex, PackageIndex
│   └── builder.py       # builds nodes + edges
└── tests/
    └── fixtures/
        └── python_simple/
```

`LanguageHandler` is an abstract base class with:
- `extract_imports(tree, source_bytes) -> list[RawImport]`
- `resolve_import(raw_import, file_path, repo_index) -> Optional[str]`

This is the seam for Phase 3 — every other language plugs in here.

## Constraints

- Single-threaded in this phase.
- Read files as bytes (`open(f, "rb").read()`). Tree-sitter accepts bytes natively. Do NOT decode to string just to re-encode.
- Use `py-tree-sitter` >= 0.21 and the pre-built `tree-sitter-python` wheel. Do NOT compile grammars from source at runtime.
- Store the `Query` objects as module-level constants, compiled once at startup, reused per request.

## Time budget

3 hours.
