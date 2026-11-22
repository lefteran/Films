// Global State (Η κατάσταση της εφαρμογής)
let moviesData = [];
let filteredMovies = [];
let activeTags = new Set();
let allGenres = new Set();
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
const gridSizeToggle = document.getElementById('gridSizeToggle');
const genreSelect = document.getElementById('genreSelect');

// Search / ordering helpers
function normalizeText(text) {
    if (typeof text !== 'string') return '';
    return text
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase();
}

function shuffleArray(array) {
    for (let i = array.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [array[i], array[j]] = [array[j], array[i]];
    }
    return array;
}

function initializeSearchFromURL() {
    const search = new URLSearchParams(window.location.search).get('search');
    if (search !== null) {
        searchInput.value = search;
    }
}

function updateSearchQueryParam(value) {
    const url = new URL(window.location.href);
    if (value.trim()) {
        url.searchParams.set('search', value);
    } else {
        url.searchParams.delete('search');
    }
    window.history.replaceState({}, '', url.toString());
}

function selectGenre(tag) {
    const value = typeof tag === 'string' ? tag.trim() : '';
    if (!value) return;

    activeTags.add(value);
    if (genreSelect) {
        genreSelect.value = '';
    }
    renderActiveGenrePills();
    applyFilters();
}

function renderActiveGenrePills() {
    if (!tagsContainer) return;
    tagsContainer.querySelectorAll('.active-genre-pill').forEach(el => el.remove());

    activeTags.forEach(tag => {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = 'active-genre-pill';
        pill.setAttribute('aria-label', `Αφαίρεση φίλτρου ${tag}`);

        const label = document.createElement('span');
        label.textContent = tag;
        const removeIcon = document.createElement('span');
        removeIcon.className = 'pill-remove';
        removeIcon.setAttribute('aria-hidden', 'true');
        removeIcon.textContent = '×';

        pill.appendChild(label);
        pill.appendChild(removeIcon);
        pill.addEventListener('click', () => {
            activeTags.delete(tag);
            renderActiveGenrePills();
            applyFilters();
        });

        tagsContainer.appendChild(pill);
    });
}

// 1. Φόρτωση των δεδομένων
async function fetchMovies() {
    try {
        const response = await fetch('data/movies_lite.json');
        moviesData = await response.json();
        filteredMovies = [...moviesData];
        
        // Εξαγωγή όλων των μοναδικών ειδών (genres) για το dropdown
        moviesData.forEach(movie => {
            if (Array.isArray(movie.genres)) {
                movie.genres.forEach(genre => {
                    const clean = typeof genre === 'string' ? genre.trim() : '';
                    if (clean) allGenres.add(clean);
                });
            }
        });
        
        renderTags();
        applyFilters();
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
        
        card.innerHTML = `
            <div class="poster-container">
                <img src="${posterSrc}" alt="${title}" class="movie-poster" loading="lazy" decoding="async">
                <div class="shelf-badge">${movie.shelf_id}</div>
            </div>
            <div class="movie-info">
                <h3 class="movie-title">${title}</h3>
                <div class="movie-meta">${movie.year || '-'} • ${movie.director || '-'}</div>
                <div class="card-tags"></div>
            </div>
        `;

        const cardTags = card.querySelector('.card-tags');
        const cardLabels = Array.isArray(movie.genres) && movie.genres.length > 0
            ? movie.genres
            : (Array.isArray(movie.tags) ? movie.tags : []);
        cardLabels.forEach(tag => {
            const badge = document.createElement('span');
            badge.className = 'card-tag';
            badge.textContent = tag;
            badge.setAttribute('role', 'button');
            badge.setAttribute('tabindex', '0');
            badge.addEventListener('click', (event) => {
                event.stopPropagation();
                selectGenre(tag);
            });
            badge.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    event.stopPropagation();
                    selectGenre(tag);
                }
            });
            cardTags.appendChild(badge);
        });

        // Όταν κάνει κλικ, ανοίγει το Modal
        card.addEventListener('click', () => openModal(movie));
        fragment.appendChild(card);
    });

    moviesGrid.appendChild(fragment);
}

// 3. Γέμισμα του dropdown ειδών (χωρίς κουμπιά filter-tag)
function renderTags() {
    const sortedGenres = Array.from(allGenres).sort((a, b) => a.localeCompare(b));

    if (genreSelect) {
        Array.from(genreSelect.options).forEach(option => {
            if (option.value !== '') option.remove();
        });
        sortedGenres.forEach(genre => {
            const option = document.createElement('option');
            option.value = genre;
            option.textContent = genre;
            genreSelect.appendChild(option);
        });
    }

    if (tagsContainer) {
        tagsContainer.querySelectorAll('.filter-tag').forEach(button => button.remove());
    }
    renderActiveGenrePills();
}

// 4. Η Μηχανή Αναζήτησης και Φιλτραρίσματος (Αστραπιαία)
function applyFilters() {
    const rawSearch = searchInput.value.trim();
    const searchTerm = normalizeText(rawSearch);
    
    filteredMovies = moviesData.filter(movie => {
        // Έλεγχος Αναζήτησης (Τίτλος, Σκηνοθέτης, Ηθοποιοί, List No., IMDb ID, Έτος, Είδη/Υποείδη)
        const searchableText = normalizeText(`
            ${movie.original_title || ''}
            ${movie.greek_title || ''}
            ${movie.director || ''}
            ${movie.actors || ''}
            ${Array.isArray(movie.tags) ? movie.tags.join(' ') : ''}
            ${Array.isArray(movie.genres) ? movie.genres.join(' ') : ''}
            ${Array.isArray(movie.subgenres) ? movie.subgenres.join(' ') : ''}
            ${movie.shelf_id || ''}
            ${movie.imdb_id || ''}
            ${movie.year || ''}
        `);
        
        const matchesSearch = searchTerm === '' || searchableText.includes(searchTerm);
        
        // Έλεγχος Tags (Πρέπει να περιέχει ΟΛΑ τα επιλεγμένα tags - AND logic)
        let matchesTags = true;
        if (activeTags.size > 0) {
            const movieLabels = new Set([
                ...(Array.isArray(movie.tags) ? movie.tags : []),
                ...(Array.isArray(movie.genres) ? movie.genres : []),
                ...(Array.isArray(movie.subgenres) ? movie.subgenres : [])
            ]);
            if (movieLabels.size === 0) {
                matchesTags = false;
            } else {
                for (let tag of activeTags) {
                    if (!movieLabels.has(tag)) {
                        matchesTags = false;
                        break;
                    }
                }
            }
        }
        
        return matchesSearch && matchesTags;
    });

    if (rawSearch === '') {
        filteredMovies = shuffleArray([...filteredMovies]);
    }

    renderGrid(filteredMovies);
}

// 5. Λειτουργίες του Modal
function openModal(movie) {
    const title = movie.greek_title || movie.original_title;
    const posterSrc = movie.poster_url || 'https://via.placeholder.com/500x750/2a2a2a/ffffff?text=No+Poster';
    const duration = movie.duration_minutes ? `${movie.duration_minutes} λεπτά` : 'Άγνωστη διάρκεια';
    
    const genres = Array.isArray(movie.genres) && movie.genres.length > 0
        ? movie.genres
        : (Array.isArray(movie.tags) ? movie.tags : []);
    const subgenres = Array.isArray(movie.subgenres) ? movie.subgenres : [];

    modalBody.innerHTML = `
        <img src="${posterSrc}" alt="${title}" class="modal-poster">
        <div class="modal-details">
            <h2>${title}</h2>
            ${movie.original_title && movie.original_title !== title ? `<p><strong>Πρωτότυπος Τίτλος:</strong> ${movie.original_title}</p>` : ''}
            <p><strong>Σκηνοθεσία:</strong> ${movie.director || '-'}</p>
            <p><strong>Ηθοποιοί:</strong> ${movie.actors || '-'}</p>
            <p><strong>Έτος:</strong> ${movie.year || '-'} • <strong>Διάρκεια:</strong> ${duration}</p>
            <p><strong>Θέση:</strong> List No. ${movie.shelf_id}</p>
            <p><strong>IMDb ID:</strong> ${movie.imdb_id || '-'}</p>
            ${genres.length > 0 || subgenres.length > 0 ? '<div class="modal-taxonomy"></div>' : ''}
            ${movie.imdb_id ? `<a href="https://www.imdb.com/title/${movie.imdb_id}/" target="_blank" rel="noopener noreferrer" class="imdb-link">Προβολή στο IMDb</a>` : ''}
            <div class="modal-synopsis">Φόρτωση σύνοψης...</div>
        </div>
    `;

    const taxonomyEl = modalBody.querySelector('.modal-taxonomy');
    if (taxonomyEl) {
        const appendBadgeGroup = (labelText, items, badgeClass) => {
            if (items.length === 0) return;
            const group = document.createElement('div');
            group.className = 'modal-taxonomy-group';

            const label = document.createElement('span');
            label.className = 'modal-taxonomy-label';
            label.textContent = labelText;
            group.appendChild(label);

            const list = document.createElement('div');
            list.className = 'modal-badges';
            items.forEach(item => {
                const badge = document.createElement('button');
                badge.type = 'button';
                badge.className = `modal-badge ${badgeClass}`;
                badge.textContent = item;
                badge.addEventListener('click', () => {
                    movieModal.classList.add('hidden');
                    document.body.style.overflow = 'auto';
                    selectGenre(item);
                });
                list.appendChild(badge);
            });
            group.appendChild(list);
            taxonomyEl.appendChild(group);
        };

        appendBadgeGroup('Είδη', genres, 'genre-badge');
        appendBadgeGroup('Υποείδη', subgenres, 'subgenre-badge');
    }

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
    updateSearchQueryParam(searchInput.value);
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(applyFilters, 300); // 300ms καθυστέρηση
});

if (genreSelect) {
    genreSelect.addEventListener('change', () => {
        if (genreSelect.value) {
            selectGenre(genreSelect.value);
        } else {
            activeTags.clear();
            renderActiveGenrePills();
            applyFilters();
        }
    });
}

function syncGridToggleState() {
    const isSmall = moviesGrid.classList.contains('small-grid');
    gridSizeToggle.setAttribute('aria-pressed', String(isSmall));
    gridSizeToggle.setAttribute('aria-label', isSmall ? 'Εμφάνιση μεγάλων αφισών' : 'Εμφάνιση μικρών αφισών');
}

syncGridToggleState();

gridSizeToggle.addEventListener('click', () => {
    moviesGrid.classList.toggle('small-grid');
    syncGridToggleState();
});

// Ξεκινάμε!
initializeSearchFromURL();
fetchMovies();