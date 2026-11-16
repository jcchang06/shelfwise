"""Clients for external book APIs and the catalog save logic (C-1, C-2).

Layout:
- types.py         BookResult, the one shape every source is normalized into, plus errors
- normalize.py     pure helpers: descriptions, genres, ISBNs, author names, cover URLs
- http.py          shared requests session (timeouts, retries, User-Agent)
- google_books.py  Google Books client (primary source)
- open_library.py  Open Library client (fallback)
- search.py        search_books(): Google first, Open Library as fallback
- catalog.py       get_or_create_book(): save a search result into the shared catalog
"""
