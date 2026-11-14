# Activate environment
.films\Scripts\activate.bat

# Install Python dependencies
.films\Scripts\pip.exe install -r requirements.txt

# Required .env keys: TMDB_API_KEY, AI_API_KEY, AI_BASE_URL (optional), AI_MODEL

# Repair abbreviated actors and comma-formatted director names
.films\Scripts\python.exe scripts\patch_credits.py

# Translate missing synopses with the BYOK AI client
.films\Scripts\python.exe scripts\patch_synopses_ai.py

# Add a movie locally (the same script used by the Manage Movie GitHub Action)
.films\Scripts\python.exe scripts\manage_movie.py --action add --imdb_id tt0111161 --list_no A123

# Modify a movie's list number / shelf ID
.films\Scripts\python.exe scripts\manage_movie.py --action modify --imdb_id tt0111161 --list_no B456

# Delete a movie and its synopsis entry
.films\Scripts\python.exe scripts\manage_movie.py --action delete --imdb_id tt0111161
