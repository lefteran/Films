"""Backfill missing IMDb IDs using TMDB title/year/director validation.

The script scans data/movies_lite.json for movies whose `imdb_id` is null,
empty, or whitespace-only. For each movie it:

1. Searches TMDB using the original/Greek title variants and release year.
2. Prefilters candidates by title similarity and year.
3. Fetches candidate details with external IDs and credits.
4. Accepts a match only when the title, year, and director evidence is strong.
5. Writes the found IMDb ID into the existing movie object.

Progress is saved every 25 processed movies. A report is written to
docs/imdb_backfill_report.md with matched and unmatched results.
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
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
REPORT_FILE = BASE_DIR / "docs" / "imdb_backfill_report.md"
TMDB_API_BASE = "https://api.themoviedb.org/3"
REQUEST_DELAY = 0.2
SAVE_EVERY = 25
MAX_CANDIDATES = 6


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


def has_imdb_id(movie):
    value = movie.get("imdb_id")
    return isinstance(value, str) and bool(value.strip())


def normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


def similarity(left, right):
    left_text = normalize_text(left)
    right_text = normalize_text(right)
    if not left_text or not right_text:
        return 0.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def title_variants(title):
    raw = str(title or "").strip()
    variants = []

    def add(value):
        value = re.sub(r"\s+", " ", value).strip(" -–—:/")
        if value and value not in variants:
            variants.append(value)

    add(raw)
    add(re.sub(r"\(\s*(?:19|20)\d{2}\s*\)", "", raw))
    for part in re.split(r"\s+[-–—/]\s+|\s*:\s*", raw):
        add(part)
    return variants[:5]


def extract_year(value):
    match = re.search(r"\b(19|20)\d{2}\b", str(value or ""))
    return int(match.group(0)) if match else None


def name_tokens(value):
    return {token for token in normalize_text(value).split() if len(token) > 1}


def names_match(left, right):
    left_tokens = name_tokens(left)
    right_tokens = name_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    required = min(2, len(left_tokens), len(right_tokens))
    return len(left_tokens & right_tokens) >= required


def director_matches(movie_director, tmdb_directors):
    if not movie_director or not tmdb_directors:
        return None
    return any(names_match(movie_director, director) for director in tmdb_directors)


def build_search_attempts(movie, year):
    titles = [movie.get("original_title"), movie.get("greek_title")]
    attempts = []
    seen = set()

    for title in titles:
        for variant in title_variants(title):
            for query_year in ([year, None] if year else [None]):
                key = (variant, query_year)
                if key not in seen:
                    seen.add(key)
                    attempts.append((variant, query_year))

    return attempts[:8]


def tmdb_get(session, api_key, path, **params):
    try:
        response = session.get(
            f"{TMDB_API_BASE}/{path}",
            params={"api_key": api_key, **params},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
    finally:
        time.sleep(REQUEST_DELAY)


def search_movies(session, api_key, movie, year):
    for query, query_year in build_search_attempts(movie, year):
        params = {
            "query": query,
            "language": "en-US",
            "include_adult": "false",
        }
        if query_year:
            params["primary_release_year"] = query_year

        data = tmdb_get(session, api_key, "search/movie", **params)
        results = data.get("results") or []
        if results:
            return query, results
    return None, []


def candidate_title_similarity(movie, candidate):
    variants = []
    for title in (movie.get("original_title"), movie.get("greek_title")):
        variants.extend(title_variants(title))

    titles = [
        candidate.get("title"),
        candidate.get("original_title"),
    ]
    return max(
        (similarity(variant, title) for variant in variants for title in titles if title),
        default=0.0,
    )


def candidate_is_plausible(movie, candidate):
    movie_year = movie.get("year")
    movie_year = movie_year if isinstance(movie_year, int) else None
    candidate_year = extract_year(candidate.get("release_date"))

    if movie_year and candidate_year and abs(movie_year - candidate_year) > 1:
        return False

    return candidate_title_similarity(movie, candidate) >= 0.55


def fetch_candidate_details(session, api_key, tmdb_id):
    return tmdb_get(
        session,
        api_key,
        f"movie/{tmdb_id}",
        language="en-US",
        append_to_response="external_ids,credits",
    )


def evaluate_candidate(movie, candidate, details):
    imdb_id = (details.get("external_ids") or {}).get("imdb_id")
    if not isinstance(imdb_id, str) or not re.fullmatch(r"tt\d{7,8}", imdb_id.strip()):
        return None

    titles = [
        details.get("title"),
        details.get("original_title"),
        candidate.get("title"),
        candidate.get("original_title"),
    ]

    variants = []
    for title in (movie.get("original_title"), movie.get("greek_title")):
        variants.extend(title_variants(title))

    title_score = max(
        (similarity(variant, title) for variant in variants for title in titles if title),
        default=0.0,
    )
    if title_score < 0.72:
        return None

    movie_year = movie.get("year")
    movie_year = movie_year if isinstance(movie_year, int) else None
    candidate_year = extract_year(details.get("release_date")) or extract_year(candidate.get("release_date"))

    year_match = None
    if movie_year and candidate_year:
        year_match = abs(movie_year - candidate_year) <= 1
        if not year_match:
            return None

    credits = details.get("credits") or {}
    directors = [
        (member.get("name") or "").strip()
        for member in (credits.get("crew") or [])
        if (member.get("job") or "").strip().lower() == "director"
        and (member.get("name") or "").strip()
    ]
    director_match = director_matches(movie.get("director"), directors)

    if director_match is True:
        accepted = title_score >= 0.72
    elif director_match is None:
        accepted = title_score >= 0.90 and year_match is True
    else:
        accepted = False

    if not accepted:
        return None

    score = title_score * 100
    if year_match is True:
        score += 10
    if director_match is True:
        score += 20

    return {
        "imdb_id": imdb_id.strip(),
        "tmdb_id": details.get("id") or candidate.get("id"),
        "matched_title": details.get("title") or candidate.get("title"),
        "matched_year": candidate_year,
        "title_score": title_score,
        "year_match": year_match,
        "director_match": director_match,
        "score": score,
    }


def find_match(session, api_key, movie):
    movie_year = movie.get("year")
    movie_year = movie_year if isinstance(movie_year, int) else None
    query, results = search_movies(session, api_key, movie, movie_year)
    if not results:
        return None

    plausible = [candidate for candidate in results if candidate_is_plausible(movie, candidate)]
    plausible = plausible[:MAX_CANDIDATES]

    best_match = None
    for candidate in plausible:
        tmdb_id = candidate.get("id")
        if not tmdb_id:
            continue
        try:
            details = fetch_candidate_details(session, api_key, tmdb_id)
        except (requests.RequestException, ValueError) as exc:
            print(f"  ! Candidate {tmdb_id} request failed: {exc}")
            continue

        match = evaluate_candidate(movie, candidate, details)
        if match and (best_match is None or match["score"] > best_match["score"]):
            best_match = match

    return best_match


def escape_markdown(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def write_report(matched, unmatched, checked_count, dry_run, limit):
    lines = [
        "# IMDb Backfill Report",
        "",
        f"Checked **{checked_count}** movies with a missing or empty `imdb_id`.",
        f"Matched **{len(matched)}**; unmatched **{len(unmatched)}**.",
        f"Mode: {'dry run' if dry_run else 'write'}.",
    ]
    if limit is not None:
        lines.append(f"Limit applied: first {limit} candidates only.")
    lines.extend([
        "",
        "## Matched",
        "",
        "| List No. | Title | Year | Director | IMDb ID | TMDB ID | Score |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])

    for movie, match in matched:
        lines.append(
            f"| {escape_markdown(movie.get('shelf_id'))} "
            f"| {escape_markdown(movie.get('original_title'))} "
            f"| {escape_markdown(movie.get('year'))} "
            f"| {escape_markdown(movie.get('director'))} "
            f"| {escape_markdown(match['imdb_id'])} "
            f"| {escape_markdown(match['tmdb_id'])} "
            f"| {match['score']:.1f} |"
        )

    lines.extend([
        "",
        "## Unmatched",
        "",
        "| List No. | Title | Year | Director |",
        "| --- | --- | --- | --- |",
    ])

    for movie in unmatched:
        lines.append(
            f"| {escape_markdown(movie.get('shelf_id'))} "
            f"| {escape_markdown(movie.get('original_title'))} "
            f"| {escape_markdown(movie.get('year'))} "
            f"| {escape_markdown(movie.get('director'))} |"
        )

    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backfill missing IMDb IDs from TMDB.")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N missing movies.")
    parser.add_argument("--dry-run", action="store_true", help="Find matches without modifying movies_lite.json.")
    args = parser.parse_args(argv)

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

    missing = [movie for movie in movies if not has_imdb_id(movie)]
    if args.limit is not None:
        missing = missing[:max(args.limit, 0)]

    print(f"Loaded {len(movies)} movies.")
    print(f"Missing IMDb IDs to process: {len(missing)}")
    if args.dry_run:
        print("Dry run: movies_lite.json will not be written.")

    matched = []
    unmatched = []
    processed = 0

    with requests.Session() as session:
        session.headers.update({"accept": "application/json"})

        for movie in missing:
            processed += 1
            title = movie.get("original_title") or movie.get("greek_title") or "<unknown>"
            print(
                f"[{processed}/{len(missing)}] {title} "
                f"({movie.get('year') or '-'}) / {movie.get('director') or '-'}"
            )

            try:
                match = find_match(session, api_key, movie)
            except (requests.RequestException, ValueError) as exc:
                print(f"  ! Search failed: {exc}")
                match = None

            if match:
                movie["imdb_id"] = match["imdb_id"]
                matched.append((movie, match))
                print(
                    f"  + {match['imdb_id']} (TMDB {match['tmdb_id']}, "
                    f"score {match['score']:.1f}, matched '{match['matched_title']}')"
                )
            else:
                unmatched.append(movie)
                print("  - No confident match.")

            if not args.dry_run and processed % SAVE_EVERY == 0:
                write_json(MOVIES_FILE, movies)
                print(f"  [save] Progressive save after {processed} processed movies.")

    if not args.dry_run:
        write_json(MOVIES_FILE, movies)

    write_report(matched, unmatched, len(missing), args.dry_run, args.limit)

    print("\nIMDb backfill complete.")
    print(f"Matched: {len(matched)}")
    print(f"Unmatched: {len(unmatched)}")
    print(f"Report: {REPORT_FILE}")
    if not args.dry_run:
        print(f"Saved {MOVIES_FILE.name} in minified format.")


if __name__ == "__main__":
    main()
