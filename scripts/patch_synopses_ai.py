"""Fill missing synopses from TMDB (Greek first, then AI-translated English).

For movies whose `shelf_id` is missing from data/synopses.json (or maps to a
null/blank value), the script checks TMDB using `imdb_id` (falling back to
`tmdb_id`) for a Greek overview (`el-GR`). If unavailable, it fetches the
English overview (`en-US`) and asks the configured AI model to translate it
into Greek.

Required environment variables:
- TMDB_API_KEY
Required for English-to-Greek AI fallback:
- AI_API_KEY
- AI_MODEL
Optional:
- AI_BASE_URL (for cloud gateways or local OpenAI-compatible interfaces)
"""

import json
import os
import sys
import time
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
TMDB_FIND_URL = "https://api.themoviedb.org/3/find/{imdb_id}"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{tmdb_id}"
REQUEST_DELAY = 0.25
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


def fetch_overview(session, api_key, movie, language):
    """Fetch a movie overview from TMDB by imdb_id, falling back to tmdb_id."""
    imdb_id = (movie.get("imdb_id") or "").strip()
    if imdb_id:
        response = session.get(
            TMDB_FIND_URL.format(imdb_id=imdb_id),
            params={
                "api_key": api_key,
                "external_source": "imdb_id",
                "language": language,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        for bucket in ("movie_results", "tv_results"):
            for item in payload.get(bucket) or []:
                overview = (item.get("overview") or "").strip()
                if overview:
                    return overview

    tmdb_id = movie.get("tmdb_id")
    if tmdb_id:
        response = session.get(
            TMDB_MOVIE_URL.format(tmdb_id=tmdb_id),
            params={"api_key": api_key, "language": language},
            timeout=20,
        )
        response.raise_for_status()
        return (response.json().get("overview") or "").strip()

    return ""


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

    client = None
    if ai_api_key and ai_model:
        client_kwargs = {"api_key": ai_api_key}
        if ai_base_url:
            client_kwargs["base_url"] = ai_base_url
        client = OpenAI(**client_kwargs)
    else:
        print(
            "Warning: AI_API_KEY or AI_MODEL is missing. "
            "Only existing Greek TMDB synopses will be saved; English fallback translation will be skipped."
        )

    greek_tmdb_count = 0
    translated_count = 0
    processed = 0

    def maybe_save():
        if processed % SAVE_EVERY == 0:
            write_json(SYNOPSES_FILE, synopses)
            print(f"  [save] Progressive save after {processed} records.")

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for position, (_, movie) in enumerate(missing, start=1):
            title = movie.get("greek_title") or movie.get("original_title") or "<unknown>"
            imdb_id = (movie.get("imdb_id") or "").strip()
            tmdb_id = movie.get("tmdb_id")
            print(f"[{position}/{len(missing)}] {title} ({imdb_id or tmdb_id or 'no id'})")

            if not imdb_id and not tmdb_id:
                print("  ! Skipped: no imdb_id or tmdb_id.")
                processed += 1
                maybe_save()
                continue

            try:
                greek_overview = fetch_overview(session, tmdb_api_key, movie, "el-GR")
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! TMDB Greek request failed: {exc}")
                processed += 1
                maybe_save()
                time.sleep(REQUEST_DELAY)
                continue

            key = get_synopsis_key(movie)
            if greek_overview and key is not None:
                synopses[key] = greek_overview
                greek_tmdb_count += 1
                print(f"  + Greek synopsis found on TMDB ({len(greek_overview)} chars).")
                processed += 1
                maybe_save()
                time.sleep(REQUEST_DELAY)
                continue

            time.sleep(REQUEST_DELAY)

            try:
                english_overview = fetch_overview(session, tmdb_api_key, movie, "en-US")
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! TMDB English request failed: {exc}")
                processed += 1
                maybe_save()
                time.sleep(REQUEST_DELAY)
                continue

            if not english_overview:
                print("  - No Greek or English overview available on TMDB.")
                processed += 1
                maybe_save()
                time.sleep(REQUEST_DELAY)
                continue

            if client is None:
                print("  - English overview found, but AI translation is not configured.")
                processed += 1
                maybe_save()
                time.sleep(REQUEST_DELAY)
                continue

            try:
                translation = translate_with_ai(client, ai_model, english_overview)
            except Exception as exc:
                print(f"  ! AI translation failed: {exc}")
                processed += 1
                maybe_save()
                time.sleep(REQUEST_DELAY)
                continue

            if key is not None and translation:
                synopses[key] = translation
                translated_count += 1
                print(f"  + Greek synopsis translated via AI ({len(translation)} chars).")
            else:
                print("  - AI returned an empty translation.")

            processed += 1
            maybe_save()
            time.sleep(REQUEST_DELAY)

    write_json(SYNOPSES_FILE, synopses)

    print("\nSynopsis patch complete.")
    print(f"Added from TMDB (Greek): {greek_tmdb_count}")
    print(f"Added via AI translation: {translated_count}")
    print(f"Total synopses added: {greek_tmdb_count + translated_count}")
    print(f"Saved {SYNOPSES_FILE.name} in minified format.")


if __name__ == "__main__":
    main()
