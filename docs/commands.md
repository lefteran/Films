# Activate environment
.films\Scripts\activate.bat

# Install Python dependencies
.films\Scripts\pip.exe install -r requirements.txt

# Incrementally patch missing synopses and abbreviated actor names
.films\Scripts\python.exe scripts\patch_existing_json.py
