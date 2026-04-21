# DepGraph — Phase 11: UX Polish + Cached Examples

## Goal

Make the app feel finished for a first-time visitor. Pre-cached demo repos so users see the product working before they submit anything. Friendly error states. Loading skeletons. About page. Empty-state messaging. Edge case handling from the hidden-challenges list.

## Deliverable

A new visitor lands on the URL → sees a live demo graph of a popular OSS repo already rendered → can click around → understands what this tool does before typing anything.

---

## Pre-cached demo repos

Pick 5 well-known repos of varied shapes. Analyze each once, save the `AnalysisResult` JSON, serve from Vercel as static files.

**Recommended set:**
1. `https://github.com/fastapi/fastapi` — Python, medium size, has interesting graph shape.
2. `https://github.com/expressjs/express` — JS, small, clean.
3. `https://github.com/vitejs/vite` — TS monorepo, exercises tsconfig paths resolver.
4. `https://github.com/gin-gonic/gin` — Go, demonstrates module path resolution.
5. `https://github.com/pallets/flask` — Python, shows decorator-heavy architecture.

**Process:**
1. Analyze each locally via the deployed backend.
2. Save the full `AnalysisResult` as `frontend/public/demos/{slug}.json`.
3. Commit them to the repo.
4. Frontend has a "Demos" dropdown: selecting one loads from `/demos/{slug}.json` directly — no backend call.

### Demo mode UI

Landing page:
- Large repo URL input (centered, prominent).
- Below: "Or try a demo:" with the 5 repo names as chips.
- Clicking a chip: loads the static JSON, renders the graph immediately, shows a small banner "Viewing cached demo — submit a URL to analyze a different repo."

This means even a cold-start dyno or total backend outage still shows a working product. Portfolio value is preserved.

---

## Loading states

### During analysis (streaming)

While SSE events arrive from Phase 5, show:
- A subtle progress bar at the top, filling as `progress` events arrive.
- Stage label: "Cloning…", "Parsing…", "Building graph…", "Detecting cycles…".
- The graph canvas fades in from opacity 0 → 1 as nodes arrive, so it doesn't feel empty.
- Node count badge: "Nodes: 47" updating live.

### Cold-start wait

If no event received within 2 seconds of opening the SSE stream, show:
> "Waking up server (this happens after idle periods)..."

Disappears on first real event.

### First-time visitor

Before any URL submitted, show the landing page with demos. Do NOT auto-analyze; the user picks.

---

## Empty states

### Graph has 0 nodes (per Hidden Challenge 9.4)

Repo was valid but contains no supported source files. Show:
> "No source-code dependencies detected. This repo appears to contain only [docs / generated / config] files."
> List the file types detected.
> Button: "Analyze a different repo".

### Graph has nodes but 0 edges

All files are isolated. Show a banner:
> "This codebase has no detected imports between files. Each file appears to be self-contained."

Still render the nodes — they deserve to be visible.

### Repo has submodules (per Hidden Challenge 9.7)

Show banner:
> "This repo uses Git submodules, which were not analyzed. Edges to submodule files will appear as external."

### Dynamic imports detected (per Hidden Challenge 4.1)

Show banner if any edges have `type === "dynamic"`:
> "N dynamic imports detected. Some edges are shown as dashed lines — their targets could not be statically determined."

### Outlier hub detected (per Hidden Challenge 9.5)

Show banner if any node has `is_outlier_hub: true` (backend flags nodes with in-degree > 50 AND size in top decile):
> "N infrastructure files are heavily imported and shown in a separate cluster. [Hide them]"

---

## Error states

### Rate limited (from Phase 10)

```
429 Too Many Requests
```
Show:
> "You've analyzed 5 repos in the past hour. Try again in {retry_after} seconds, or explore the demos below."
> Show the demo chips.

### Queued (from Phase 5)

```
status: {queued, position: 3}
```
Show:
> "You're #3 in queue. Analyzing will start in ~24 seconds."
> Live position update as others complete.

### Analysis errors

- 400 Invalid URL → "That doesn't look like a valid GitHub/GitLab/Bitbucket URL."
- 404 Repo not found → "Repo not found. Is it private or mistyped?"
- 413 Too large → "This repo has too many files (max: 500 for live analysis)."
- 504 Clone timeout → "The repo took too long to clone. Try a smaller one?"
- 503 Server at capacity → "Server is slammed. Try again in 30 seconds, or check out a demo."
- 500 (anything) → "Unexpected error. The team has been notified. Try again or use a demo."

All errors use the same visual component — red banner, clear message, action button.

### AI unavailable (from Phase 8)

Side panel shows:
> "AI explanations are temporarily unavailable. The dependency graph is unaffected."

Graph interactions continue to work.

---

## Polish details

### Language legend

Small collapsible legend in a corner:
- Circle with language color + name + count, e.g. `● Python (47)`.
- Click a legend entry → highlights those nodes / dims others.
- Click again → unhighlight.

### Cycle panel

When `cycles.sccs` is non-empty, a collapsible panel shows:
> "⚠ N circular dependencies detected"
> List of SCCs, each clickable.
> Clicking an SCC pans/zooms to that cluster and highlights those nodes.

### Setup steps panel

Display the `setup` object as formatted steps:
```
Runtime: Python
Install:  pip install -r requirements.txt
Build:    (none)
Run:      python main.py
Env vars: DATABASE_URL, API_KEY
```
Copy button next to each command.

### Keyboard shortcuts

- `/` focuses the URL input.
- `Esc` clears selection, closes side panel.
- `f` toggles "fit to screen" (zoom to show all nodes).
- `l` toggles language legend.

### Share URL

When an analysis completes, update the URL bar to `/?repo=<encoded>`. Loading that URL re-runs (or hits cache for) the same analysis. Enables shareable links for portfolio/demo purposes.

### Dark mode

Default to system preference. Toggle in the header. Palette:
- Light: backgrounds `#ffffff` / `#f9fafb`, text `#1f2937`.
- Dark: backgrounds `#0f172a` / `#1e293b`, text `#f1f5f9`.
- Language colors stay the same (they're branded).

### About / Help modal

Small `?` button in header opens a modal:
- What DepGraph does.
- What it doesn't do (real-time indexing, private repos, etc).
- Link to `/security` page.
- Link to GitHub repo (for portfolio).

---

## Verification (must pass ALL of these)

1. First visit (incognito): landing page, demos visible, can click a demo and see a graph within 1 second. No backend call made for the demo load.

2. Submit a real URL, see the progress UI fill as events arrive. Stage labels change.

3. Disconnect Wi-Fi mid-analysis. UI shows "Connection lost" banner, not a crash.

4. Submit a bad URL → friendly error. Action button works.

5. Hit rate limit (5 in a row). See the rate-limit screen with demos.

6. Submit a docs-only repo (e.g. an awesome-list). See empty-state messaging correctly.

7. Keyboard shortcuts all work. `/` focuses input, `Esc` clears.

8. Dark mode toggles and persists (stored in localStorage).

9. Share URL: copy URL after an analysis, open in incognito, same graph loads.

---

## Constraints

- Demos are static JSON in Vercel — no backend dependency for the demo path.
- Error messages are user-friendly, never raw stack traces.
- No telemetry / analytics at this phase. Privacy-respecting by default.
- localStorage only for: dark-mode preference, previously-viewed analyses (list of recent repos for convenience).

## Time budget

3 hours.
