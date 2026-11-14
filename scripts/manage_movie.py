"""Manage movies in the catalogue: add, modify, or delete.

Examples:
    python scripts/manage_movie.py --action add --imdb_id tt0111161 --list_no A123
    python scripts/manage_movie.py --action modify --imdb_id tt0111161 --list_no B456
    python scripts/manage_movie.py --action delete --imdb_id tt0111161

The `add` action resolves TMDB metadata, optionally translates a missing Greek
overview, and inserts the movie at index 0. `modify` changes the shelf_id and
moves the synopsis key. `delete` removes both the movie and its synopsis entry.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from openai import OpenAI

try:
    from dotenv import load_dotenv
except ImportError:  # Fall back to a minimal .env parser if python-dotenv is absent.
    load_dotenv = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
MOVIES_FILE = BASE_DIR / "data" / "movies_lite.json"
SYNOPSES_FILE = BASE_DIR / "data" / "synopses.json"
ENV_FILE = BASE_DIR / ".env"
TMDB_API_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w500"

SYSTEM_PROMPT = (
    "You are a professional film translator. Translate the following movie synopsis "
    "into natural, engaging Greek. Output ONLY the translation without quotes or extra text."
)


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


def load_catalog():
    try:
        movies = read_json(MOVIES_FILE)
        synopses = read_json(SYNOPSES_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Failed to load JSON data: {exc}")

    if not isinstance(movies, list):
        sys.exit(f"{MOVIES_FILE} must contain a JSON array.")
    if not isinstance(synopses, dict):
        sys.exit(f"{SYNOPSES_FILE} must contain a JSON object.")

    return movies, synopses


def find_movie_index(movies, imdb_id):
    for index, movie in enumerate(movies):
        if movie.get("imdb_id") == imdb_id:
            return index
    return None


def tmdb_get(session, api_key, path, **params):
    response = session.get(
        f"{TMDB_API_BASE}/{path}",
        params={"api_key": api_key, **params},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def find_tmdb_id(session, api_key, imdb_id):
    data = tmdb_get(
        session,
        api_key,
        f"find/{imdb_id}",
        external_source="imdb_id",
    )
    results = data.get("movie_results") or []
    if not results:
        return None
    return results[0].get("id")


def fetch_movie_details(session, api_key, tmdb_id, language):
    return tmdb_get(session, api_key, f"movie/{tmdb_id}", language=language)


def fetch_credits(session, api_key, tmdb_id):
    return tmdb_get(session, api_key, f"movie/{tmdb_id}/credits", language="en-US")


def get_top_actors(credits):
    cast = credits.get("cast") or []
    names = [
        actor.get("name", "").strip()
        for actor in cast[:4]
        if actor.get("name")
    ]
    names = [name for name in names if name]
    return ", ".join(names) if names else None


def get_director(credits):
    crew = credits.get("crew") or []
    for member in crew:
        if (member.get("job") or "").strip().lower() == "director":
            name = (member.get("name") or "").strip()
            if name:
                return name
    return None


def extract_year(release_date):
    if not release_date or not isinstance(release_date, str):
        return None
    year_text = release_date[:4]
    return int(year_text) if year_text.isdigit() else None


def translate_overview(english_overview):
    ai_api_key = os.getenv("AI_API_KEY")
    ai_base_url = os.getenv("AI_BASE_URL")
    ai_model = os.getenv("AI_MODEL")

    if not ai_api_key:
        sys.exit("AI_API_KEY is missing. Add it to .env or the environment.")
    if not ai_model:
        sys.exit("AI_MODEL is missing. Add it to .env or the environment.")

    client_kwargs = {"api_key": ai_api_key}
    if ai_base_url:
        client_kwargs["base_url"] = ai_base_url
    client = OpenAI(**client_kwargs)

    try:
        response = client.chat.completions.create(
            model=ai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": english_overview},
            ],
            temperature=0.3,
        )
        content = response.choices[0].message.content if response.choices else ""
        translation = (content or "").strip()
        if len(translation) >= 2 and translation[0] == translation[-1] == '"':
            translation = translation[1:-1].strip()
        return translation
    except Exception as exc:
        sys.exit(f"AI translation failed: {exc}")


def add_movie(imdb_id, list_no):
    load_env_file()
    tmdb_api_key = os.getenv("TMDB_API_KEY")
    if not tmdb_api_key:
        sys.exit("TMDB_API_KEY is missing. Add it to .env or the environment.")

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        try:
            tmdb_id = find_tmdb_id(session, tmdb_api_key, imdb_id)
        except (requests.RequestException, ValueError) as exc:
            sys.exit(f"TMDB IMDb lookup failed: {exc}")

        if not tmdb_id:
            sys.exit(f"No TMDB movie found for IMDb ID {imdb_id}.")

        try:
            details = fetch_movie_details(session, tmdb_api_key, tmdb_id, "el-GR")
            credits = fetch_credits(session, tmdb_api_key, tmdb_id)
        except (requests.RequestException, ValueError) as exc:
            sys.exit(f"TMDB details/credits request failed: {exc}")

        greek_overview = (details.get("overview") or "").strip()
        synopsis = greek_overview
        synopsis_source = "TMDB el-GR"

        if not synopsis:
            try:
                english_details = fetch_movie_details(session, tmdb_api_key, tmdb_id, "en-US")
            except (requests.RequestException, ValueError) as exc:
                sys.exit(f"TMDB English overview request failed: {exc}")

            english_overview = (english_details.get("overview") or "").strip()
            if english_overview:
                synopsis = translate_overview(english_overview)
                synopsis_source = "AI translation"
            else:
                synopsis_source = "unavailable"

    actors = get_top_actors(credits)
    director = get_director(credits)
    original_title = details.get("original_title") or details.get("title")
    greek_title = details.get("title") or original_title
    poster_path = details.get("poster_path")

    movie = {
        "shelf_id": list_no,
        "original_title": original_title,
        "director": director,
        "actors": actors,
        "year": extract_year(details.get("release_date")),
        "tags": [],
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
        "greek_title": greek_title,
        "duration_minutes": details.get("runtime"),
        "poster_url": f"{POSTER_BASE}{poster_path}" if poster_path else None,
        "date_added": datetime.now().strftime("%Y-%m-%d"),
    }

    movies, synopses = load_catalog()

    for existing in movies:
        if existing.get("imdb_id") == imdb_id or existing.get("tmdb_id") == tmdb_id:
            sys.exit(
                f"Movie already exists: {existing.get('greek_title') or existing.get('original_title')} "
                f"(shelf_id={existing.get('shelf_id')})."
            )

    movies.insert(0, movie)
    if synopsis:
        synopses[list_no] = synopsis

    write_json(MOVIES_FILE, movies)
    write_json(SYNOPSES_FILE, synopses)

    print(f"Added movie: {greek_title} ({original_title})")
    print(f"TMDB ID: {tmdb_id}; List No.: {list_no}")
    print(f"Actors: {actors or '-'}; Director: {director or '-'}")
    print(f"Synopsis source: {synopsis_source}")
    print(f"Saved {MOVIES_FILE.name} and {SYNOPSES_FILE.name} in minified format.")


def modify_movie(imdb_id, list_no):
    movies, synopses = load_catalog()
    index = find_movie_index(movies, imdb_id)

    if index is None:
        sys.exit(f"Movie not found for IMDb ID {imdb_id}.")

    movie = movies[index]
    old_shelf_id = movie.get("shelf_id")
    movie["shelf_id"] = list_no

    if old_shelf_id is not None:
        old_key = str(old_shelf_id)
        new_key = str(list_no)
        if old_key != new_key and old_key in synopses:
            synopses[new_key] = synopses.pop(old_key)
            print(f"Moved synopsis key: {old_key} -> {new_key}")
        elif old_key == new_key:
            print("Shelf ID unchanged; synopsis key left in place.")
        else:
            print(f"No synopsis found for old shelf ID {old_key}.")

    write_json(MOVIES_FILE, movies)
    write_json(SYNOPSES_FILE, synopses)

    print(f"Modified movie: {movie.get('greek_title') or movie.get('original_title')}")
    print(f"IMDb ID: {imdb_id}; List No.: {list_no}")
    print(f"Saved {MOVIES_FILE.name} and {SYNOPSES_FILE.name} in minified format.")


def delete_movie(imdb_id):
    movies, synopses = load_catalog()
    index = find_movie_index(movies, imdb_id)

    if index is None:
        sys.exit(f"Movie not found for IMDb ID {imdb_id}.")

    removed = movies.pop(index)
    shelf_id = removed.get("shelf_id")
    if shelf_id is not None:
        synopses.pop(str(shelf_id), None)

    write_json(MOVIES_FILE, movies)
    write_json(SYNOPSES_FILE, synopses)

    print(f"Deleted movie: {removed.get('greek_title') or removed.get('original_title')}")
    print(f"IMDb ID: {imdb_id}; removed synopsis key: {shelf_id}")
    print(f"Saved {MOVIES_FILE.name} and {SYNOPSES_FILE.name} in minified format.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the Film-O-List catalogue.")
    parser.add_argument(
        "--action",
        required=True,
        choices=["add", "modify", "delete"],
        help="Action to perform: add, modify, or delete",
    )
    parser.add_argument("--imdb_id", required=True, help="IMDb ID, e.g. tt0111161")
    parser.add_argument(
        "--list_no",
        required=False,
        default=None,
        help="List number / shelf ID (required for add and modify)",
    )
    args = parser.parse_args(argv)

    imdb_id = args.imdb_id.strip()
    list_no = args.list_no.strip() if args.list_no else ""

    if not imdb_id:
        sys.exit("--imdb_id cannot be empty.")
    if args.action in ("add", "modify") and not list_no:
        sys.exit(f"--list_no is required for the '{args.action}' action.")

    if args.action == "add":
        add_movie(imdb_id, list_no)
    elif args.action == "modify":
        modify_movie(imdb_id, list_no)
    else:
        delete_movie(imdb_id)


if __name__ == "__main__":
    main()
