# Activate environment
.films\Scripts\activate.bat

# Install Python dependencies
.films\Scripts\pip.exe install -r requirements.txt

# Required .env keys: TMDB_API_KEY, AI_API_KEY, AI_BASE_URL (optional), AI_MODEL

# Repair abbreviated actors and comma-formatted director names
.films\Scripts\python.exe scripts\patch_credits.py

# Translate missing synopses with the BYOK AI client
.films\Scripts\python.exe scripts\patch_synopses_ai.py

# Add a movie locally (the same script used by the Add Movie GitHub Action)
.films\Scripts\python.exe scripts\add_movie.py --imdb_id tt0111161 --list_no A123
