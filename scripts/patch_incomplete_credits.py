"""Fix incomplete actor and director credits listed in temp/incomplete_credits.json.

The script reads temp/incomplete_credits.json and data/movies_lite.json,
resolves each flagged movie on TMDB via `imdb_id` (falling back to `tmdb_id`),
fetches English credits (`append_to_response=credits&language=en-US`), updates
`actors` (top 4 cast names) and `director` (first Director crew member), and
writes data/movies_lite.json in minified UTF-8 format.
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
INCOMPLETE_FILE = BASE_DIR / "temp" / "incomplete_credits.json"
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
    movie_results = response.json().get("movie_results") or []
    if movie_results:
        return movie_results[0].get("id")
    return None


def fetch_movie_credits(session, api_key, movie):
    """Fetch English TMDB movie details with credits via imdb_id (or tmdb_id fallback)."""
    imdb_id = (movie.get("imdb_id") or "").strip()
    tmdb_id = resolve_tmdb_movie_id(session, api_key, imdb_id) if imdb_id else None
    if tmdb_id is None:
        tmdb_id = movie.get("tmdb_id")
    if not tmdb_id:
        return None

    time.sleep(REQUEST_DELAY)
    response = session.get(
        TMDB_MOVIE_URL.format(tmdb_id=tmdb_id),
        params={
            "api_key": api_key,
            "language": "en-US",
            "append_to_response": "credits",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def get_top_actor_names(details):
    cast = (details.get("credits") or {}).get("cast") or []
    names = [
        (actor.get("name") or "").strip()
        for actor in cast[:4]
        if (actor.get("name") or "").strip()
    ]
    return ", ".join(names) if names else None


def get_director_name(details):
    crew = (details.get("credits") or {}).get("crew") or []
    for member in crew:
        if (member.get("job") or "").strip().lower() == "director":
            name = (member.get("name") or "").strip()
            if name:
                return name
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Fix incomplete credits in data/movies_lite.json using temp/incomplete_credits.json."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query TMDB and preview updates without modifying data/movies_lite.json.",
    )
    args = parser.parse_args()

    load_env_file()
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        sys.exit("TMDB_API_KEY is missing. Add it to .env or the environment.")

    try:
        movies = read_json(MOVIES_FILE)
        incomplete = read_json(INCOMPLETE_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Failed to load JSON data: {exc}")

    if not isinstance(movies, list) or not isinstance(incomplete, list):
        sys.exit("Both data/movies_lite.json and temp/incomplete_credits.json must be JSON arrays.")

    by_key = {
        (movie.get("shelf_id"), movie.get("original_title")): movie
        for movie in movies
    }
    by_imdb = {
        movie.get("imdb_id"): movie
        for movie in movies
        if movie.get("imdb_id")
    }

    targets = []
    for entry in incomplete:
        movie = by_key.get((entry.get("shelf_id"), entry.get("original_title")))
        if movie is None and entry.get("imdb_id"):
            movie = by_imdb.get(entry.get("imdb_id"))
        if movie is not None:
            targets.append(movie)

    print(f"Loaded {len(movies)} movies and {len(incomplete)} incomplete entries.")
    print(f"Matched catalogue records to inspect: {len(targets)}")

    if not targets:
        print("Nothing to patch.")
        return

    changed_movies = 0
    actors_updated = 0
    directors_updated = 0
    skipped = 0
    failed = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for position, movie in enumerate(targets, start=1):
            title = movie.get("greek_title") or movie.get("original_title") or "<unknown>"
            imdb_id = (movie.get("imdb_id") or "").strip()
            tmdb_id = movie.get("tmdb_id")
            print(f"[{position}/{len(targets)}] {title} ({imdb_id or tmdb_id or 'no id'})")

            if not imdb_id and not tmdb_id:
                print("  ! Skipped: no imdb_id or tmdb_id.")
                skipped += 1
                continue

            try:
                details = fetch_movie_credits(session, api_key, movie)
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! TMDB request failed: {exc}")
                failed += 1
                time.sleep(REQUEST_DELAY)
                continue

            if not details:
                print("  - No TMDB match found.")
                skipped += 1
                time.sleep(REQUEST_DELAY)
                continue

            changed = False

            actor_names = get_top_actor_names(details)
            if actor_names and movie.get("actors") != actor_names:
                print(f"  + Actors: {actor_names}")
                if not args.dry_run:
                    movie["actors"] = actor_names
                actors_updated += 1
                changed = True

            director_name = get_director_name(details)
            if director_name and movie.get("director") != director_name:
                print(f"  + Director: {director_name}")
                if not args.dry_run:
                    movie["director"] = director_name
                directors_updated += 1
                changed = True

            if changed:
                changed_movies += 1
                if not args.dry_run and changed_movies % SAVE_INTERVAL == 0:
                    write_json(MOVIES_FILE, movies)
                    print(f"  * Saved progress ({changed_movies} movies updated).")
            else:
                print("  - No credit changes needed.")

            time.sleep(REQUEST_DELAY)

    if not args.dry_run and changed_movies > 0:
        write_json(MOVIES_FILE, movies)

    print("\nSummary:")
    print(f"  Checked:           {len(targets)}")
    print(f"  Movies changed:    {changed_movies}")
    print(f"  Actors updated:    {actors_updated}")
    print(f"  Directors updated: {directors_updated}")
    print(f"  Skipped:           {skipped}")
    print(f"  Failed:            {failed}")
    if args.dry_run:
        print("  (Dry run: data/movies_lite.json was not modified.)")


if __name__ == "__main__":
    main()
