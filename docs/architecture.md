# Films — Architecture

**Films** is a serverless, static personal movie library. It turns a private, color-coded Excel
workbook into a public, version-controlled JSON catalogue, serves that catalogue as a fast
client-side web application on GitHub Pages, and allows new films to be added directly from the
browser through the GitHub API — with no backend server, database, or hosting cost.

---

## 1. Design Principles

| Principle | Decision |
| --- | --- |
| **Static-first** | The runtime is plain HTML/CSS/JavaScript. There is no application server. |
| **Single source of truth** | [`data/movies.json`](../data/movies.json) is the canonical database. Every client reads it; writes go through the GitHub Contents API. |
| **Private source data** | [`data/movies.xlsx`](../data/movies.xlsx) is local-only and gitignored. It is an input to Phase 1, not part of the deployed app. |
| **Zero infrastructure** | GitHub Pages hosts the frontend and GitHub hosts the data. TMDB supplies metadata and images. |
| **Idempotent ingestion** | Re-running the migration script must produce the same JSON for the same workbook and TMDB responses, without creating duplicate records. |
| **No build step** | The deployed files are the authored files. No bundler, transpiler, or server-side rendering. |

---

## 2. High-Level Data Flow

```text
┌─────────────────────────┐
│ data/movies.xlsx        │  private, gitignored
│ color-coded workbook    │
└────────────┬────────────┘
             │  PHASE 1 — offline, run manually
             ▼
┌──────────────────────────────────────────────────────────────┐
│ scripts/excel_to_tmdb.py                                     │
│  • openpyxl: read cells, fill colours, hyperlinks            │
│  • colour → tag mapping                                      │
│  • IMDb ID extraction (tt\d{7,8})                            │
│  • TMDB API: metadata, synopsis, poster                      │
│  • normalise + deduplicate + write JSON                      │
└────────────┬─────────────────────────────────────────────────┘
             ▼
┌─────────────────────────┐
│ data/movies.json        │  committed, public, served by Pages
└────────────┬────────────┘
             │  PHASE 2 — browser runtime
             ▼
┌──────────────────────────────────────────────────────────────┐
│ Static frontend (GitHub Pages)                               │
│  index.html  +  src/css/  +  src/js/                         │
│  fetch('data/movies.json') → grid → search → tag filters     │
└────────────┬─────────────────────────────────────────────────┘
             │  PHASE 3 — browser runtime, authenticated writes
             ▼
┌──────────────────────────────────────────────────────────────┐
│ Hidden /add page                                             │
│  TMDB search ──────────────► api.themoviedb.org              │
│  read/modify/commit ───────► api.github.com Contents API      │
│                              (fine-grained PAT, contents:write)│
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Phase 1 — Data Migration

### 3.1 Purpose

Convert the personal Excel catalogue into a flat JSON database enriched with TMDB metadata and
poster URLs. The migration is an **offline, one-off (or on-demand) operation**, never part of the
request path.

### 3.2 Current implementation status

A working prototype exists at [`excel_to_tmdb.py`](../excel_to_tmdb.py). It already implements the
core pipeline:

* loads the workbook with `openpyxl.load_workbook(..., data_only=True)`;
* reads rows from the active sheet;
* extracts the title cell's fill colour and hyperlink;
* maps colours to tags;
* fetches TMDB data by IMDb ID first, then by title + year as a fallback;
* writes UTF-8 JSON with 4-space indentation;
* sleeps 200 ms between TMDB calls.

The production version will move to `scripts/` and be hardened as described below.

### 3.3 Workbook layout assumed by the prototype

| Column index | Field | Notes |
| --- | --- | --- |
| `A` (`row[0]`) | `shelf_id` | Physical shelf / location identifier. |
| `C` (`row[2]`) | title | Cell value is the original title; cell fill is the tag source; the cell hyperlink usually contains an IMDb URL. |
| `D` (`row[3]`) | `director` | Free text. |
| `E` (`row[4]`) | `actors` | Free text. |
| `F` (`row[5]`) | `year` | Release year. |

Rows without a title are skipped.

### 3.4 Colour → tag mapping

Excel stores fill colours as 8-character ARGB hex strings (e.g. `FFCCFFCC`). The prototype uses a
static dictionary:

| ARGB | Tag |
| --- | --- |
| `FFCCFFCC` | `Official GR Subs` |
| `FF9CC2E5` | `Greek Movie` |
| `FFFABF8F` | `Custom GR Subs` |
| `FFCC0069` | `HDD Only` |
| `FFDA9694` | `VHS Rip` |
| `FF00B0F0` | `HD` |
| `FFFFFF00` | `EN Subs Only` |

Unmapped or theme/indexed colours produce an empty tag list. The mapping must stay synchronised with
the workbook and be documented here whenever it changes.

### 3.5 TMDB enrichment

Request strategy, in priority order:

1. **IMDb lookup (preferred):**
   `GET https://api.themoviedb.org/3/find/{imdb_id}?external_source=imdb_id&language=el-GR`
   → first item in `movie_results`.
2. **Title + year search fallback:**
   `GET https://api.themoviedb.org/3/search/movie?query={title}&language=el-GR&primary_release_year={year}`
   → first item in `results`.

`language=el-GR` is used so that `title` and `overview` are Greek localisations where available.

Poster URL construction:

```text
https://image.tmdb.org/t/p/w500{poster_path}
```

`w500` is chosen as a balance between visual quality and grid performance. The app may later request
a smaller size (`w342`) for thumbnails and use `w500` in a detail view.

### 3.6 Output schema (`data/movies.json`)

The file is a JSON **array** of movie objects:

```json
[
  {
    "shelf_id": "A1",
    "original_title": "The Example Movie",
    "director": "Jane Doe",
    "actors": "John Smith, Anna Lee",
    "year": 1999,
    "tags": ["HD", "Official GR Subs"],
    "imdb_id": "tt0123456",
    "tmdb_id": 12345,
    "greek_title": "Η Παράδειγμα Ταινία",
    "synopsis": "Σύνοψη της ταινίας...",
    "poster_url": "https://image.tmdb.org/t/p/w500/example.jpg"
  }
]
```

| Field | Type | Source | Notes |
| --- | --- | --- | --- |
| `shelf_id` | string / number | Excel A | Preserve as-is; avoid numeric coercion that drops leading zeros. |
| `original_title` | string | Excel C | Always present (empty rows skipped). |
| `director` | string \| null | Excel D | |
| `actors` | string \| null | Excel E | |
| `year` | number \| null | Excel F | |
| `tags` | string[] | Cell fill colour | Empty array when unmapped. |
| `imdb_id` | string \| null | Hyperlink regex | Matches `tt` + 7–8 digits. |
| `tmdb_id` | number \| null | TMDB | |
| `greek_title` | string \| null | TMDB `title` | Greek localisation when available. |
| `synopsis` | string | TMDB `overview` | Empty string when unavailable. |
| `poster_url` | string \| null | TMDB `poster_path` | `null` when no poster exists. |

### 3.7 Hardening requirements for the production script

* Read `TMDB_API_KEY` from the environment (`.env` locally), never hardcode it.
* Handle HTTP 429 / 5xx with bounded exponential backoff and respect `Retry-After`.
* Normalise ARGB values (uppercase, pad to 8 characters, tolerate `FFFFFFFF` / `00000000`).
* Deduplicate by `tmdb_id`, then `imdb_id`, then normalised title + year.
* Log progress and write a summary (processed, matched, unmatched, skipped).
* Keep the script importable and side-effect free at module level for testability.
* Never crash the whole run because one row has malformed data.

---

## 4. Phase 2 — Frontend Application

### 4.1 Purpose

A fast, client-side-only catalogue that loads `data/movies.json` and renders a responsive movie
grid with instant search and tag filters. Hosted on GitHub Pages.

### 4.2 Hosting and URL layout

GitHub Pages serves static files; it has **no server-side rewrites**. Serving from the repository
root (branch `main`, folder `/`) gives clean URLs:

| URL | File | Purpose |
| --- | --- | --- |
| `/` | `index.html` (thin shell at repo root) | Main library application. |
| `/add/` | `add/index.html` | Hidden add-movie route (Phase 3). GitHub Pages serves `/add` with a redirect to `/add/`. |
| `/data/movies.json` | `data/movies.json` | Canonical dataset. |
| `/src/...` | CSS / JS | Application assets referenced by the root shell. |

The root `index.html` is intentionally thin: it contains the mount points and loads
`src/css/styles.css` and `src/js/app.js`, keeping actual frontend source in `src/`.

Paths inside `add/` must be resolved relative to the document, e.g.
`new URL('../data/movies.json', window.location.href)`.

### 4.3 Runtime components

| File (planned) | Responsibility |
| --- | --- |
| `index.html` | Semantic shell: header, search input, tag filters, grid container, status/empty states. |
| `src/css/styles.css` | Responsive grid, card layout, tag chips, focus styles, dark/light-friendly colours. |
| `src/js/data.js` | Fetch + validate `movies.json`; in-memory cache; optional localStorage cache with version key. |
| `src/js/filters.js` | Normalise text, tokenise search, apply tag and text predicates. |
| `src/js/render.js` | Build cards with `DocumentFragment`; lazy-load posters; fallback poster. |
| `src/js/app.js` | Bootstrap, event wiring, URL state, debounced search, result counts. |

### 4.4 Data flow

```text
page load
  → fetch('data/movies.json')
  → parse + validate array
  → state = { movies, query: '', activeTags: Set, sort: 'title' }
  → derive filteredMovies = movies.filter(matchesQuery && matchesTags)
  → sort
  → render(filteredMovies) into grid
  → user input (debounced 150 ms) / tag toggle / sort change
  → update state → re-derive → re-render
```

Single source of state is kept in `app.js`; rendering is a pure function of that state. No
framework is required because the dataset is small (hundreds to low thousands of rows) and the UI has
few interactions.

### 4.5 Behaviour specification

* **Search:** case-insensitive, accent-insensitive substring matching across `original_title`,
  `greek_title`, `director`, and `actors`. Multiple whitespace-separated tokens must all match
  (AND semantics).
* **Tag filters:** multi-select chips. Selecting several tags narrows results (AND semantics), which
  matches the physical meaning of a film having multiple attributes.
* **Sorting:** title (A–Z), year (newest/oldest), shelf ID.
* **Card content:** poster, title (Greek title preferred with original fallback), year, director,
  tags, shelf ID.
* **Empty state:** explicit message plus a “clear filters” action.
* **Result count:** live count, e.g. “123 of 480 films”.
* **URL state (planned):** query and tags mirrored to `?q=&tags=` so filtered views are linkable;
  read on load and updated with `history.replaceState`.
* **Accessibility:** keyboard-operable filters, visible focus rings, `alt` text, `aria-pressed` on
  toggles, sufficient contrast.
* **Performance:** `loading="lazy"` and `decoding="async"` on posters; a single JSON request; no
  runtime dependencies; render via `DocumentFragment`.

### 4.6 Failure handling

* Fetch failure → visible error state with a retry button.
* Invalid JSON or non-array payload → error state; log to console.
* Missing `poster_url` → local placeholder graphic, unchanged card dimensions.
* GitHub Pages propagation delay after a Phase 3 commit → cache-busted refetch and user messaging.

---

## 5. Phase 3 — Serverless Movie Addition

### 5.1 Purpose

Allow adding a film from the browser without any backend by:

1. searching TMDB for the film;
2. constructing an entry that matches the Phase 1 schema;
3. reading `data/movies.json` through the GitHub Contents API;
4. appending the entry and committing the updated file with a Personal Access Token (PAT).

### 5.2 Hidden route

`/add/` is a real static page (`add/index.html`) and is not linked from the public UI. Because
GitHub Pages cannot rewrite `/add` to an SPA shell, a physical page is simpler and more reliable
than hash-routing tricks or a custom `404.html` redirect.

### 5.3 Authentication model

* The user pastes a **fine-grained GitHub PAT** into the add page.
* Token permissions: **Contents: Read and write**, limited to the single Films repository.
* The token is kept in `sessionStorage` only, so it disappears when the tab closes. A “Forget token”
  button clears it immediately.
* The token is never committed, logged, or sent anywhere except `api.github.com`.
* This is acceptable for a personal, single-user tool on a public static site, but it is **not** a
  multi-user auth system: any XSS on the origin could read the token. The app therefore ships no
  third-party scripts and avoids injecting untrusted HTML.

### 5.4 Add flow

```text
1. User enters PAT (sessionStorage).
2. User searches TMDB: GET /3/search/movie?query=...&language=el-GR
3. User selects a result.
4. Client builds entry:
     { shelf_id, original_title, director, actors, year, tags,
       imdb_id, tmdb_id, greek_title, synopsis, poster_url }
   - tags / shelf_id entered manually in the form (Excel colours are unavailable here)
   - IMDb ID can come from TMDB external IDs or user input
5. GET /repos/{owner}/{repo}/contents/data/movies.json
     Accept: application/vnd.github+json
     Authorization: Bearer <PAT>
   → response includes base64 `content` and `sha`
6. Decode base64 (UTF-8 safe) → JSON.parse
7. Duplicate check by tmdb_id / imdb_id → abort with a clear message if found
8. Append entry → JSON.stringify(..., null, 4) → base64 encode
9. PUT /repos/{owner}/{repo}/contents/data/movies.json
     body: { message, content, sha, branch }
10. On 409/422 sha conflict: refetch, re-apply append, retry (max 3)
11. On success: show commit URL and refetch the library with cache-busting
```

### 5.5 Repository configuration

The add page needs the repository owner, name, and branch. These are non-secret constants in a small
`src/js/config.js` (or derived from `window.location` when hosted at
`https://<owner>.github.io/<repo>/`). Keeping them explicit avoids ambiguity when the site is served
from a custom domain.

### 5.6 Concurrency and consistency

The Contents API is not a transactional database. Two concurrent additions can race; the `sha`
precondition makes the second write fail rather than silently overwrite. The retry loop re-reads the
latest file, re-appends the new entry, and retries. Duplicate checks are repeated after each refetch.

### 5.7 Post-commit propagation

A commit does not update GitHub Pages instantly. After a successful PUT:

1. poll the Contents API (or use the returned commit SHA) until the remote blob reflects the new
   content;
2. fetch `data/movies.json?v=<commit-sha>` to bypass caches;
3. if Pages has not deployed yet, show “Saved to GitHub — deployment may take a moment” and retry.

### 5.8 Failure modes

| Condition | Handling |
| --- | --- |
| Missing/invalid PAT (`401`) | Prompt to re-enter token; do not clear the form data. |
| Insufficient scope (`403`) | Explain the required fine-grained `Contents: Read and write` permission. |
| File not found (`404`) | Check owner/repo/branch configuration. |
| SHA conflict (`409` / `422`) | Refetch, re-apply, retry up to 3 times. |
| GitHub rate limit (`403` with rate-limit headers) | Show reset time; authenticated limit is 5,000 req/hour. |
| TMDB rate limit (`429`) | Backoff and retry; debounce searches. |
| Duplicate film | Abort before writing and highlight the existing entry. |
| Network failure | Keep user input; offer retry. |

### 5.9 Trade-off: why not GitHub Actions / Issues?

A GitHub Actions workflow triggered by an issue form would avoid holding a PAT in the browser and
would provide an audit trail. It was rejected for v1 because it adds latency, repository-specific
workflow maintenance, and a less fluid UX. The design keeps that option open: the add page can later
open a pre-filled issue instead of committing directly.

---

## 6. Technology Decisions

| Layer | Choice | Rationale | Alternatives considered |
| --- | --- | --- | --- |
| Ingestion | **Python + `openpyxl` + `requests`** | `openpyxl` exposes cell fills and hyperlinks; Python is ideal for a one-off data pipeline. | Node.js + `exceljs`; manual CSV export loses colours. |
| Metadata | **TMDB API** | Good coverage, localised Greek titles/synopses, reliable poster CDN, generous free tier. | OMDb (weaker images), IMDb scraping (fragile, ToS issues). |
| Database | **Flat `movies.json` committed to the repo** | Human-readable, diffable, trivially served, atomic enough at this scale, no DB hosting. | SQLite/WASM (overkill), Firebase/Supabase (backend dependency). |
| Frontend | **Vanilla HTML/CSS/JS** | Tiny dataset and simple interactions; no build step; fast first load; easy to audit. | React/Vue (unnecessary weight), Astro (build step). |
| Hosting | **GitHub Pages** | Free, HTTPS, same origin as the repository and API workflow, zero config for static files. | Netlify/Cloudflare Pages (extra account), S3 (cost/config). |
| Writes | **GitHub Contents API + fine-grained PAT** | True serverless writes, versioned history, no secret on a server. | Serverless function with token (defeats “no backend”), GitHub Actions (see 5.9). |
| Images | **TMDB image CDN (`image.tmdb.org`)** | No image hosting or storage cost; responsive sizes available. | Repo-stored images (repo bloat), third-party image host. |

---

## 7. Repository Structure

```text
Films/
├── .gitignore
├── docs/
│   ├── architecture.md          # this document
│   └── TODO.md                  # phased implementation checklist
├── scripts/
│   └── ...                      # Phase 1 Python migration scripts
├── src/
│   ├── css/                     # frontend styles (planned)
│   └── js/                      # frontend logic (planned)
├── data/
│   ├── movies.xlsx              # private source workbook (gitignored)
│   └── movies.json              # generated catalogue (committed)
├── add/                         # Phase 3 hidden add page (planned)
├── index.html                   # Phase 2 app shell (planned)
├── excel_to_tmdb.py             # Phase 1 prototype at repo root
└── .films/                      # Python virtual environment (gitignored)
```

---

## 8. Development Environment

* Windows 11, default shell `cmd.exe`.
* Python virtual environment: `.films/` at the repository root, gitignored.
  * Activate: `.films\Scripts\activate`
* Phase 1 dependencies (planned `scripts/requirements.txt`): `openpyxl`, `requests`,
  `python-dotenv`.
* Environment variables: `TMDB_API_KEY` for Phase 1. The browser app never needs the TMDB key for
  Phase 2; Phase 3 calls TMDB from the browser, which requires a client-visible key — document the
  acceptable use and consider restricting the key.

---

## 9. Security and Privacy Summary

* `data/movies.xlsx` stays out of version control via `.gitignore`.
* The TMDB API key must not be committed; use `.env` (also gitignored).
* The GitHub PAT is user-supplied at runtime, held only in `sessionStorage`, scoped to one repo, and
  never stored in the repository or sent to third parties.
* The app loads no third-party scripts, reducing XSS surface.
* All traffic uses HTTPS (GitHub Pages, TMDB, GitHub API).
* The published catalogue is public by design; private fields such as shelf locations are included
  intentionally.

---

## 10. Roadmap

| Phase | Deliverable | Definition of done |
| --- | --- | --- |
| **1** | Migration tool + `data/movies.json` | Running the script on the real workbook produces a valid, deduplicated JSON file; unmatched films are reported. |
| **2** | Static library on GitHub Pages | The grid loads, search and tag filters update instantly, and the site works on mobile. |
| **3** | Hidden `/add/` page | A new film can be searched on TMDB and committed to `movies.json` from the browser without a backend. |

See [`TODO.md`](TODO.md) for the actionable checklist.
