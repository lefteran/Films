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
| **Single source of truth** | [`data/movies_lite.json`](../data/movies_lite.json) plus [`data/synopses.json`](../data/synopses.json) form the canonical database. The catalogue is loaded eagerly; synopses are lazy-loaded on demand. Writes go through the GitHub Contents API. |
| **Private source data** | [`data/all_movies.xlsx`](../data/all_movies.xlsx) is local-only and gitignored. It is an input to Phase 1, not part of the deployed app. |
| **Zero infrastructure** | GitHub Pages hosts the frontend and GitHub hosts the data. TMDB supplies metadata and images. |
| **Idempotent ingestion** | Re-running the migration script must produce the same JSON for the same workbook and TMDB responses, without creating duplicate records. |
| **No build step** | The deployed files are the authored files. No bundler, transpiler, or server-side rendering. |

---

## 2. High-Level Data Flow

```text
┌─────────────────────────┐
│ data/all_movies.xlsx    │  private, local workbook
│ color-coded workbook    │
└────────────┬────────────┘
             │  PHASE 1 — offline, run manually
             ▼
┌──────────────────────────────────────────────────────────────┐
│ scripts/excel_to_tmdb.py                                     │
│  • openpyxl: read cells, fill colours, hyperlinks            │
│  • colour → tag mapping                                      │
│  • IMDb ID extraction (tt\d{7,8})                            │
│  • TMDB API: metadata, synopsis, runtime, poster             │
│  • normalise + deduplicate + split into minified files       │
└──────┬────────────────────────────────────────┬──────────────┘
       ▼                                        ▼
┌─────────────────────────┐      ┌──────────────────────────┐
│ data/movies_lite.json   │      │ data/synopses.json       │
│ array without synopsis  │      │ { shelf_id: synopsis }   │
│ minified                │      │ minified                 │
└────────────┬────────────┘      └────────────▲─────────────┘
             │  PHASE 2 — eager load            │ lazy load on first modal
             ▼                                  │
┌───────────────────────────────────────────────┴──────────────┐
│ Static frontend (GitHub Pages)                               │
│  index.html  +  src/css/  +  src/js/                         │
│  fetch('data/movies_lite.json') → grid → search → filters    │
│  openModal() → fetch('data/synopses.json') once              │
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

Convert the personal Excel catalogue into two flat, minified JSON files enriched with TMDB metadata
and poster URLs: `movies_lite.json` for grid data and `synopses.json` for on-demand text. The
migration is an **offline, one-off (or on-demand) operation**, never part of the request path.

### 3.2 Current implementation status

The migration implementation lives at [`scripts/excel_to_tmdb.py`](../scripts/excel_to_tmdb.py). It
currently:

* loads [`data/all_movies.xlsx`](../data/all_movies.xlsx) with
  `openpyxl.load_workbook(..., data_only=True)`;
* selects the `Alphanumeric` worksheet;
* reads `shelf_id`, title, director, actors, and year;
* extracts the title cell's fill colour and hyperlink;
* maps colours to tags;
* resolves a TMDB ID by IMDb ID first, then by title + year as a fallback;
* fetches full TMDB details with `append_to_response=credits` (localised title, overview, runtime,
  poster, cast);
* replaces abbreviated Excel actor names with the first four full names from `credits.cast`, falling
  back to the Excel string only when the cast list is empty;
* translates a missing Greek overview from an `en-US` request via
  `GoogleTranslator(source="en", target="el")`, with a 0.5 s pause;
* writes two minified UTF-8 files: `data/movies_lite.json` and `data/synopses.json`;
* sleeps 200 ms between TMDB calls (plus 500 ms after each translation attempt).

The exporter is being hardened incrementally as described below.

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

`language=el-GR` is used so that `title` and `overview` are Greek localisations where available;
`runtime` populates `duration_minutes`.

The movie-details request adds `append_to_response=credits`. Actor names are taken from
`credits.cast[:4]` and joined with `", "`, because TMDB provides full names while the Excel sheet may
contain abbreviations such as "P. Richard". The Excel `actors` value is retained only when the
credits cast list is missing or empty.

When the Greek `overview` is empty, the script makes a second details request with
`language=en-US`. If an English overview exists,
`deep_translator.GoogleTranslator(source="en", target="el")` translates it and the result is stored
in `synopses.json`; a 0.5 s sleep follows each translation attempt. If translation fails, the English
text is kept as a fallback.

Poster URL construction:

```text
https://image.tmdb.org/t/p/w500{poster_path}
```

`w500` is chosen as a balance between visual quality and grid performance. The app may later request
a smaller size (`w342`) for thumbnails and use `w500` in a detail view.

### 3.6 Output files and schema

Phase 1 emits **two minified JSON files**. Both use `json.dump(..., ensure_ascii=False,
separators=(',', ':'))`, so there is no indentation or insignificant whitespace.

#### `data/movies_lite.json` — catalogue array

Each movie object contains everything needed to render the grid and the modal header, but **no
`synopsis` key**:

```json
[{"shelf_id":"A1","original_title":"The Example Movie","director":"Jane Doe","actors":"John Smith, Anna Lee","year":1999,"tags":["HD","Official GR Subs"],"imdb_id":"tt0123456","tmdb_id":12345,"greek_title":"Η Παράδειγμα Ταινία","duration_minutes":98,"poster_url":"https://image.tmdb.org/t/p/w500/example.jpg"}]
```

| Field | Type | Source | Notes |
| --- | --- | --- | --- |
| `shelf_id` | string / number | Excel A | Preserve as-is; avoid numeric coercion that drops leading zeros. Also the key into `synopses.json`. |
| `original_title` | string | Excel C | Always present (empty rows skipped). |
| `director` | string \| null | Excel D | |
| `actors` | string \| null | TMDB `credits.cast[:4]`, fallback Excel E | Full TMDB names joined with commas; Excel only when cast is empty. |
| `year` | number \| null | Excel F | |
| `tags` | string[] | Cell fill colour | Empty array when unmapped. |
| `imdb_id` | string \| null | Hyperlink regex | Matches `tt` + 7–8 digits. |
| `tmdb_id` | number \| null | TMDB | |
| `greek_title` | string \| null | TMDB `title` | Greek localisation when available. |
| `duration_minutes` | number \| null | TMDB `runtime` | |
| `poster_url` | string \| null | TMDB `poster_path` | `null` when no poster exists. |

#### `data/synopses.json` — `shelf_id` → synopsis map

A single JSON object whose keys are movie `shelf_id` values and whose values are the Greek TMDB
`overview` text (or the machine-translated English fallback):

```json
{"A1":"Σύνοψη της ταινίας...","B4":"..."}
```

`shelf_id` is treated as unique. If the workbook repeats a shelf ID, the later synopsis replaces the
earlier one and the migration logs a warning. Films without a synopsis are stored with an empty
string so lookups remain predictable. Keeping synopses out of the initial catalogue removes the
largest text field from the first download; the browser fetches this file only when a modal is first
opened.

In the initial split of the existing 3.45 MB `movies.json`, `movies_lite.json` is about 1.13 MB and
`synopses.json` is about 1.75 MB, so the first page load no longer downloads the synopsis corpus.
The current export contains 24 duplicate `shelf_id` values (3,279 films, 3,255 unique IDs), which is
a known data-quality limitation of the `shelf_id` key.

`data/movies.json` is no longer written by the current script; it is superseded by the two files
above.

### 3.7 Hardening requirements for the production script

* Read `TMDB_API_KEY` from the environment (`.env` locally), never hardcode it.
* Handle HTTP 429 / 5xx with bounded exponential backoff and respect `Retry-After`.
* Normalise ARGB values (uppercase, pad to 8 characters, tolerate `FFFFFFFF` / `00000000`).
* Deduplicate by `tmdb_id`, then `imdb_id`, then normalised title + year.
* Write both output files from the same in-memory pass so the catalogue and synopsis map stay
  consistent.
* Log progress and write a summary (processed, matched, unmatched, skipped).
* Keep the script importable and side-effect free at module level for testability.
* Never crash the whole run because one row has malformed data.

### 3.8 Incremental patching (`scripts/patch_existing_json.py`)

Re-running the full migration is unnecessary for targeted corrections. The incremental patcher loads
the existing JSON files and updates only records that need attention:

1. Load `data/movies_lite.json` and `data/synopses.json`.
2. Flag a movie when its `shelf_id` is absent from `synopses.json`, its synopsis is empty or
   whitespace, or its non-null `actors` string contains a period (`.`) — the signal for abbreviated
   Excel names such as `P. Richard`.
3. For flagged movies with a valid `tmdb_id`, call
   `GET /3/movie/{tmdb_id}?append_to_response=credits&language=el-GR` using `TMDB_API_KEY` loaded
   from `.env`.
4. Replace `actors` with the first four full names from `credits.cast` when available.
5. When the existing synopsis is missing/empty, use the Greek `overview`. If it is empty, request
   `language=en-US`, translate the English overview with
   `GoogleTranslator(source="en", target="el")`, and sleep 0.5 s.
6. Rewrite both files with UTF-8 and `json.dump(..., separators=(",", ":"))` (no indentation).

The script logs the number of flagged movies, each movie being patched together with its reasons, and
a final count of actor and synopsis updates. Movies without a `tmdb_id` are skipped with a warning.
Existing non-empty synopses are preserved when a movie is patched only for abbreviated actors.

---

## 4. Phase 2 — Frontend Application

### 4.1 Purpose

A fast, client-side-only catalogue that loads `data/movies_lite.json` and renders a responsive movie
grid with instant search and tag filters. Synopsis text is loaded lazily from `data/synopses.json`
the first time a movie modal is opened. Hosted on GitHub Pages.

### 4.2 Hosting and URL layout

GitHub Pages serves static files; it has **no server-side rewrites**. Serving from the repository
root (branch `main`, folder `/`) gives clean URLs:

| URL | File | Purpose |
| --- | --- | --- |
| `/` | `index.html` (thin shell at repo root) | Main library application. |
| `/add/` | `add/index.html` | Hidden add-movie route (Phase 3). GitHub Pages serves `/add` with a redirect to `/add/`. |
| `/data/movies_lite.json` | `data/movies_lite.json` | Catalogue array (no synopses), loaded on page start. |
| `/data/synopses.json` | `data/synopses.json` | Lazy-loaded `shelf_id` → synopsis map for modals. |
| `/src/...` | CSS / JS | Application assets referenced by the root shell. |

The root `index.html` is intentionally thin: it contains the mount points and loads
`src/css/styles.css` and `src/js/app.js`, keeping actual frontend source in `src/`.

Paths inside `add/` must be resolved relative to the document, e.g.
`new URL('../data/movies_lite.json', window.location.href)`.

### 4.3 Runtime components

| File (planned) | Responsibility |
| --- | --- |
| `index.html` | Semantic shell: header with search and grid-size toggle, tag filters, grid container, status/empty states. |
| `src/css/styles.css` | Responsive normal/small grid densities, card layout, tag chips, modal scroll area, focus styles, dark/light-friendly colours. |
| `src/js/data.js` | Fetch + validate `movies_lite.json`; in-memory cache; optional localStorage cache with version key. |
| `src/js/filters.js` | Normalise text, tokenise search, apply tag and text predicates. |
| `src/js/render.js` | Build cards with `DocumentFragment`; lazy-load posters; fallback poster. |
| `src/js/app.js` | Bootstrap, event wiring, grid-size toggle, URL state, debounced search, result counts, lazy synopsis loading. |

### 4.4 Data flow

```text
page load
  → fetch('data/movies_lite.json')
  → parse + validate array
  → state = { movies, query: '', activeTags: Set, sort: 'title' }
  → derive filteredMovies = movies.filter(matchesQuery && matchesTags)
  → sort
  → render(filteredMovies) into grid
  → user opens a movie modal
      → if synopsesData === null: fetch('data/synopses.json') once
      → display synopsesData[movie.shelf_id] in .modal-synopsis
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
* **Grid density:** a header button toggles `.small-grid` on `#moviesGrid`, switching from
  `minmax(200px, 1fr)` to `minmax(130px, 1fr)` columns with proportionally smaller titles, metadata,
  badges, and tags. `aria-pressed` reflects the active state.
* **Modal layout:** the poster is top-aligned in the flex row and never stretches; `.modal-details`
  scrolls independently at `max-height: 70vh` (55vh on mobile) so long synopses stay inside the modal.
* **Card content:** poster, title (Greek title preferred with original fallback), year, director,
  tags, shelf ID.
* **Empty state:** explicit message plus a “clear filters” action.
* **Result count:** live count, e.g. “123 of 480 films”.
* **URL state (planned):** query and tags mirrored to `?q=&tags=` so filtered views are linkable;
  read on load and updated with `history.replaceState`.
* **Accessibility:** keyboard-operable filters, visible focus rings, `alt` text, `aria-pressed` on
  toggles, sufficient contrast.
* **Performance:** `loading="lazy"` and `decoding="async"` on posters; one initial JSON request (the
  synopsis file is deferred until the first modal open); no runtime dependencies; render via
  `DocumentFragment`.

### 4.6 Failure handling

* Fetch failure → visible error state with a retry button.
* Invalid JSON or non-array payload → error state; log to console.
* Synopses fetch failure → the modal shows a load error and the next modal open retries.
* Missing `poster_url` → local placeholder graphic, unchanged card dimensions.
* GitHub Pages propagation delay after a Phase 3 commit → cache-busted refetch and user messaging.

---

## 5. Phase 3 — Serverless Movie Addition

### 5.1 Purpose

Allow adding a film from the browser without any backend by:

1. searching TMDB for the film;
2. constructing a catalogue entry (without synopsis) and its synopsis text;
3. reading `data/movies_lite.json` and `data/synopses.json` through the GitHub Contents API;
4. appending both and committing the updated files with a Personal Access Token (PAT).

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
4. Client builds:
     - lite entry (no synopsis):
         { shelf_id, original_title, director, actors, year, tags,
           imdb_id, tmdb_id, greek_title, duration_minutes, poster_url }
     - synopsis text for synopses.json
   - tags / shelf_id entered manually in the form (Excel colours are unavailable here)
   - IMDb ID can come from TMDB external IDs or user input
5. GET /repos/{owner}/{repo}/contents/data/movies_lite.json
   GET /repos/{owner}/{repo}/contents/data/synopses.json
     Accept: application/vnd.github+json
     Authorization: Bearer <PAT>
   → each response includes base64 `content` and `sha`
6. Decode base64 (UTF-8 safe) → JSON.parse for both files
7. Duplicate check by tmdb_id / imdb_id → abort with a clear message if found
8. Append the entry to the lite array; set synopses[shelf_id] = synopsis
   → JSON.stringify(...) without spacing → base64 encode both files
9. PUT both files to their Contents API paths with their own `sha` and `branch`
10. On 409/422 sha conflict: refetch the affected file, re-apply, retry (max 3)
11. On success: show commit URLs and refetch the library with cache-busting
```

### 5.5 Repository configuration

The add page needs the repository owner, name, and branch. These are non-secret constants in a small
`src/js/config.js` (or derived from `window.location` when hosted at
`https://<owner>.github.io/<repo>/`). Keeping them explicit avoids ambiguity when the site is served
from a custom domain.

### 5.6 Concurrency and consistency

The Contents API is not a transactional database. Two concurrent additions can race; each file's
`sha` precondition makes a conflicting write fail rather than silently overwrite. The retry loop
re-reads the affected latest file, re-applies the change, and retries. Duplicate checks are repeated
after each refetch. Because the two files are committed separately, a partial write is possible
(catalogue updated, synopsis write failed); the UI reports which file needs retrying and re-runs only
the failed PUT.

### 5.7 Post-commit propagation

A commit does not update GitHub Pages instantly. After a successful PUT:

1. poll the Contents API (or use the returned commit SHAs) until both remote blobs reflect the new
   content;
2. fetch `data/movies_lite.json?v=<commit-sha>` and `data/synopses.json?v=<commit-sha>` to bypass
   caches;
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
| Metadata | **TMDB API** | Good coverage, localised Greek titles/synopses, full cast credits, reliable poster CDN, generous free tier. | OMDb (weaker images), IMDb scraping (fragile, ToS issues). |
| Translation | **`deep-translator` (`GoogleTranslator`)** | Free fallback when TMDB has no Greek overview; runs only during the Phase 1 migration. | Manual translation; English-only synopsis; paid translation APIs. |
| Database | **Two flat minified JSON files (`movies_lite.json` + `synopses.json`) committed to the repo** | Smaller initial payload because synopses are deferred, still readable and diffable, no DB hosting. | Single `movies.json` (large initial download), SQLite/WASM (overkill), Firebase/Supabase (backend dependency). |
| Frontend | **Vanilla HTML/CSS/JS** | Tiny dataset and simple interactions; no build step; fast first load; easy to audit. | React/Vue (unnecessary weight), Astro (build step). |
| Hosting | **GitHub Pages** | Free, HTTPS, same origin as the repository and API workflow, zero config for static files. | Netlify/Cloudflare Pages (extra account), S3 (cost/config). |
| Writes | **GitHub Contents API + fine-grained PAT** | True serverless writes, versioned history, no secret on a server. | Serverless function with token (defeats “no backend”), GitHub Actions (see 5.9). |
| Images | **TMDB image CDN (`image.tmdb.org`)** | No image hosting or storage cost; responsive sizes available. | Repo-stored images (repo bloat), third-party image host. |

---

## 7. Repository Structure

```text
Films/
├── .gitignore
├── requirements.txt             # Python dependencies
├── docs/
│   ├── architecture.md          # this document
│   └── TODO.md                  # phased implementation checklist
├── scripts/
│   ├── excel_to_tmdb.py         # Phase 1 full migration script
│   └── patch_existing_json.py   # targeted incremental patcher
├── src/
│   ├── css/                     # frontend styles
│   └── js/                      # frontend logic
├── data/
│   ├── all_movies.xlsx          # private source workbook (local)
│   ├── movies_lite.json         # generated catalogue, minified (committed)
│   ├── synopses.json            # generated synopsis map, minified (committed)
│   └── movies.json              # legacy combined export (superseded)
├── add/                         # Phase 3 hidden add page (planned)
├── index.html                   # Phase 2 app shell
└── .films/                      # Python virtual environment (gitignored)
```

---

## 8. Development Environment

* Windows 11, default shell `cmd.exe`.
* Python virtual environment: `.films/` at the repository root, gitignored.
  * Activate: `.films\Scripts\activate`
* Phase 1 dependencies in [`requirements.txt`](../requirements.txt): `openpyxl`, `requests`,
  `python-dotenv`, `deep-translator`.
* Install with `.films\Scripts\pip.exe install -r requirements.txt` (see
  [`commands.md`](commands.md)).
* Run incremental repairs with `.films\Scripts\python.exe scripts\patch_existing_json.py`.
* Environment variables: `TMDB_API_KEY` for Phase 1. The browser app never needs the TMDB key for
  Phase 2; Phase 3 calls TMDB from the browser, which requires a client-visible key — document the
  acceptable use and consider restricting the key.

---

## 9. Security and Privacy Summary

* Private Excel workbooks stay out of version control; ensure `.gitignore` covers the exact source
  filename (`data/all_movies.xlsx` is the current input to the migration script).
* The TMDB API key must not be committed; use `.env` (also gitignored).
* The translation fallback sends English synopsis text to Google Translate through `deep-translator`;
  it runs only during the Phase 1 export and only when TMDB lacks a Greek overview.
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
| **1** | Migration tool + `data/movies_lite.json` + `data/synopses.json` | Running the script on the real workbook produces valid, deduplicated, minified catalogue and synopsis files; unmatched films are reported. |
| **2** | Static library on GitHub Pages | The grid loads, search and tag filters update instantly, synopses lazy-load on first modal open, and the site works on mobile. |
| **3** | Hidden `/add/` page | A new film can be searched on TMDB and committed to both JSON files from the browser without a backend. |

See [`TODO.md`](TODO.md) for the actionable checklist.
