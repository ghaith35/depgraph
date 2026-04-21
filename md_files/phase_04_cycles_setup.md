# DepGraph — Phase 4: Cycle Detection + Setup Instructions + Full Schema

## Goal
Detect circular dependencies using Tarjan's SCC algorithm. Generate setup instructions from manifest files. Finalize the `AnalysisResult` Pydantic schema. All synchronous still — no SSE yet.

## Time budget
2 hours.

## Prerequisites
Phase 3 complete. Multi-language graph construction working.

---

## Part 1: Cycle detection

### Algorithm: Tarjan's SCC via networkx

Use `networkx.strongly_connected_components(G)`. It returns an iterator of sets. A set is a cycle if:
- It contains 2 or more nodes (mutual cycle), OR
- It contains exactly 1 node AND that node has a self-edge (self-cycle, rare but possible).

```python
def detect_cycles(graph: nx.DiGraph) -> list[list[str]]:
    cycles = []
    for scc in nx.strongly_connected_components(graph):
        if len(scc) > 1:
            cycles.append(sorted(scc))
        elif len(scc) == 1:
            node = next(iter(scc))
            if graph.has_edge(node, node):
                cycles.append([node])
    return cycles
```

### Marking cycle membership on nodes and edges
For each SCC (returned as a set of node IDs):
- Set `is_cycle = True` on every node in the SCC.
- Set `is_cycle = True` on every edge whose source AND target are both in the same SCC. An edge from a cycle node to a non-cycle node is NOT a cycle edge.

### Simple cycle paths (optional detail for the report)
Beyond SCCs, the user may want to know the actual cycle path (e.g., `A → B → C → A`). Use `networkx.simple_cycles(graph.subgraph(scc))` per SCC. **Cap at 50 simple cycles per SCC** — a fully-connected SCC of 6 nodes has 720 simple cycles, which is not useful to display.

```python
def extract_cycle_paths(graph: nx.DiGraph, scc: set[str], cap: int = 50) -> list[list[str]]:
    subgraph = graph.subgraph(scc).copy()
    paths = []
    for i, cycle in enumerate(nx.simple_cycles(subgraph)):
        if i >= cap:
            break
        paths.append(cycle)
    return paths
```

### CycleReport schema
```python
class CycleReport(BaseModel):
    scc_count: int           # number of SCCs of size >= 2 (or 1 with self-loop)
    node_count_in_cycles: int
    edge_count_in_cycles: int
    sccs: list[list[str]]    # sorted node lists, one per SCC
    simple_cycles: list[list[str]]  # up to 50 simple cycles per SCC, flat list
```

---

## Part 2: Setup instruction generation

Pure heuristics, no LLM. Scan the repo root (and up to depth 2) for known manifest files.

### SetupSteps schema
```python
class SetupSteps(BaseModel):
    runtime: str              # "node", "python", "go", "rust", "java", "c", "unknown"
    install_cmd: str | None   # e.g., "npm install"
    build_cmd: str | None     # e.g., "npm run build"
    run_cmd: str | None       # e.g., "npm run dev"
    env_vars: list[str]       # keys from .env.example
    notes: list[str]          # free-form warnings or tips
```

### Detection rules (in priority order)

**Node/JS/TS (`package.json` present):**
- `runtime = "node"`
- Parse `package.json`. If `scripts.dev` exists → `run_cmd = "npm run dev"`; elif `scripts.start` → `"npm start"`.
- `scripts.build` → `build_cmd = "npm run build"`.
- Detect package manager: if `pnpm-lock.yaml` → use `pnpm`; if `yarn.lock` → `yarn`; if `bun.lockb` → `bun`; else `npm`.
- `install_cmd = "<pm> install"`.

**Python (`pyproject.toml` OR `requirements.txt` OR `Pipfile`):**
- `runtime = "python"`
- `pyproject.toml` with `[tool.poetry]` → `install_cmd = "poetry install"`, `run_cmd = "poetry run python main.py"` (best guess).
- `pyproject.toml` without poetry (PEP 621) → `install_cmd = "pip install -e ."`.
- `requirements.txt` → `install_cmd = "pip install -r requirements.txt"`.
- `Pipfile` → `install_cmd = "pipenv install"`.
- `run_cmd` — look for `main.py`, `app.py`, `manage.py`, `__main__.py` at root and suggest the first one found.

**Rust (`Cargo.toml`):**
- `runtime = "rust"`, `install_cmd = "cargo build"`, `build_cmd = "cargo build --release"`, `run_cmd = "cargo run"`.

**Go (`go.mod`):**
- `runtime = "go"`, `install_cmd = "go mod download"`, `build_cmd = "go build ./..."`.
- `run_cmd` — if `main.go` at root → `"go run ."`; else look for a `cmd/` subdir and suggest `"go run ./cmd/<first-subdir>"`.

**Java (`pom.xml` OR `build.gradle` OR `build.gradle.kts`):**
- `runtime = "java"`.
- Maven (`pom.xml`) → `install_cmd = "mvn install"`, `run_cmd = "mvn exec:java"`.
- Gradle → `install_cmd = "./gradlew build"`, `run_cmd = "./gradlew run"`.

**C/C++ (`CMakeLists.txt` OR `Makefile`):**
- `runtime = "c"` (or `"cpp"` if any `.cpp` files found).
- CMake → `build_cmd = "cmake -B build && cmake --build build"`.
- Makefile → `install_cmd = "make"`.

**No recognized manifest:**
- `runtime = "unknown"`, all commands `None`, `notes = ["No recognized build manifest found."]`.

### Environment variables
- Look for `.env.example`, `.env.sample`, `.env.template` at repo root.
- If found, read the file, extract keys (lines matching `^([A-Z_][A-Z0-9_]*)=.*`), populate `env_vars`.
- Also check `README.md` if no env file exists — scan for patterns like `` `API_KEY=...` `` in code blocks. Best-effort only.

### Multiple manifests
A repo can have Python and JS (e.g., a Django + React monorepo). Pick the dominant runtime by file count:
- If >60% of source files are one language, use that language's setup.
- Otherwise, set `notes` to list both and pick the one with the most files as primary.

---

## Part 3: Finalized Pydantic schema

```python
class Node(BaseModel):
    id: str                  # repo-relative path
    label: str               # basename
    language: str            # "Python" | "TypeScript" | ... | "Unknown"
    size: int                # LOC
    is_cycle: bool
    cluster: str             # directory path, depth 2
    parse_error: bool = False
    is_outlier_hub: bool = False  # populated in Phase 7


class Edge(BaseModel):
    source: str
    target: str
    type: str                # "import" | "require" | "dynamic" | "include"
    symbol: str | None       # the imported name if known
    line: int
    is_cycle: bool
    has_dynamic_target: bool = False  # for JS/TS dynamic imports


class RepoStats(BaseModel):
    file_count: int
    total_size_bytes: int
    total_loc: int
    languages: dict[str, int]       # language -> file count
    commit_sha: str
    repo_url: str
    analysis_duration_ms: int


class AnalysisResult(BaseModel):
    job_id: str
    stats: RepoStats
    graph: Graph
    cycles: CycleReport
    setup: SetupSteps
    unresolved_imports_count: int   # diagnostic
    schema_version: str = "1.0"


class Graph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
```

**Place this schema in `backend/app/schemas.py` and also export it as JSON Schema to `shared/graph_schema.json`** (a file checked into the repo root `shared/` directory). The frontend will consume this JSON Schema to validate incoming data. Generate with:

```python
# In a script or a pytest fixture, run once:
with open("shared/graph_schema.json", "w") as f:
    json.dump(AnalysisResult.model_json_schema(), f, indent=2)
```

---

## Part 4: Wiring

The `POST /analyze` response now returns the full `AnalysisResult`:

```python
@app.post("/analyze", response_model=AnalysisResult)
async def analyze(req: AnalyzeRequest) -> AnalysisResult:
    # ...clone, walk, parse, build graph...
    cycles = detect_cycles(graph)
    setup = generate_setup(repo_root)
    return AnalysisResult(...)
```

---

## Verification tests

### Test A — intentional 3-file cycle
Fixture `tests/fixtures/cycle_three/`:
```
cycle_three/
├── a.py    # imports b
├── b.py    # imports c
└── c.py    # imports a
```

Assert:
- `cycles.scc_count == 1`
- `cycles.sccs == [["a.py", "b.py", "c.py"]]`
- All 3 nodes have `is_cycle = True`.
- All 3 edges have `is_cycle = True`.
- `len(cycles.simple_cycles) == 1` (only one simple cycle through these 3 nodes).

### Test B — two disjoint cycles
Fixture with two independent cycles: `{a, b}` and `{c, d, e}`. Assert `scc_count == 2` and each SCC's members are correctly flagged.

### Test C — cycle node connecting to a non-cycle node
`a → b → a` (cycle), plus `a → c` (c is not in cycle). Assert: `a` and `b` have `is_cycle = True`, `c` has `is_cycle = False`. The edge `a → c` has `is_cycle = False` even though `a` is in a cycle.

### Test D — self-cycle
A file that imports itself (rare but possible in some languages). Assert it's detected as a single-node SCC with the self-edge flagged.

### Test E — Python project with requirements.txt
Fixture with `requirements.txt` at root, `main.py` present. Assert:
- `setup.runtime == "python"`
- `setup.install_cmd == "pip install -r requirements.txt"`
- `setup.run_cmd == "python main.py"`

### Test F — Node project with package.json
Fixture with `package.json` containing `scripts: {"dev": "vite", "build": "vite build"}` and `pnpm-lock.yaml`.
- `setup.install_cmd == "pnpm install"`
- `setup.run_cmd == "pnpm run dev"`

### Test G — .env.example extraction
Fixture with a `.env.example` containing:
```
DATABASE_URL=postgres://localhost/mydb
API_KEY=your-key-here
# a comment
DEBUG=false
```
Assert `setup.env_vars == ["DATABASE_URL", "API_KEY", "DEBUG"]`.

### Test H — JSON Schema export
Run the export script. Validate the generated JSON Schema file is parseable. Load it on the frontend (placeholder test) and confirm it validates a known-good response.

---

## Out of scope for this phase
- SSE streaming (Phase 5)
- Rendering (Phase 6)
- AI (Phase 8)
- Caching (Phase 9)

---

## Common pitfalls
- Don't use `nx.simple_cycles` on the full graph — it's exponential. Always subgraph it to an SCC first.
- Don't forget the self-loop case in cycle detection — `len(scc) == 1` is not always non-cyclic.
- Don't generate setup commands from LLM — latency budget forbids it. Pure heuristics.
- When parsing `package.json`, wrap in try/except — some repos have invalid or comment-laden JSON.
