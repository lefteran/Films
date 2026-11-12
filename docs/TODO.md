# Film-O-List — TODO

Actionable checklist for the three-phase build. Items are ordered so that each phase unblocks the
next. Update this file as work lands; see [`architecture.md`](architecture.md) for design details.

---

## Phase 0 — Project Foundations

- [x] Create `docs/` documentation folder
- [x] Write [`architecture.md`](architecture.md) covering the 3-phase design
- [x] Write this `TODO.md` checklist
- [x] Create `scripts/`, `src/`, and `data/` directories
- [x] Add `.gitignore` for `.films/`, `__pycache__/`, and private Excel workbooks (`data/*.xlsx`)
- [x] Confirm `.gitignore` covers the current migration input (`data/all_movies.xlsx`)
- [ ] Create/verify the `.films/` virtual environment
- [x] Add [`requirements.txt`](../requirements.txt) (`openpyxl`, `requests`, `python-dotenv`, `openai`)
- [ ] Add `.env.example` with `TMDB_API_KEY=`, `AI_API_KEY=`, `AI_BASE_URL=`, and `AI_MODEL=`
- [ ] Add a root `README.md` (project summary, setup, run commands)
- [ ] Initialize the Git repository (`git init`) and confirm the remote/default branch (`main`)
- [ ] Decide and add a license

---

## Phase 1 — Data Migration (Python)

### Script setup
- [x] Migration script exists at [`scripts/excel_to_tmdb.py`](../scripts/excel_to_tmdb.py)
- [x] Move/refactor the prototype into `scripts/excel_to_tmdb.py`
- [ ] Load `TMDB_API_KEY` from the environment instead of hardcoding it
- [ ] Make paths configurable via CLI arguments (`--input`, `--output`)
- [ ] Keep module import side-effect free; expose a `main()` entry point

### Workbook parsing
- [ ] Inspect the real `data/all_movies.xlsx` and confirm columns, header row, and `Alphanumeric` sheet
- [ ] Read `shelf_id` (column A) without dropping leading zeros
- [ ] Read title (column C), director (D), actors (E), year (F)
- [ ] Skip empty/header rows reliably
- [ ] Extract hyperlink and parse IMDb ID with `tt\d{7,8}`
- [ ] Read cell fill colour robustly (ARGB normalisation; handle theme/indexed and `FFFFFFFF`/`00000000`)
- [ ] Finalise the colour → tag mapping and update the table in [`architecture.md`](architecture.md)
- [x] Remove the `VHS Rip` tag mapping from `COLOR_TO_TAGS`
- [x] Remove the 11 existing `VHS Rip` tags from `data/movies_lite.json`
- [ ] Support multiple tags per colour if the workbook requires it

### TMDB enrichment
- [x] Implement IMDb lookup via `/3/find/{imdb_id}` (`external_source=imdb_id`, `language=el-GR`)
- [x] Implement fallback search via `/3/search/movie` with title + `primary_release_year`
- [x] Request and store `greek_title`, `duration_minutes`, and `overview` (exported to `synopses.json`)
- [x] Build `poster_url` at `w500`
- [ ] Add retry with backoff for `429`/`5xx` and honour `Retry-After`
- [ ] Add a request timeout and clear error handling
- [x] Respect TMDB rate limits (keep the inter-request delay)
- [ ] Cache TMDB responses locally during development to avoid re-fetching
- [x] Fetch `append_to_response=credits` and use the first 4 TMDB cast full names, falling back to Excel only when cast is empty
- [x] Leave missing Greek overviews empty in the exporter for the BYOK AI synopsis patcher

### Output quality
- [ ] Define and validate the JSON schema from [`architecture.md`](architecture.md) §3.6
- [ ] Deduplicate by `tmdb_id`, then `imdb_id`, then normalised title + year
- [ ] Handle films not found on TMDB without aborting the run
- [ ] Log a summary: processed, matched, unmatched, skipped, duplicates
- [x] Write `data/movies_lite.json` and `data/synopses.json` as UTF-8, minified output
- [ ] Add a small test workbook fixture and unit tests for colour mapping and IMDb parsing
- [ ] Run a full migration against the real workbook
- [ ] Manually spot-check 10–20 entries (posters, titles, tags, shelf IDs)
- [ ] Investigate duplicate `shelf_id` values in the workbook (24 collisions in the current export) so the synopsis map is lossless
- [ ] Commit the generated `data/movies_lite.json` and `data/synopses.json`

### Payload optimization
- [x] Split the export into `data/movies_lite.json` (catalogue, no synopsis) and `data/synopses.json` (`shelf_id` → synopsis)
- [x] Minify both files with `json.dump(..., separators=(',', ':'))`
- [x] Generate the initial split from the existing `data/movies.json` (3.45 MB → 1.13 MB catalogue + 1.75 MB deferred synopses)
- [x] Switch the initial frontend fetch to `data/movies_lite.json`
- [x] Lazy-load `data/synopses.json` on first modal open, showing “Φόρτωση σύνοψης...” while it loads
- [x] Document the split data model and lazy-loading strategy in [`architecture.md`](architecture.md)

### Incremental patching
- [x] Remove the obsolete `scripts/patch_existing_json.py`
- [x] Create [`scripts/patch_credits.py`](../scripts/patch_credits.py) for actor/director credit repair
- [x] Flag movies with periods, commas, or Greek characters in `actors`/`director`
- [x] Request credits with `language=en-US` so cast and crew names stay in Latin characters
- [x] Update actors from the first 4 TMDB cast names and director from the first `Director` crew member
- [x] Progressively save `movies_lite.json` every 25 flagged records
- [x] Create [`scripts/patch_synopses_ai.py`](../scripts/patch_synopses_ai.py) for missing synopses
- [x] Configure the BYOK client with `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL`
- [x] Translate English TMDB overviews with the required Greek-translation system prompt
- [x] Progressively save `synopses.json` every 25 records
- [x] Document both workflows in [`architecture.md`](architecture.md) §3.8–3.9
- [ ] Run the credit and AI synopsis patchers against the real data and spot-check updated records

---

## Phase 2 — Frontend Application (Vanilla JS on GitHub Pages)

### Structure and data loading
- [ ] Create the root `index.html` app shell
- [ ] Create `src/css/styles.css`
- [ ] Create `src/js/app.js` (bootstrap and state)
- [ ] Create `src/js/data.js` (fetch + validation)
- [ ] Create `src/js/filters.js` (search + tag predicates)
- [ ] Create `src/js/render.js` (card rendering)
- [ ] Fetch `data/movies_lite.json` relative to the page and lazy-load `data/synopses.json` in the modal
- [ ] Show loading, error, and retry states
- [ ] Validate that the payload is a JSON array

### UI and behaviour
- [ ] Responsive movie grid (auto-fill cards)
- [ ] Movie cards: poster, title, year, director, tags, shelf ID
- [ ] Poster placeholder for missing/failed images
- [ ] Instant search with 300 ms debounce across title/director/actors
- [x] Accent-insensitive search normalization (NFD accent stripping + lowercase)
- [x] Fisher-Yates randomized default order when the search query is empty
- [ ] Tag filter chips with multi-select AND semantics
- [ ] Sort controls: title, year (newest/oldest), shelf
- [ ] Live result count (“X of Y films”)
- [ ] Empty state with “clear filters”
- [ ] Keyboard accessibility, visible focus, `aria-pressed` toggles, `alt` text
- [ ] Mirror query/tags to URL (`?q=`, `?tags=`) with `history.replaceState`
- [ ] Lazy-load posters (`loading="lazy"`, `decoding="async"`)

### UI enhancements
- [x] Rename the application to Film-O-List in the page title and header
- [x] Align the modal poster to the top and add an independently scrolling details/synopsis area (70vh desktop, 55vh mobile)
- [x] Enable `.small-grid` by default and synchronise the toggle’s `aria-pressed` state on load
- [x] Change the modal shelf label to “List No.” and add an IMDb link when `imdb_id` exists
- [x] Add the header “Μικρές / Μεγάλες Αφίσες” toggle and `.small-grid` styles

### Hosting and verification
- [ ] Configure GitHub Pages to serve from `main` / root
- [ ] Verify `/`, `/add/`, `/data/movies_lite.json`, and `/data/synopses.json` resolve correctly
- [ ] Cache-busting strategy for updated JSON (e.g. `?v=`)
- [ ] Test on mobile viewport and a narrow desktop window
- [ ] Test with missing posters and an empty filter result
- [ ] Document the deployment steps in [`architecture.md`](architecture.md)

---

## Phase 3 — Serverless Movie Addition

### Hidden add page
- [ ] Create `add/index.html` (not linked from the public UI)
- [ ] Reuse `src/` styles and modules where practical
- [ ] Resolve data paths relative to the page (`../data/movies_lite.json`, `../data/synopses.json`)
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
- [ ] GET `data/movies_lite.json` and `data/synopses.json` with `Accept: application/vnd.github+json` and bearer token
- [ ] Decode both base64 payloads safely as UTF-8
- [ ] Parse both JSON files and check for duplicates (`tmdb_id`, `imdb_id`)
- [ ] Append the catalogue entry and set `synopses[shelf_id]`, then re-encode both as minified base64
- [ ] PUT both files with their own `message`, `content`, `sha`, and `branch`
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
- [ ] Confirm `data/movies_lite.json` and `data/synopses.json` remain committed while private workbooks stay ignored
- [ ] Occasional dependency update review for Phase 1
