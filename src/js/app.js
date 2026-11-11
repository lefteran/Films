// Global State (Η κατάσταση της εφαρμογής)
let moviesData = [];
let filteredMovies = [];
let activeTags = new Set();
let allTags = new Set();
let synopsesData = null;
let synopsesPromise = null;

// DOM Elements
const moviesGrid = document.getElementById('moviesGrid');
const searchInput = document.getElementById('searchInput');
const statsDisplay = document.getElementById('statsDisplay');
const tagsContainer = document.getElementById('tagsContainer');
const emptyState = document.getElementById('emptyState');

const movieModal = document.getElementById('movieModal');
const modalBody = document.getElementById('modalBody');
const closeModalBtn = document.getElementById('closeModal');

// 1. Φόρτωση των δεδομένων
async function fetchMovies() {
    try {
        const response = await fetch('data/movies_lite.json');
        moviesData = await response.json();
        filteredMovies = [...moviesData];
        
        // Εξαγωγή όλων των μοναδικών tags για να φτιάξουμε τα κουμπιά φίλτρων
        moviesData.forEach(movie => {
            if (movie.tags && Array.isArray(movie.tags)) {
                movie.tags.forEach(tag => allTags.add(tag));
            }
        });
        
        renderTags();
        renderGrid(filteredMovies);
    } catch (error) {
        console.error("Σφάλμα κατά τη φόρτωση του JSON:", error);
        moviesGrid.innerHTML = `<p style="color:red;">Αποτυχία φόρτωσης δεδομένων.</p>`;
    }
}

// 2. Δημιουργία των HTML Καρτών
function renderGrid(movies) {
    moviesGrid.innerHTML = ''; // Καθαρισμός
    
    if (movies.length === 0) {
        emptyState.classList.remove('hidden');
        statsDisplay.textContent = '0 ταινίες';
        return;
    }
    emptyState.classList.add('hidden');
    statsDisplay.textContent = `${movies.length} ταινίες (από ${moviesData.length})`;

    // Χρήση DocumentFragment για μέγιστη απόδοση
    const fragment = document.createDocumentFragment();

    movies.forEach(movie => {
        const card = document.createElement('div');
        card.className = 'movie-card';
        
        const title = movie.greek_title || movie.original_title;
        const posterSrc = movie.poster_url || 'https://via.placeholder.com/500x750/2a2a2a/ffffff?text=No+Poster';
        
        // Δημιουργία των μικρών tags (αν υπάρχουν)
        const tagsHtml = movie.tags ? movie.tags.map(tag => `<span class="card-tag">${tag}</span>`).join('') : '';

        card.innerHTML = `
            <div class="poster-container">
                <img src="${posterSrc}" alt="${title}" class="movie-poster" loading="lazy" decoding="async">
                <div class="shelf-badge">${movie.shelf_id}</div>
            </div>
            <div class="movie-info">
                <h3 class="movie-title">${title}</h3>
                <div class="movie-meta">${movie.year || '-'} • ${movie.director || '-'}</div>
                <div class="card-tags">${tagsHtml}</div>
            </div>
        `;

        // Όταν κάνει κλικ, ανοίγει το Modal
        card.addEventListener('click', () => openModal(movie));
        fragment.appendChild(card);
    });

    moviesGrid.appendChild(fragment);
}

// 3. Δημιουργία των κουμπιών (Φίλτρων) στην κορυφή
function renderTags() {
    tagsContainer.innerHTML = '';
    const sortedTags = Array.from(allTags).sort();
    
    sortedTags.forEach(tag => {
        const btn = document.createElement('button');
        btn.className = 'filter-tag';
        btn.textContent = tag;
        
        btn.addEventListener('click', () => {
            if (activeTags.has(tag)) {
                activeTags.delete(tag);
                btn.classList.remove('active');
            } else {
                activeTags.add(tag);
                btn.classList.add('active');
            }
            applyFilters();
        });
        
        tagsContainer.appendChild(btn);
    });
}

// 4. Η Μηχανή Αναζήτησης και Φιλτραρίσματος (Αστραπιαία)
function applyFilters() {
    const searchTerm = searchInput.value.toLowerCase().trim();
    
    filteredMovies = moviesData.filter(movie => {
        // Έλεγχος Αναζήτησης (Τίτλος, Σκηνοθέτης, Ηθοποιοί, Έτος)
        const searchableText = `
            ${movie.original_title || ''} 
            ${movie.greek_title || ''} 
            ${movie.director || ''} 
            ${movie.actors || ''} 
            ${movie.year || ''}
        `.toLowerCase();
        
        const matchesSearch = searchTerm === '' || searchableText.includes(searchTerm);
        
        // Έλεγχος Tags (Πρέπει να περιέχει ΟΛΑ τα επιλεγμένα tags - AND logic)
        let matchesTags = true;
        if (activeTags.size > 0) {
            if (!movie.tags) {
                matchesTags = false;
            } else {
                for (let tag of activeTags) {
                    if (!movie.tags.includes(tag)) {
                        matchesTags = false;
                        break;
                    }
                }
            }
        }
        
        return matchesSearch && matchesTags;
    });

    renderGrid(filteredMovies);
}

// 5. Λειτουργίες του Modal
function openModal(movie) {
    const title = movie.greek_title || movie.original_title;
    const posterSrc = movie.poster_url || 'https://via.placeholder.com/500x750/2a2a2a/ffffff?text=No+Poster';
    const duration = movie.duration_minutes ? `${movie.duration_minutes} λεπτά` : 'Άγνωστη διάρκεια';
    
    modalBody.innerHTML = `
        <img src="${posterSrc}" alt="${title}" class="modal-poster">
        <div class="modal-details">
            <h2>${title}</h2>
            ${movie.original_title && movie.original_title !== title ? `<p><strong>Πρωτότυπος Τίτλος:</strong> ${movie.original_title}</p>` : ''}
            <p><strong>Σκηνοθεσία:</strong> ${movie.director || '-'}</p>
            <p><strong>Ηθοποιοί:</strong> ${movie.actors || '-'}</p>
            <p><strong>Έτος:</strong> ${movie.year || '-'} • <strong>Διάρκεια:</strong> ${duration}</p>
            <p><strong>Τοποθεσία:</strong> Ράφι ${movie.shelf_id}</p>
            <div class="modal-synopsis">Φόρτωση σύνοψης...</div>
        </div>
    `;
    movieModal.classList.remove('hidden');
    document.body.style.overflow = 'hidden'; // Κλειδώνει το σκρολάρισμα της σελίδας

    const synopsisEl = modalBody.querySelector('.modal-synopsis');

    const displaySynopsis = (data) => {
        synopsisEl.textContent = data[movie.shelf_id] || 'Δεν υπάρχει διαθέσιμη σύνοψη.';
    };

    if (synopsesData) {
        displaySynopsis(synopsesData);
        return;
    }

    // Lazy loading: το synopses.json φορτώνεται μόνο την πρώτη φορά που ανοίγει modal.
    if (!synopsesPromise) {
        synopsesPromise = fetch('data/synopses.json')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                synopsesData = data;
                return data;
            })
            .catch(error => {
                synopsesPromise = null; // Επιτρέπει νέα προσπάθεια στο επόμενο άνοιγμα
                throw error;
            });
    }

    synopsesPromise
        .then(displaySynopsis)
        .catch(error => {
            console.error("Σφάλμα κατά τη φόρτωση των συνόψεων:", error);
            synopsisEl.textContent = 'Αποτυχία φόρτωσης σύνοψης.';
        });
}

closeModalBtn.addEventListener('click', () => {
    movieModal.classList.add('hidden');
    document.body.style.overflow = 'auto';
});

// Κλείσιμο modal αν κάνεις κλικ έξω από αυτό (στο μαύρο)
movieModal.addEventListener('click', (e) => {
    if (e.target === movieModal) {
        movieModal.classList.add('hidden');
        document.body.style.overflow = 'auto';
    }
});

// 6. Listeners
let searchTimeout;
searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(applyFilters, 300); // 300ms καθυστέρηση
});

// Ξεκινάμε!
fetchMovies();