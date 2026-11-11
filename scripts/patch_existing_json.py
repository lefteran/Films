"""Incrementally patch the existing movie JSON files without a full TMDB re-export.

A movie is patched only when:
- its `shelf_id` is missing from `synopses.json`, or its synopsis is blank; and/or
- its `actors` string is non-null and contains a period (`.`), which indicates
  abbreviated names such as "P. Richard" from the original Excel sheet.

The script reads `TMDB_API_KEY` from the repository `.env` file (or environment),
updates TMDB metadata, and rewrites both JSON files in minified UTF-8 format.
"""

import json
import os
import sys
import time
from pathlib import Path

# Windows consoles may use a legacy code page; never crash on unencodable titles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

import requests
from deep_translator import GoogleTranslator

try:
    from dotenv import load_dotenv
except ImportError:  # Fall back to a minimal .env parser if python-dotenv is absent.
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
MOVIES_FILE = BASE_DIR / "data" / "movies_lite.json"
SYNOPSES_FILE = BASE_DIR / "data" / "synopses.json"
ENV_FILE = BASE_DIR / ".env"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{tmdb_id}"


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


def get_synopsis_key(movie):
    shelf_id = movie.get("shelf_id")
    return None if shelf_id is None else str(shelf_id)


def get_patch_reasons(movie, synopses):
    """Return human-readable reasons explaining why a movie needs patching."""
    reasons = []

    key = get_synopsis_key(movie)
    synopsis = synopses.get(key) if key is not None else None
    if key is None or not str(synopsis or "").strip():
        reasons.append("missing/empty synopsis")

    actors = movie.get("actors")
    if isinstance(actors, str) and "." in actors:
        reasons.append("abbreviated actors")

    return reasons


def get_top_actor_names(details):
    """Return the first four TMDB cast names, or None when credits are unavailable."""
    cast = (details.get("credits") or {}).get("cast") or []
    names = [
        actor.get("name", "").strip()
        for actor in cast[:4]
        if actor.get("name")
    ]
    names = [name for name in names if name]
    return ", ".join(names) if names else None


def fetch_movie_details(session, api_key, tmdb_id, language="el-GR"):
    """Fetch movie details and credits from TMDB."""
    response = session.get(
        TMDB_MOVIE_URL.format(tmdb_id=tmdb_id),
        params={
            "api_key": api_key,
            "language": language,
            "append_to_response": "credits",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def resolve_synopsis(session, api_key, tmdb_id, greek_details):
    """Return a Greek synopsis, translating the English overview when necessary."""
    greek_overview = (greek_details.get("overview") or "").strip()
    if greek_overview:
        return greek_overview

    english_details = fetch_movie_details(session, api_key, tmdb_id, language="en-US")
    english_overview = (english_details.get("overview") or "").strip()
    if not english_overview:
        return ""

    try:
        translated = GoogleTranslator(source="en", target="el").translate(english_overview)
        return (translated or "").strip() or english_overview
    except Exception as exc:
        print(f"  ! Translation failed: {exc}. Keeping English overview.")
        return english_overview
    finally:
        time.sleep(0.5)


def patch_movie(session, api_key, movie, synopses, reasons, position, total):
    """Patch one movie and return (actors_changed, synopsis_changed)."""
    title = movie.get("greek_title") or movie.get("original_title") or "<unknown>"
    print(f"[{position}/{total}] {title} - {', '.join(reasons)}")

    tmdb_id = movie.get("tmdb_id")
    if not tmdb_id:
        print("  ! Skipped: no tmdb_id.")
        return False, False

    try:
        details = fetch_movie_details(session, api_key, tmdb_id)
    except (requests.RequestException, ValueError) as exc:
        print(f"  ! TMDB request failed: {exc}")
        return False, False

    actors_changed = False
    actor_names = get_top_actor_names(details)
    if actor_names:
        if movie.get("actors") != actor_names:
            movie["actors"] = actor_names
            actors_changed = True
            print(f"  + Actors: {actor_names}")
    else:
        print("  - No TMDB cast names; keeping existing actors.")

    synopsis_changed = False
    key = get_synopsis_key(movie)
    current_synopsis = synopses.get(key) if key is not None else None

    if key is not None and not str(current_synopsis or "").strip():
        try:
            synopsis = resolve_synopsis(session, api_key, tmdb_id, details)
        except (requests.RequestException, ValueError) as exc:
            print(f"  ! English fallback request failed: {exc}")
            synopsis = ""

        if synopsis:
            synopses[key] = synopsis
            synopsis_changed = True
            print(f"  + Synopsis updated ({len(synopsis)} chars).")
        else:
            print("  - No Greek or English overview available.")
    elif key is not None:
        print("  - Existing synopsis preserved.")

    return actors_changed, synopsis_changed


def main():
    load_env_file()

    try:
        movies = read_json(MOVIES_FILE)
        synopses = read_json(SYNOPSES_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Failed to load JSON data: {exc}")

    if not isinstance(movies, list):
        sys.exit(f"{MOVIES_FILE} must contain a JSON array.")
    if not isinstance(synopses, dict):
        sys.exit(f"{SYNOPSES_FILE} must contain a JSON object.")

    flagged = []
    for index, movie in enumerate(movies, start=1):
        reasons = get_patch_reasons(movie, synopses)
        if reasons:
            flagged.append((index, movie, reasons))

    print(f"Loaded {len(movies)} movies and {len(synopses)} synopses.")
    print(f"Movies requiring patch: {len(flagged)}")

    if not flagged:
        write_json(MOVIES_FILE, movies)
        write_json(SYNOPSES_FILE, synopses)
        print("Nothing to patch. Files rewritten in minified format.")
        return

    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        sys.exit("TMDB_API_KEY is missing. Add it to .env or the environment.")

    actors_updated = 0
    synopses_updated = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})
        for position, (_, movie, reasons) in enumerate(flagged, start=1):
            actors_changed, synopsis_changed = patch_movie(
                session, api_key, movie, synopses, reasons, position, len(flagged)
            )
            actors_updated += int(actors_changed)
            synopses_updated += int(synopsis_changed)

    write_json(MOVIES_FILE, movies)
    write_json(SYNOPSES_FILE, synopses)

    print("\nPatch complete.")
    print(f"Actors updated: {actors_updated}")
    print(f"Synopses updated: {synopses_updated}")
    print(f"Saved {MOVIES_FILE.name} and {SYNOPSES_FILE.name} in minified format.")


if __name__ == "__main__":
    main()
