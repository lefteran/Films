import openpyxl
import requests
import json
import re
import time
from deep_translator import GoogleTranslator

# --- ΡΥΘΜΙΣΕΙΣ ---
EXCEL_FILE = "data/all_movies.xlsx"
MOVIES_LITE_OUTPUT = "data/movies_lite.json"
SYNOPSES_OUTPUT = "data/synopses.json"
TMDB_API_KEY = "3161f4f13307a8cfd205d3c4bf87bb7e"

COLOR_TO_TAGS = {
    "FFCCFFCC": ["Official GR Subs"],
    "FF9CC2E5": ["Greek Movie"],
    "FFFABF8F": ["Custom GR Subs"],
    "FFCC0069": ["HDD Only"],
    "FFDA9694": ["VHS Rip"],
    "FF00B0F0": ["HD"],
    "FFFFFF00": ["EN Subs Only"]
}

def get_imdb_id(url):
    if not url: return None
    match = re.search(r'(tt\d{7,8})', url)
    return match.group(1) if match else None

def get_tmdb_id(imdb_id, title, year):
    """Βρίσκει το TMDB ID της ταινίας"""
    headers = {"accept": "application/json"}
    
    if imdb_id:
        url = f"https://api.themoviedb.org/3/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id&language=el-GR"
        response = requests.get(url, headers=headers).json()
        results = response.get("movie_results", [])
        if results:
            return results[0].get("id")
            
    if title:
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={title}&language=el-GR"
        if year:
            url += f"&primary_release_year={year}"
        
        response = requests.get(url, headers=headers).json()
        results = response.get("results", [])
        if results:
            return results[0].get("id")
            
    return None

def fetch_movie_details(tmdb_id, language="el-GR"):
    """Τραβάει τα πλήρη δεδομένα, συμπεριλαμβανομένων συντελεστών και διάρκειας"""
    if not tmdb_id:
        return None
        
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_API_KEY}&language={language}&append_to_response=credits"
    headers = {"accept": "application/json"}
    return requests.get(url, headers=headers).json()

def get_top_actors(tmdb_data, fallback):
    """Επιστρέφει έως 4 ονόματα ηθοποιών από τα TMDB credits, αλλιώς το Excel."""
    if not tmdb_data:
        return fallback

    cast = (tmdb_data.get("credits") or {}).get("cast") or []
    names = [
        actor.get("name", "").strip()
        for actor in cast[:4]
        if actor.get("name")
    ]
    return ", ".join(names) if names else fallback

def get_synopsis(tmdb_data, tmdb_id):
    """Επιστρέφει ελληνική σύνοψη, μεταφράζοντας την αγγλική αν λείπει."""
    if not tmdb_data:
        return ""

    synopsis = (tmdb_data.get("overview") or "").strip()
    if synopsis:
        return synopsis

    english_data = fetch_movie_details(tmdb_id, language="en-US")
    english_overview = (english_data.get("overview") or "").strip() if english_data else ""
    if not english_overview:
        return ""

    try:
        translated = GoogleTranslator(source="en", target="el").translate(english_overview)
        return (translated or "").strip() or english_overview
    except Exception as exc:
        print(f"Προειδοποίηση: αποτυχία μετάφρασης για TMDB ID {tmdb_id}: {exc}")
        return english_overview
    finally:
        time.sleep(0.5)

def main():
    print("Φόρτωση αρχείου Excel...")
    wb = openpyxl.load_workbook(EXCEL_FILE, data_only=True)
    
    # Επιλογή της σωστής καρτέλας
    if "Alphanumeric" in wb.sheetnames:
        sheet = wb["Alphanumeric"]
    else:
        print("Σφάλμα: Δεν βρέθηκε καρτέλα με όνομα 'Alphanumeric' στο αρχείο.")
        return
        
    movies_db = []
    synopses_db = {}
    
    # max_col=10 για να διασφαλίσουμε ότι διαβάζονται αρκετές στήλες
    for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, max_col=10):
        # Αν η γραμμή έχει λιγότερα κελιά από τα αναμενόμενα, την προσπερνάμε
        if len(row) < 6:
            continue
            
        shelf_id = row[0].value
        title_cell = row[2]
        director = row[3].value
        actors = row[4].value
        year = row[5].value
        
        # Αν το κελί του τίτλου είναι εντελώς άδειο
        if not title_cell or not title_cell.value:
            continue
            
        original_title = str(title_cell.value).strip()
        
        # Ασφαλής ανάγνωση χρώματος
        color_hex = None
        if title_cell.fill and title_cell.fill.start_color:
            color_hex = title_cell.fill.start_color.index
            
        # Ασφαλής ανάγνωση hyperlink
        hyperlink = None
        if hasattr(title_cell, 'hyperlink') and title_cell.hyperlink:
            hyperlink = title_cell.hyperlink.target
        
        tags = COLOR_TO_TAGS.get(color_hex, [])
        
        print(f"Επεξεργασία: {original_title}...")
        
        imdb_id = get_imdb_id(hyperlink)
        tmdb_id = get_tmdb_id(imdb_id, original_title, year)
        tmdb_data = fetch_movie_details(tmdb_id)
        
        actors_value = get_top_actors(tmdb_data, actors)
        synopsis = get_synopsis(tmdb_data, tmdb_id)
        
        movie_entry = {
            "shelf_id": shelf_id,
            "original_title": original_title,
            "director": director,
            "actors": actors_value,
            "year": year,
            "tags": tags,
            "imdb_id": imdb_id,
            "tmdb_id": tmdb_id,
            "greek_title": tmdb_data.get("title") if tmdb_data else None,
            "duration_minutes": tmdb_data.get("runtime") if tmdb_data else None,
            "poster_url": f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}" if tmdb_data and tmdb_data.get("poster_path") else None
        }
        
        movies_db.append(movie_entry)
        
        # Το shelf_id είναι το μοναδικό κλειδί για το αρχείο συνόψεων
        if shelf_id is not None:
            if shelf_id in synopses_db:
                print(f"Προειδοποίηση: διπλό shelf_id '{shelf_id}', η σύνοψη θα αντικατασταθεί.")
            synopses_db[shelf_id] = synopsis
        time.sleep(0.2)
        
    # Minified έξοδοι: το catalogue χωρίς σύνοψη + ξεχωριστό dictionary συνόψεων
    with open(MOVIES_LITE_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(movies_db, f, ensure_ascii=False, separators=(",", ":"))
        
    with open(SYNOPSES_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(synopses_db, f, ensure_ascii=False, separators=(",", ":"))
        
    print(f"\nΟλοκληρώθηκε! Εξήχθησαν {len(movies_db)} ταινίες στο {MOVIES_LITE_OUTPUT}.")
    print(f"Εξήχθησαν {len(synopses_db)} σύνοψεις στο {SYNOPSES_OUTPUT}.")

if __name__ == "__main__":
    main()