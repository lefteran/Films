"""Enrich data/movies_lite.json with official TMDB genres and curated subgenres.

Reads data/movies_lite.json without modifying it, queries TMDB v3 for each
movie (using tmdb_id directly, or resolving via imdb_id with /3/find), extracts
official `genres` and whitelisted `subgenres` from `keywords`, and writes the
enriched catalogue to movies_enriched.json with 2-space indentation.
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
DEFAULT_OUTPUT_FILE = BASE_DIR / "movies_enriched.json"
ENV_FILE = BASE_DIR / ".env"

TMDB_FIND_URL = "https://api.themoviedb.org/3/find/{imdb_id}"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{tmdb_id}"
REQUEST_DELAY = 0.25
SAVE_INTERVAL = 50
MAX_RETRIES = 3

# Curated mapping from lowercase TMDB keyword name -> canonical subgenre label.
SUBGENRE_WHITELIST = {
    "dark comedy": "Dark Comedy",
    "black comedy": "Dark Comedy",
    "dark humor": "Dark Comedy",
    "gallows humor": "Dark Comedy",
    "satire": "Satire",
    "political satire": "Political Satire",
    "social satire": "Social Satire",
    "parody": "Parody",
    "spoof": "Parody",
    "slapstick": "Slapstick",
    "slapstick comedy": "Slapstick",
    "screwball comedy": "Screwball Comedy",
    "romantic comedy": "Romantic Comedy",
    "buddy comedy": "Buddy Comedy",
    "buddy cop": "Buddy Cop",
    "mockumentary": "Mockumentary",
    "found footage": "Found Footage",
    "tragicomedy": "Tragicomedy",
    "slasher": "Slasher",
    "psychological thriller": "Psychological Thriller",
    "psychological horror": "Psychological Horror",
    "body horror": "Body Horror",
    "folk horror": "Folk Horror",
    "gothic horror": "Gothic Horror",
    "giallo": "Giallo",
    "zombie": "Zombie",
    "vampire": "Vampire",
    "monster movie": "Monster Movie",
    "kaiju": "Kaiju",
    "supernatural horror": "Supernatural Horror",
    "haunted house": "Haunted House",
    "cyberpunk": "Cyberpunk",
    "steampunk": "Steampunk",
    "dystopia": "Dystopia",
    "post-apocalyptic": "Post-Apocalyptic",
    "post-apocalyptic future": "Post-Apocalyptic",
    "time travel": "Time Travel",
    "space opera": "Space Opera",
    "alien invasion": "Alien Invasion",
    "neo-noir": "Neo-Noir",
    "neo noir": "Neo-Noir",
    "film noir": "Film Noir",
    "noir": "Film Noir",
    "tech noir": "Tech Noir",
    "whodunit": "Whodunit",
    "murder mystery": "Murder Mystery",
    "heist": "Heist",
    "caper": "Heist",
    "conspiracy": "Conspiracy Thriller",
    "conspiracy thriller": "Conspiracy Thriller",
    "political thriller": "Political Thriller",
    "spy thriller": "Spy Thriller",
    "espionage": "Espionage",
    "legal thriller": "Legal Thriller",
    "erotic thriller": "Erotic Thriller",
    "coming of age": "Coming of Age",
    "coming-of-age": "Coming of Age",
    "teen drama": "Teen Drama",
    "road movie": "Road Movie",
    "courtroom drama": "Courtroom Drama",
    "legal drama": "Legal Drama",
    "biographical drama": "Biographical Drama",
    "historical drama": "Historical Drama",
    "period drama": "Period Drama",
    "costume drama": "Costume Drama",
    "melodrama": "Melodrama",
    "family drama": "Family Drama",
    "kitchen sink realism": "Kitchen Sink Realism",
    "social realism": "Social Realism",
    "neorealism": "Neorealism",
    "italian neorealism": "Italian Neorealism",
    "french new wave": "French New Wave",
    "surrealism": "Surrealism",
    "magical realism": "Magical Realism",
    "avant-garde": "Avant-Garde",
    "experimental": "Experimental",
    "anthology": "Anthology",
    "spaghetti western": "Spaghetti Western",
    "revisionist western": "Revisionist Western",
    "martial arts": "Martial Arts",
    "kung fu": "Kung Fu",
    "wuxia": "Wuxia",
    "samurai": "Samurai",
    "sword and sandal": "Sword and Sandal",
    "swashbuckler": "Swashbuckler",
    "disaster": "Disaster",
    "survival": "Survival",
    "anti-war": "Anti-War",
    "sports drama": "Sports Drama",
    "musical comedy": "Musical Comedy",
    "rock opera": "Rock Opera",
    "jukebox musical": "Jukebox Musical",
    "stop motion": "Stop Motion",
    "anime": "Anime",
    "silent film": "Silent Film",
    "true crime": "True Crime",
    "gangster": "Gangster",
    "mafia": "Mafia",
}


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


def write_json_pretty(path, data):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def tmdb_get(session, url, params):
    """GET a TMDB endpoint with retry/backoff for 429 and 5xx responses."""
    for attempt in range(MAX_RETRIES + 1):
        response = session.get(url, params=params, timeout=20)
        if response.status_code == 404:
            return None
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt >= MAX_RETRIES:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else (2 ** attempt)
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response.json()
    return None


def resolve_tmdb_id(session, api_key, imdb_id):
    """Resolve a TMDB movie ID from an IMDb ID using /3/find."""
    payload = tmdb_get(
        session,
        TMDB_FIND_URL.format(imdb_id=imdb_id),
        {"api_key": api_key, "external_source": "imdb_id"},
    )
    if not payload:
        return None
    movie_results = payload.get("movie_results") or []
    if movie_results:
        return movie_results[0].get("id")
    return None


def extract_genres_and_subgenres(details):
    """Extract official genre names and whitelisted subgenre labels from TMDB details."""
    genres = []
    for item in details.get("genres") or []:
        name = (item.get("name") or "").strip()
        if name and name not in genres:
            genres.append(name)

    keywords_block = details.get("keywords") or {}
    raw_keywords = keywords_block.get("keywords") or keywords_block.get("results") or []
    subgenres = []
    for kw in raw_keywords:
        raw_name = (kw.get("name") or "").strip().lower()
        canonical = SUBGENRE_WHITELIST.get(raw_name)
        if canonical and canonical not in subgenres:
            subgenres.append(canonical)

    return genres, subgenres


def main():
    parser = argparse.ArgumentParser(
        description="Enrich data/movies_lite.json with TMDB genres and curated subgenres."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="Output JSON path (default: movies_enriched.json in repo root).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of movies to process (0 = all).",
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

    total = len(movies) if args.limit <= 0 else min(args.limit, len(movies))
    enriched_movies = []
    enriched_count = 0
    not_found_count = 0
    failed_count = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for idx, movie in enumerate(movies):
            entry = dict(movie)
            if idx >= total:
                entry.setdefault("genres", [])
                entry.setdefault("subgenres", [])
                enriched_movies.append(entry)
                continue

            title = entry.get("original_title") or entry.get("greek_title") or "<unknown>"
            tmdb_id = entry.get("tmdb_id")
            imdb_id = (entry.get("imdb_id") or "").strip()

            try:
                if not tmdb_id and imdb_id:
                    tmdb_id = resolve_tmdb_id(session, api_key, imdb_id)
                    time.sleep(REQUEST_DELAY)

                if not tmdb_id:
                    print(f"[{idx + 1}/{total}] Warning: Not found on TMDb (no ID) - {title}")
                    entry["genres"] = []
                    entry["subgenres"] = []
                    not_found_count += 1
                    enriched_movies.append(entry)
                    continue

                details = tmdb_get(
                    session,
                    TMDB_MOVIE_URL.format(tmdb_id=tmdb_id),
                    {
                        "api_key": api_key,
                        "language": "en-US",
                        "append_to_response": "keywords",
                    },
                )
            except (requests.RequestException, ValueError) as exc:
                print(f"[{idx + 1}/{total}] Warning: Request failed for {title}: {exc}")
                entry["genres"] = []
                entry["subgenres"] = []
                failed_count += 1
                enriched_movies.append(entry)
                time.sleep(REQUEST_DELAY)
                continue

            if not details:
                print(f"[{idx + 1}/{total}] Warning: TMDb 404 for {title} (tmdb_id={tmdb_id})")
                entry["genres"] = []
                entry["subgenres"] = []
                not_found_count += 1
                enriched_movies.append(entry)
                time.sleep(REQUEST_DELAY)
                continue

            genres, subgenres = extract_genres_and_subgenres(details)
            entry["genres"] = genres
            entry["subgenres"] = subgenres
            enriched_count += 1
            enriched_movies.append(entry)

            print(
                f"[{idx + 1}/{total}] Enriched: {title} "
                f"(genres={genres}, subgenres={subgenres})"
            )

            if (idx + 1) % SAVE_INTERVAL == 0:
                write_json_pretty(args.output, enriched_movies)

            time.sleep(REQUEST_DELAY)

    write_json_pretty(args.output, enriched_movies)

    print("\nEnrichment complete.")
    print(f"  Processed: {total}")
    print(f"  Enriched:  {enriched_count}")
    print(f"  Not found: {not_found_count}")
    print(f"  Failed:    {failed_count}")
    print(f"  Saved to:  {args.output}")


if __name__ == "__main__":
    main()
