"""Patch actor and director formatting in data/movies_lite.json from TMDB credits.

Flagged movies:
- `actors` contains a period (`.`), indicating abbreviated legacy names.
- `director` contains a comma (`,`), indicating "Lastname, Firstname" formatting.
- `actors` or `director` contains Greek characters, indicating a previous run
  fetched localised names.

For each flagged movie with a valid `tmdb_id`, the script fetches English TMDB
credits, updates actors with the first four cast names, updates the director from
the first crew member whose job is "Director", and saves progress every 25 records.
"""

import json
import os
import re
import sys
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
SAVE_EVERY = 25
GREEK_CHARS_RE = re.compile(r"[α-ωΑ-Ωά-ώΆ-Ώ]")


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


def has_greek_characters(value):
    return bool(GREEK_CHARS_RE.search(str(value or "")))


def get_patch_reasons(movie):
    reasons = []
    actors = movie.get("actors")
    director = movie.get("director")

    if isinstance(actors, str) and "." in actors:
        reasons.append("actors contain period")
    if isinstance(director, str) and "," in director:
        reasons.append("director contains comma")
    if has_greek_characters(actors):
        reasons.append("actors contain Greek characters")
    if has_greek_characters(director):
        reasons.append("director contains Greek characters")

    return reasons


def get_top_actor_names(details):
    cast = (details.get("credits") or {}).get("cast") or []
    names = [
        actor.get("name", "").strip()
        for actor in cast[:4]
        if actor.get("name")
    ]
    names = [name for name in names if name]
    return ", ".join(names) if names else None


def get_director_name(details):
    crew = (details.get("credits") or {}).get("crew") or []
    for member in crew:
        if (member.get("job") or "").strip().lower() == "director":
            name = (member.get("name") or "").strip()
            if name:
                return name
    return None


def fetch_movie_details(session, api_key, tmdb_id):
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


def main():
    load_env_file()

    try:
        movies = read_json(MOVIES_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Failed to load {MOVIES_FILE}: {exc}")

    if not isinstance(movies, list):
        sys.exit(f"{MOVIES_FILE} must contain a JSON array.")

    flagged = []
    for index, movie in enumerate(movies, start=1):
        reasons = get_patch_reasons(movie)
        if reasons:
            flagged.append((index, movie, reasons))

    print(f"Loaded {len(movies)} movies.")
    print(f"Movies requiring credit patches: {len(flagged)}")

    if not flagged:
        print("Nothing to patch.")
        return

    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        sys.exit("TMDB_API_KEY is missing. Add it to .env or the environment.")

    actors_updated = 0
    directors_updated = 0
    patched_movies = 0
    processed = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for position, (_, movie, reasons) in enumerate(flagged, start=1):
            title = movie.get("greek_title") or movie.get("original_title") or "<unknown>"
            print(f"[{position}/{len(flagged)}] {title} - {', '.join(reasons)}")

            tmdb_id = movie.get("tmdb_id")
            if not tmdb_id:
                print("  ! Skipped: no tmdb_id.")
                processed += 1
                if processed % SAVE_EVERY == 0:
                    write_json(MOVIES_FILE, movies)
                    print(f"  [save] Progressive save after {processed} flagged records.")
                continue

            try:
                details = fetch_movie_details(session, api_key, tmdb_id)
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! TMDB request failed: {exc}")
                processed += 1
                if processed % SAVE_EVERY == 0:
                    write_json(MOVIES_FILE, movies)
                    print(f"  [save] Progressive save after {processed} flagged records.")
                continue

            changed = False

            actor_names = get_top_actor_names(details)
            if actor_names and movie.get("actors") != actor_names:
                movie["actors"] = actor_names
                actors_updated += 1
                changed = True
                print(f"  + Actors: {actor_names}")
            elif not actor_names:
                print("  - No TMDB cast names; keeping existing actors.")

            director_name = get_director_name(details)
            if director_name and movie.get("director") != director_name:
                movie["director"] = director_name
                directors_updated += 1
                changed = True
                print(f"  + Director: {director_name}")
            elif not director_name:
                print("  - No TMDB director credit; keeping existing director.")

            if changed:
                patched_movies += 1

            processed += 1
            if processed % SAVE_EVERY == 0:
                write_json(MOVIES_FILE, movies)
                print(f"  [save] Progressive save after {processed} flagged records.")

    write_json(MOVIES_FILE, movies)

    print("\nCredit patch complete.")
    print(f"Movies changed: {patched_movies}")
    print(f"Actors updated: {actors_updated}")
    print(f"Directors updated: {directors_updated}")
    print(f"Saved {MOVIES_FILE.name} in minified format.")


if __name__ == "__main__":
    main()
