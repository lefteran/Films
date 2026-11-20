"""Backfill missing duration_minutes in data/movies_lite.json via TMDB.

The script loads data/movies_lite.json once, selects movies whose
duration_minutes is missing/null/0 and whose imdb_id is present, resolves the
TMDB ID via /3/find/{imdb_id}, fetches movie details for `runtime`, updates
duration_minutes, and rewrites the file in minified UTF-8 format.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # Fall back to a minimal .env parser if python-dotenv is absent.
    load_dotenv = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
MOVIES_FILE = BASE_DIR / "data" / "movies_lite.json"
ENV_FILE = BASE_DIR / ".env"
TMDB_FIND_URL = "https://api.themoviedb.org/3/find/{imdb_id}"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{tmdb_id}"
REQUEST_DELAY = 0.25
SAVE_INTERVAL = 25


def load_env_file(path=ENV_FILE):
    """Load .env without overriding variables already set in the environment."""
    if load_dotenv is not None:
        load_dotenv(dotenv_path=path)
        return

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        os.environ.setdefault(key, value.strip().strip("\"'"))


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))


def resolve_tmdb_movie_id(session, api_key, imdb_id):
    """Resolve a TMDB movie ID from an IMDb ID using /3/find."""
    response = session.get(
        TMDB_FIND_URL.format(imdb_id=imdb_id),
        params={"api_key": api_key, "external_source": "imdb_id"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    movie_results = payload.get("movie_results") or []
    if movie_results:
        return movie_results[0].get("id")
    return None


def fetch_runtime(session, api_key, movie):
    """Fetch runtime in minutes from TMDB using imdb_id (or tmdb_id fallback)."""
    imdb_id = (movie.get("imdb_id") or "").strip()
    tmdb_id = resolve_tmdb_movie_id(session, api_key, imdb_id) if imdb_id else None
    if tmdb_id is None:
        tmdb_id = movie.get("tmdb_id")
    if not tmdb_id:
        return None

    time.sleep(REQUEST_DELAY)
    response = session.get(
        TMDB_MOVIE_URL.format(tmdb_id=tmdb_id),
        params={"api_key": api_key, "language": "en-US"},
        timeout=20,
    )
    response.raise_for_status()
    runtime = response.json().get("runtime")
    if isinstance(runtime, int) and runtime > 0:
        return runtime
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Backfill missing duration_minutes in data/movies_lite.json via TMDB."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query TMDB and report how many durations were found without modifying the file.",
    )
    args = parser.parse_args()

    load_env_file()
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        sys.exit("TMDB_API_KEY is missing. Add it to .env or the environment.")

    try:
        movies = read_json(MOVIES_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Failed to load {MOVIES_FILE}: {exc}")

    if not isinstance(movies, list):
        sys.exit(f"{MOVIES_FILE} must contain a JSON array.")

    targets = [
        movie
        for movie in movies
        if (movie.get("duration_minutes") is None or movie.get("duration_minutes") in ("", 0))
        and (movie.get("imdb_id") or "").strip()
    ]
    print(f"Loaded {len(movies)} movies.")
    print(f"Movies missing duration_minutes with imdb_id: {len(targets)}")

    if not targets:
        print("Nothing to patch.")
        return

    found = 0
    not_found = 0
    failed = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for position, movie in enumerate(targets, start=1):
            title = movie.get("greek_title") or movie.get("original_title") or "<unknown>"
            imdb_id = movie["imdb_id"]
            print(f"[{position}/{len(targets)}] {title} ({imdb_id})")

            try:
                runtime = fetch_runtime(session, api_key, movie)
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! TMDB request failed: {exc}")
                failed += 1
                time.sleep(REQUEST_DELAY)
                continue

            if runtime:
                found += 1
                print(f"  + Duration found: {runtime} min")
                if not args.dry_run:
                    movie["duration_minutes"] = runtime
                    if found % SAVE_INTERVAL == 0:
                        write_json(MOVIES_FILE, movies)
                        print(f"  * Saved progress ({found} updated).")
            else:
                not_found += 1
                print("  - No runtime found on TMDB.")

            time.sleep(REQUEST_DELAY)

    if not args.dry_run and found > 0:
        write_json(MOVIES_FILE, movies)

    print("\nSummary:")
    print(f"  Checked:   {len(targets)}")
    print(f"  Found:     {found}")
    print(f"  Not found: {not_found}")
    print(f"  Failed:    {failed}")
    if args.dry_run:
        print("  (Dry run: data/movies_lite.json was not modified.)")


if __name__ == "__main__":
    main()
