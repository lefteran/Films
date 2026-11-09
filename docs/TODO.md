# Films — TODO

Actionable checklist for the three-phase build. Items are ordered so that each phase unblocks the
next. Update this file as work lands; see [`architecture.md`](architecture.md) for design details.

---

## Phase 0 — Project Foundations

- [x] Create `docs/` documentation folder
- [x] Write [`architecture.md`](architecture.md) covering the 3-phase design
- [x] Write this `TODO.md` checklist
- [x] Create `scripts/`, `src/`, and `data/` directories
- [x] Add `.gitignore` for `.films/`, `__pycache__/`, and `data/movies.xlsx`
- [ ] Create/verify the `.films/` virtual environment
- [ ] Add `scripts/requirements.txt` (`openpyxl`, `requests`, `python-dotenv`)
- [ ] Add `.env.example` with `TMDB_API_KEY=`
- [ ] Add a root `README.md` (project summary, setup, run commands)
- [ ] Initialize the Git repository (`git init`) and confirm the remote/default branch (`main`)
- [ ] Decide and add a license

---

## Phase 1 — Data Migration (Python)

### Script setup
- [x] Prototype ingestion script exists at [`excel_to_tmdb.py`](../excel_to_tmdb.py)
- [ ] Move/refactor the prototype into `scripts/excel_to_tmdb.py`
- [ ] Load `TMDB_API_KEY` from the environment instead of hardcoding it
- [ ] Make paths configurable via CLI arguments (`--input`, `--output`)
- [ ] Keep module import side-effect free; expose a `main()` entry point

### Workbook parsing
- [ ] Inspect the real `data/movies.xlsx` and confirm columns, header row, and sheet name
- [ ] Read `shelf_id` (column A) without dropping leading zeros
- [ ] Read title (column C), director (D), actors (E), year (F)
- [ ] Skip empty/header rows reliably
- [ ] Extract hyperlink and parse IMDb ID with `tt\d{7,8}`
- [ ] Read cell fill colour robustly (ARGB normalisation; handle theme/indexed and `FFFFFFFF`/`00000000`)
- [ ] Finalise the colour → tag mapping and update the table in [`architecture.md`](architecture.md)
- [ ] Support multiple tags per colour if the workbook requires it

### TMDB enrichment
- [ ] Implement IMDb lookup via `/3/find/{imdb_id}` (`external_source=imdb_id`, `language=el-GR`)
- [ ] Implement fallback search via `/3/search/movie` with title + `primary_release_year`
- [ ] Request and store `greek_title`, `synopsis`, and `poster_path`
- [ ] Build `poster_url` at `w500`
- [ ] Add retry with backoff for `429`/`5xx` and honour `Retry-After`
- [ ] Add a request timeout and clear error handling
- [ ] Respect TMDB rate limits (keep the inter-request delay)
- [ ] Cache TMDB responses locally during development to avoid re-fetching

### Output quality
- [ ] Define and validate the JSON schema from [`architecture.md`](architecture.md) §3.6
- [ ] Deduplicate by `tmdb_id`, then `imdb_id`, then normalised title + year
- [ ] Handle films not found on TMDB without aborting the run
- [ ] Log a summary: processed, matched, unmatched, skipped, duplicates
- [ ] Write `data/movies.json` as UTF-8 with predictable formatting
- [ ] Add a small test workbook fixture and unit tests for colour mapping and IMDb parsing
- [ ] Run a full migration against the real workbook
- [ ] Manually spot-check 10–20 entries (posters, titles, tags, shelf IDs)
- [ ] Commit the generated `data/movies.json`

---

## Phase 2 — Frontend Application (Vanilla JS on GitHub Pages)

### Structure and data loading
- [ ] Create the root `index.html` app shell
- [ ] Create `src/css/styles.css`
- [ ] Create `src/js/app.js` (bootstrap and state)
- [ ] Create `src/js/data.js` (fetch + validation)
- [ ] Create `src/js/filters.js` (search + tag predicates)
- [ ] Create `src/js/render.js` (card rendering)
- [ ] Fetch `data/movies.json` relative to the page
- [ ] Show loading, error, and retry states
- [ ] Validate that the payload is a JSON array

### UI and behaviour
- [ ] Responsive movie grid (auto-fill cards)
- [ ] Movie cards: poster, title, year, director, tags, shelf ID
- [ ] Poster placeholder for missing/failed images
- [ ] Instant search with 150 ms debounce across title/director/actors
- [ ] Accent-insensitive, multi-token AND search
- [ ] Tag filter chips with multi-select AND semantics
- [ ] Sort controls: title, year (newest/oldest), shelf
- [ ] Live result count (“X of Y films”)
- [ ] Empty state with “clear filters”
- [ ] Keyboard accessibility, visible focus, `aria-pressed` toggles, `alt` text
- [ ] Mirror query/tags to URL (`?q=`, `?tags=`) with `history.replaceState`
- [ ] Lazy-load posters (`loading="lazy"`, `decoding="async"`)

### Hosting and verification
- [ ] Configure GitHub Pages to serve from `main` / root
- [ ] Verify `/`, `/add/`, and `/data/movies.json` resolve correctly
- [ ] Cache-busting strategy for updated JSON (e.g. `?v=`)
- [ ] Test on mobile viewport and a narrow desktop window
- [ ] Test with missing posters and an empty filter result
- [ ] Document the deployment steps in [`architecture.md`](architecture.md)

---

## Phase 3 — Serverless Movie Addition

### Hidden add page
- [ ] Create `add/index.html` (not linked from the public UI)
- [ ] Reuse `src/` styles and modules where practical
- [ ] Resolve data paths relative to the page (`../data/movies.json`)
- [ ] Add `src/js/config.js` with repo owner, name, and branch

### Authentication
- [ ] PAT input form with clear scope instructions
- [ ] Persist the token in `sessionStorage` only
- [ ] “Forget token” button
- [ ] Never log or display the token after entry

### TMDB search and entry form
- [ ] Search input calling `/3/search/movie?language=el-GR`
- [ ] Debounce searches and show loading/empty/error states
- [ ] Display result list with poster, title, year, overview
- [ ] Select a result and preview it
- [ ] Fetch external IDs to populate `imdb_id` when available
- [ ] Manual fields: `shelf_id`, tags, director, actors, year
- [ ] Build an entry matching the Phase 1 schema exactly

### GitHub Contents API write
- [ ] GET `data/movies.json` with `Accept: application/vnd.github+json` and bearer token
- [ ] Decode base64 content safely as UTF-8
- [ ] Parse JSON and check for duplicates (`tmdb_id`, `imdb_id`)
- [ ] Append the new entry and re-encode as base64
- [ ] PUT the file with `message`, `content`, `sha`, and `branch`
- [ ] Handle `409`/`422` SHA conflicts with refetch + retry (max 3)
- [ ] Handle `401`, `403`, `404`, and rate-limit responses with actionable messages
- [ ] Show the resulting commit URL on success
- [ ] Refetch the library with cache-busting after the commit
- [ ] Handle GitHub Pages deployment delay (poll/retry messaging)

### Security and validation
- [ ] Confirm the PAT requires only fine-grained `Contents: Read and write`
- [ ] Verify no secrets are committed; re-check `.gitignore`
- [ ] Sanitise all user/TMDB text before inserting into the DOM (`textContent`, no `innerHTML`)
- [ ] Add a confirmation step before committing
- [ ] End-to-end test: add one film, verify the commit, verify it appears in the grid
- [ ] Document the add flow and its limitations in [`architecture.md`](architecture.md)

---

## Cross-Cutting

- [ ] Keep [`TODO.md`](TODO.md) and [`architecture.md`](architecture.md) in sync with every feature/refactor
- [ ] Review the repo for accidental secrets (TMDB key, PAT) before each push
- [ ] Confirm `data/movies.json` remains committed while `data/movies.xlsx` stays ignored
- [ ] Occasional dependency update review for Phase 1
