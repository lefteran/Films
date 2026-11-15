# Activate environment
.films\Scripts\activate.bat

# Install Python dependencies
.films\Scripts\pip.exe install -r requirements.txt

# Required .env keys: TMDB_API_KEY, AI_API_KEY, AI_BASE_URL (optional), AI_MODEL

# Repair abbreviated actors and comma-formatted director names
.films\Scripts\python.exe scripts\patch_credits.py

# Translate missing synopses with the BYOK AI client
.films\Scripts\python.exe scripts\patch_synopses_ai.py

# Backfill genres for movies with an empty tags list
.films\Scripts\python.exe scripts\patch_genres.py

# Add one movie locally (the same script used by the Manage Movie GitHub Action)
.films\Scripts\python.exe scripts\manage_movie.py --action add --imdb_id tt0111161 --list_no A123

# Batch add: comma-separated IMDb IDs and matching list numbers
.films\Scripts\python.exe scripts\manage_movie.py --action add --imdb_id tt0111161,tt0068646 --list_no A123,B456

# Modify a movie's list number / shelf ID
.films\Scripts\python.exe scripts\manage_movie.py --action modify --imdb_id tt0111161 --list_no B456

# Delete one or more movies and their synopsis entries
.films\Scripts\python.exe scripts\manage_movie.py --action delete --imdb_id tt0111161,tt0068646
