# DepGraph — Phase 3: Multi-Language Extraction

## Goal
Add JavaScript, TypeScript, Java, Go, Rust, C, and C++ parsers and resolvers alongside the Python one from Phase 2. Every Tier 1 language is supported.

## Time budget
5 hours (includes the TypeScript monorepo resolution work).

## Prerequisites
Phase 2 complete. Python parsing + graph building works end-to-end.

---

## Dependencies to add
```
tree-sitter-javascript
tree-sitter-typescript
tree-sitter-java
tree-sitter-go
tree-sitter-rust
tree-sitter-c
tree-sitter-cpp
```

---

## Architecture

Refactor the parser logic into a handler-per-language pattern:

```python
class LanguageHandler(ABC):
    language_name: str  # "Python", "TypeScript", etc.

    @abstractmethod
    def extract_imports(self, source: bytes, tree) -> list[RawImport]:
        ...

    @abstractmethod
    def resolve_import(self, imp: RawImport, source_file: str, repo_context: RepoContext) -> Optional[str]:
        ...
```

`RepoContext` holds: all discovered files, per-language indices (PackageIndex for Python, FqcnIndex for Java, TSConfigMap for TypeScript, ModTree for Rust, go.mod module path for Go).

Register handlers: `HANDLERS: dict[Language, LanguageHandler]`.

The pipeline becomes: for each file, look up the handler by language, call `extract_imports`, then `resolve_import` for each raw import.

---

## Language-specific Tree-sitter queries and resolution logic

### 3.1 JavaScript (`tree-sitter-javascript`)

**Query nodes for imports:**
```
(import_statement source: (string) @source)

(call_expression
  function: (identifier) @fn (#eq? @fn "require")
  arguments: (arguments (string) @source))

(call_expression
  function: (import) @fn
  arguments: (arguments (string) @source))

(export_statement source: (string) @source)
```

This captures ES modules (`import`), CommonJS (`require`), dynamic imports (`import()`), and re-exports (`export * from`).

**Query nodes for exports:**
- `export_statement` (any form)
- `assignment_expression` where left side is `module.exports` or `exports.X` (CommonJS)

**Resolution for JS:**
- Bare specifiers (`"react"`, `"lodash/get"`): external, no edge. But check first against `package.json` workspaces — if the specifier matches a workspace package name, resolve to that workspace's root.
- Relative paths (`"./utils"`, `"../lib/foo"`):
  1. Join with the importing file's directory.
  2. Probe extensions in order: `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`.
  3. If no match, try as directory: append `/index` then repeat the extension probe.
  4. First match wins. No match → unresolved.

**Dynamic imports with template strings:** Detect if the argument node is a `template_string` containing a `template_substitution`. If yes, emit the import as `has_dynamic_target: true`, target_pattern set to the literal parts concatenated with `*` replacing substitutions (e.g., `` `./locales/${x}.js` `` → `./locales/*.js`). Do not glob the filesystem to resolve it. Frontend renders these as dotted edges to a synthetic "dynamic" sink.

### 3.2 TypeScript (`tree-sitter-typescript`)

**Two parsers needed:** `tree-sitter-typescript` has two grammars — one for `.ts`, one for `.tsx`. Load both. Route by extension.

**Query nodes:** Same as JavaScript (the grammar is a superset). Same `import_statement`, `call_expression` for require/dynamic imports, same `export_statement`.

**Additional export node:** `export_statement` with `type` modifier (`export type { X }`) — treat same as regular export for graph purposes.

**Resolution — the critical piece.** Build a `TSResolver` at pipeline start:

1. **Discover all `tsconfig.json` files** in the repo. For each, parse as JSON5 (tsconfigs allow comments — use the `json5` library, add to requirements).

2. **Resolve `extends` chains**: if `extends` points to a path that's also a tsconfig in this repo, merge its `compilerOptions` with the child's (child overrides). If `extends` points to a `node_modules` package (e.g., `"extends": "@tsconfig/node20/tsconfig.json"`), we don't have it — fall back to defaults (`baseUrl: "."`, no `paths`).

3. **Build `tsconfig_map: dict[dir_path, TsConfig]`** — for each directory, the nearest enclosing tsconfig.

4. **Discover workspace aliases**: if `package.json` at repo root has a `workspaces` field, for each workspace package, read its `package.json`, register an alias: `"package-name"` → that workspace's root directory.

5. **For each TS/TSX/JS file**, find its governing tsconfig (deepest ancestor that has one). When resolving an import from that file:
   - a) Try `paths` alias match (longest prefix wins). If matched, substitute and probe extensions.
   - b) Try workspace alias match. If matched, substitute and treat as relative to workspace root.
   - c) Try as relative path (if import starts with `./` or `../`).
   - d) Try `baseUrl`-relative (if tsconfig has baseUrl).
   - e) Probe extensions: `.ts`, `.tsx`, `.d.ts`, `.js`, `.jsx`, then with `/index` suffix.
   - f) First hit wins.

**Known limitation — document it:** aliases defined only in `vite.config.ts` / `webpack.config.js` / `rollup.config.js` are not resolved. Most projects mirror them in tsconfig for IDE support; 5–10% don't. Accept this miss rate.

### 3.3 Java (`tree-sitter-java`)

**Query nodes for imports:**
```
(import_declaration (scoped_identifier) @fqcn)
(import_declaration (scoped_identifier) @fqcn (asterisk))
```

**Query nodes for exports:**
- Top-level `class_declaration`, `interface_declaration`, `enum_declaration`, `record_declaration`.
- Plus the `package_declaration` at the top of the file — this is the package name.

**Resolution:**
1. Build `FqcnIndex`: scan every `.java` file, read its `package_declaration` node, combine with the filename's class name → full FQCN. Map FQCN → file path.
2. For each import:
   - Exact FQCN match (`import com.foo.Bar` → look up `com.foo.Bar` in the index).
   - Wildcard import (`import com.foo.*`): find every FQCN in the index starting with `com.foo.` and emit edges to all of them.
   - No match → external (JDK, Maven dependency, etc.), no edge.

**Source root detection:** Java uses `src/main/java/com/foo/Bar.java` layout. The source root is the deepest directory such that the path below it matches the package declaration. For `package com.foo;` in `src/main/java/com/foo/Bar.java`, the source root is `src/main/java`. Use this to validate FQCN computation — if the path doesn't match the declared package, prefer the declared package.

### 3.4 Go (`tree-sitter-go`)

**Query nodes for imports:**
```
(import_declaration
  (import_spec
    path: (interpreted_string_literal) @path))

(import_declaration
  (import_spec_list
    (import_spec
      path: (interpreted_string_literal) @path)))
```

**Query nodes for exports:**
- Top-level `function_declaration`, `method_declaration`, `type_declaration`, `var_declaration`, `const_declaration`.
- Exported only if the declared identifier's first character is uppercase.

**Resolution:**
1. Parse `go.mod` at repo root (and any sub-`go.mod` for multi-module repos). Extract the `module` directive line.
2. For each import path `"github.com/myorg/myrepo/internal/auth"`:
   - If the path starts with the module path from go.mod, strip the prefix → `internal/auth` → resolve to `<repo_root>/internal/auth/` directory. The "edge target" is a Go package (directory), not a single file. In the graph, emit edges to every `.go` file in that directory (excluding `_test.go` files unless the importer is also a test file).
   - Standard library (`"fmt"`, `"net/http"`) — external, no edge.
   - Third-party (`"github.com/other/lib"`) — external, no edge.

Multi-module repos: each go.mod defines its own module scope. Resolve imports independently per module.

### 3.5 Rust (`tree-sitter-rust`)

**Query nodes for imports:**
```
(use_declaration (scoped_identifier) @path)
(use_declaration (scoped_use_list) @path)
(use_declaration (use_list) @path)
(use_declaration (use_as_clause) @path)
(extern_crate_declaration) @extern
```

**Query nodes for exports:**
- `function_item`, `struct_item`, `enum_item`, `trait_item`, `mod_item`, `impl_item`, `type_item`, `const_item`, `static_item` — exported only if preceded by a `visibility_modifier` of `pub` (or `pub(crate)`, `pub(super)`, etc.).

**Resolution — module tree:**
1. Parse `Cargo.toml` at repo root. Identify crate root(s): `src/lib.rs` (library), `src/main.rs` (binary), `src/bin/*.rs` (additional binaries). Also check `[[bin]]` and `[lib]` sections for custom paths. Workspace repos have multiple `Cargo.toml` — each is a crate.
2. For each crate root, recursively build a `ModTree`: every `mod foo;` declaration in `lib.rs` means "look for `src/foo.rs` or `src/foo/mod.rs`". Recurse. The tree maps dotted paths like `crate::foo::bar` → file path.
3. For each `use` statement in a file:
   - `use crate::foo::bar::Baz` → look up `foo::bar` in the ModTree of the file's crate. Resolve to the module's file.
   - `use super::foo` → go up one level in the mod tree from the current file's module.
   - `use self::foo` → current module.
   - `use external_crate::...` or `extern crate external_crate;` → external, no edge unless it's a workspace member crate (check Cargo.toml workspace section).

### 3.6 C and C++ (`tree-sitter-c`, `tree-sitter-cpp`)

**Query nodes for imports:**
```
(preproc_include path: (string_literal) @path)
(preproc_include path: (system_lib_string) @system)
```

**Query nodes for exports:**
- `function_definition`, `declaration` (prototypes), `type_definition`, `struct_specifier`, `enum_specifier` at top level. C has no module system — everything in `.h` is effectively exported.

**Resolution (best-effort, document as such):**
- `<system.h>` → external, no edge.
- `"local.h"` → probe in order:
  1. Same directory as the including file.
  2. Repo root.
  3. Common include dirs: `include/`, `inc/`, `src/include/`, `src/`.
  4. First hit wins. No hit → unresolved.
- We do not parse `CMakeLists.txt` or `Makefile` to discover `-I` paths. C is the language we expect to be wrong about most often. Accept this.

---

## Worker pool for parallelism

Once you have >1 language, parse files in parallel using a `concurrent.futures.ProcessPoolExecutor`. **However**, on Render's 512 MB free tier, we need adaptive worker count:

```python
def compute_max_workers() -> int:
    import resource
    # Measure baseline RSS after loading all grammars.
    baseline_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    # Conservative estimate: each worker adds ~80 MB.
    budget_mb = 480  # leave 32 MB headroom under 512
    max_workers = max(1, int((budget_mb - baseline_mb) // 80))
    return min(max_workers, 2)  # cap at 2 for safety
```

Start with `max_workers = 2`. If Render logs show OOM kills under load, drop to 1 and accept the slower parse time.

Each worker loads its own set of Tree-sitter parsers (can't share across processes). This is a cost — budget for it in the 80 MB/worker estimate.

---

## Verification tests

One fixture repo per language, each with 5–10 files and hand-verified expected edges.

### `tests/fixtures/js_commonjs/`
A tiny Node-style project with `require` statements. Assert edges resolve with extension probing and `/index.js` fallback.

### `tests/fixtures/ts_monorepo/`
A Turborepo-style structure:
```
ts_monorepo/
├── package.json (with "workspaces": ["packages/*"])
├── packages/
│   ├── shared/
│   │   ├── package.json (name: "@repo/shared")
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── index.ts
│   │       └── utils.ts
│   └── web/
│       ├── package.json
│       ├── tsconfig.json (with paths: {"@/*": ["./src/*"]})
│       └── src/
│           ├── main.ts (imports from "@/lib/x" and "@repo/shared")
│           └── lib/
│               └── x.ts
```
Assert that `main.ts` has two outgoing edges: one to `lib/x.ts` (via tsconfig paths alias) and one to `packages/shared/src/index.ts` (via workspace alias).

### `tests/fixtures/java_wildcard/`
5 Java files across 2 packages, with one wildcard import. Assert edges to all matching FQCNs.

### `tests/fixtures/go_module/`
A repo with `go.mod` declaring a module path, several packages importing each other by full path. Assert edges resolve after module-path stripping.

### `tests/fixtures/rust_modtree/`
A crate with nested `mod` declarations, `super::` and `crate::` uses. Assert the mod tree is walked correctly.

### `tests/fixtures/c_local_headers/`
C source files with `#include "local.h"` and `#include <system.h>`. Assert local includes resolve with the probe order above, and system includes are external.

### Smoke test — real repos
Run against these real GitHub repos and manually spot-check 5 edges each:
- `https://github.com/expressjs/express` (JS)
- `https://github.com/vercel/swr` (TS monorepo)
- `https://github.com/google/gson` (Java)
- `https://github.com/spf13/cobra` (Go)
- `https://github.com/tokio-rs/mini-redis` (Rust)
- `https://github.com/antirez/redis` (C)

---

## Out of scope for this phase
- Cycle detection (Phase 4)
- Setup instruction generation (Phase 4)
- SSE streaming (Phase 5)
- Rendering (Phase 6)
- AI (Phase 8)

---

## Known limitations to document in README
- TypeScript build-config-only aliases (Vite/Webpack) not resolved.
- C include paths only cover common layouts; custom `-I` flags from CMake/Make not parsed.
- Dynamic imports with computed strings show as dotted edges to a synthetic target.
- Go test files don't produce edges to non-test files unless the importer is also a test file.
