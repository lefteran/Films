"""Backfill TMDB genres for catalogue movies with an empty tags list.

The script loads data/movies_lite.json once, fetches English movie details for
each movie that has no tags, stores the English genre names in `tags`, sleeps
briefly between requests, and rewrites the file in minified UTF-8 format.
"""

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
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{tmdb_id}"
REQUEST_DELAY = 0.25


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


def fetch_genres(session, api_key, tmdb_id):
    response = session.get(
        TMDB_MOVIE_URL.format(tmdb_id=tmdb_id),
        params={"api_key": api_key, "language": "en-US"},
        timeout=20,
    )
    response.raise_for_status()
    details = response.json()

    genres = []
    for genre in details.get("genres") or []:
        name = (genre.get("name") or "").strip()
        if name and name not in genres:
            genres.append(name)
    return genres


def main():
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

    missing = [movie for movie in movies if not movie.get("tags")]
    print(f"Loaded {len(movies)} movies.")
    print(f"Movies with an empty tags list: {len(missing)}")

    if not missing:
        print("Nothing to patch.")
        return

    updated = 0
    skipped = 0
    failed = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for position, movie in enumerate(missing, start=1):
            title = movie.get("greek_title") or movie.get("original_title") or "<unknown>"
            tmdb_id = movie.get("tmdb_id")
            print(f"[{position}/{len(missing)}] {title}")

            if not tmdb_id:
                print("  ! Skipped: no tmdb_id.")
                skipped += 1
                continue

            try:
                genres = fetch_genres(session, api_key, tmdb_id)
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! TMDB request failed: {exc}")
                failed += 1
                continue
            finally:
                time.sleep(REQUEST_DELAY)

            movie["tags"] = genres
            if genres:
                updated += 1
                print(f"  + Genres: {', '.join(genres)}")
            else:
                print("  - No genres returned.")

    write_json(MOVIES_FILE, movies)

    print("\nGenre patch complete.")
    print(f"Movies updated: {updated}")
    print(f"Skipped without TMDB ID: {skipped}")
    print(f"Failed requests: {failed}")
    print(f"Saved {MOVIES_FILE.name} in minified format.")


if __name__ == "__main__":
    main()
