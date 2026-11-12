"""Fill missing synopses with a BYOK OpenAI-compatible translation client.

For movies whose `shelf_id` is missing from data/synopses.json (or maps to a
blank value), the script fetches the English TMDB overview and asks the
configured AI model to translate it into Greek.

Required environment variables:
- TMDB_API_KEY
- AI_API_KEY
- AI_MODEL
Optional:
- AI_BASE_URL (for cloud gateways or local OpenAI-compatible interfaces)
"""

import json
import os
import sys
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
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{tmdb_id}"
SAVE_EVERY = 25

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


def get_synopsis_key(movie):
    shelf_id = movie.get("shelf_id")
    return None if shelf_id is None else str(shelf_id)


def has_synopsis(movie, synopses):
    key = get_synopsis_key(movie)
    return key is not None and bool(str(synopses.get(key) or "").strip())


def fetch_english_overview(session, api_key, tmdb_id):
    response = session.get(
        TMDB_MOVIE_URL.format(tmdb_id=tmdb_id),
        params={"api_key": api_key, "language": "en-US"},
        timeout=20,
    )
    response.raise_for_status()
    return (response.json().get("overview") or "").strip()


def translate_with_ai(client, model, text):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
    )
    content = response.choices[0].message.content if response.choices else ""
    translation = (content or "").strip()
    if len(translation) >= 2 and translation[0] == translation[-1] == '"':
        translation = translation[1:-1].strip()
    return translation


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

    missing = []
    for index, movie in enumerate(movies, start=1):
        if not has_synopsis(movie, synopses):
            missing.append((index, movie))

    print(f"Loaded {len(movies)} movies and {len(synopses)} synopses.")
    print(f"Movies missing a synopsis: {len(missing)}")

    if not missing:
        print("Nothing to translate.")
        return

    tmdb_api_key = os.getenv("TMDB_API_KEY")
    ai_api_key = os.getenv("AI_API_KEY")
    ai_base_url = os.getenv("AI_BASE_URL")
    ai_model = os.getenv("AI_MODEL")

    if not tmdb_api_key:
        sys.exit("TMDB_API_KEY is missing. Add it to .env or the environment.")
    if not ai_api_key:
        sys.exit("AI_API_KEY is missing. Add it to .env or the environment.")
    if not ai_model:
        sys.exit("AI_MODEL is missing. Add it to .env or the environment.")

    client_kwargs = {"api_key": ai_api_key}
    if ai_base_url:
        client_kwargs["base_url"] = ai_base_url
    client = OpenAI(**client_kwargs)

    translated_count = 0
    processed = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for position, (_, movie) in enumerate(missing, start=1):
            title = movie.get("greek_title") or movie.get("original_title") or "<unknown>"
            print(f"[{position}/{len(missing)}] {title}")

            tmdb_id = movie.get("tmdb_id")
            if not tmdb_id:
                print("  ! Skipped: no tmdb_id.")
                processed += 1
                if processed % SAVE_EVERY == 0:
                    write_json(SYNOPSES_FILE, synopses)
                    print(f"  [save] Progressive save after {processed} records.")
                continue

            try:
                english_overview = fetch_english_overview(session, tmdb_api_key, tmdb_id)
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! TMDB request failed: {exc}")
                processed += 1
                if processed % SAVE_EVERY == 0:
                    write_json(SYNOPSES_FILE, synopses)
                    print(f"  [save] Progressive save after {processed} records.")
                continue

            if not english_overview:
                print("  - No English overview available.")
                processed += 1
                if processed % SAVE_EVERY == 0:
                    write_json(SYNOPSES_FILE, synopses)
                    print(f"  [save] Progressive save after {processed} records.")
                continue

            try:
                translation = translate_with_ai(client, ai_model, english_overview)
            except Exception as exc:
                print(f"  ! AI translation failed: {exc}")
                processed += 1
                if processed % SAVE_EVERY == 0:
                    write_json(SYNOPSES_FILE, synopses)
                    print(f"  [save] Progressive save after {processed} records.")
                continue

            key = get_synopsis_key(movie)
            if key is not None and translation:
                synopses[key] = translation
                translated_count += 1
                print(f"  + Greek synopsis added ({len(translation)} chars).")
            else:
                print("  - AI returned an empty translation.")

            processed += 1
            if processed % SAVE_EVERY == 0:
                write_json(SYNOPSES_FILE, synopses)
                print(f"  [save] Progressive save after {processed} records.")

    write_json(SYNOPSES_FILE, synopses)

    print("\nAI synopsis patch complete.")
    print(f"Synopses added: {translated_count}")
    print(f"Saved {SYNOPSES_FILE.name} in minified format.")


if __name__ == "__main__":
    main()
