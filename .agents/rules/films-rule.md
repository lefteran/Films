---
trigger: always_on
description: "Core rules for Film-O-List: keep docs synced and enforce static-first, minified JSON, and GitHub Actions constraints."
---

# films-rule

## 1. Always Keep Documentation Synced
Whenever you implement a new feature, refactor code, change the directory structure, or complete a task, you MUST automatically do the following before finishing your response:
1. Update `docs/TODO.md`: Check off completed items using `[x]` and add any newly discovered sub-tasks to the list.
2. Update `docs/architecture.md`: If a new library is introduced, a new data flow is established, or the file structure changes, document the design decision immediately.
Do not consider a task fully complete until both files accurately reflect the current state of the codebase.

## 2. Frontend Constraints (Static-First)
- **No build step / Vanilla JS:** Keep the frontend in plain HTML, CSS, and JavaScript (`index.html`, `src/css/`, `src/js/`, `add/index.html`). Do NOT introduce bundlers, transpilers, frameworks (React/Vue/etc.), or third-party scripts.
- **GitHub Pages compatibility:** Ensure all asset and data paths work on static hosting without server-side rewrites (resolve paths inside `add/` relative to the document).
- **Security:** Never inject untrusted HTML and never log, commit, or transmit the GitHub PAT anywhere other than `api.github.com` (keep it in `sessionStorage` only).

## 3. Data & Schema Integrity
- **Split JSON database:** Keep `data/movies_lite.json` (catalogue array without `synopsis`) and `data/synopses.json` (`{ shelf_id: synopsis }` map) strictly separated. Do not revive the legacy `data/movies.json`.
- **Minified UTF-8 output:** Whenever writing either JSON file, always output minified UTF-8 with `ensure_ascii=False` and `separators=(',', ':')` (no indentation or extra whitespace).
- **Private files:** Never commit `data/all_movies.xlsx` or `.env`.

## 4. Python & GitHub Actions Pipeline
- **Online execution:** Python scripts (such as `scripts/manage_movie.py`) run in GitHub Actions (`ubuntu-latest`, Python 3.11) via `.github/workflows/manage_movie.yml`.
- **Dependencies:** If you add or update any Python dependency used by the pipeline, you MUST update `scripts/requirements.txt` (and `requirements.txt` if needed for local runs).
- **Secrets:** Never hardcode API keys (`TMDB_API_KEY`, `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`); always read them from environment variables / GitHub repository secrets.
- **Batch I/O:** In batch operations, load `movies_lite.json` and `synopses.json` once at the start and write them once at the end to minimize disk I/O and Git conflicts.