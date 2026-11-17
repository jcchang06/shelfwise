# Shelfwise

A personal reading tracker with content-based recommendations and new-release email digests.

**Status:** Phase 1 (MVP tracker) in progress. The full spec is in [docs/PRD.md](docs/PRD.md).

## Stack

- **API:** Python 3.12, Django 5.2, Django REST Framework, JWT auth (simplejwt)
- **Database:** PostgreSQL 16 (Docker locally, Neon in production)
- **Frontend:** React, Vite, TypeScript, React Router, Chart.js
- **Tooling:** Docker Compose, ruff, pytest, ESLint, Prettier, Vitest, GitHub Actions

## Run it locally

Requires Docker.

```bash
cp .env.example .env      # set DJANGO_SECRET_KEY to a long random string
docker compose up
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createcachetable
```

`createcachetable` creates the table behind Django's database cache. It's needed once per database (local, and Neon in production). The cache holds book API responses, the Google Books quota flag and rate-limit counters. A database cache is used instead of an in-memory one because it's shared by every process and survives Render's free instance sleeping. Tests use an in-memory cache instead.

- API health check: http://localhost:8000/api/health/
- Frontend: http://localhost:5173

## API

All endpoints are under `/api/` and return JSON. Authenticated endpoints expect `Authorization: Bearer <access token>`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/health/` | none | Liveness check |
| POST | `/api/auth/register/` | none | Sign up with `email` and `password`; returns the user and a token pair |
| POST | `/api/auth/token/` | none | Log in; returns `access` and `refresh` tokens |
| POST | `/api/auth/token/refresh/` | none | Exchange `refresh` for a new `access` token |
| GET | `/api/auth/me/` | token | The logged-in user |
| GET | `/api/books/search/?q=…&page=1` | token | Search Google Books, falling back to Open Library |
| POST | `/api/books/` | token | Save a search result (`source`, `source_id`) to the catalog |
| GET | `/api/books/{id}/` | token | One catalog book |
| GET | `/api/shelf/?status=&book=&ordering=` | token | Your shelf, paginated, with pages logged per book |
| POST | `/api/shelf/` | token | Add `book_id` (or `source` + `source_id`) with an optional status; 409 if already shelved |
| GET / PATCH / DELETE | `/api/shelf/{id}/` | token | One entry: change status, rate, review or mark DNF; DELETE also removes its reading logs |
| GET | `/api/logs/?book=&from=&to=` | token | Your page logs, newest day first |
| POST | `/api/logs/` | token | Log `pages_read` for `book_id` (today by default); a second log the same day adds to it |
| GET / PATCH / DELETE | `/api/logs/{id}/` | token | One log; PATCH sets the day's total or moves it to another day |

Book data comes from [Google Books](https://books.google.com) and [Open Library](https://openlibrary.org). Search responses name their `source`, so the UI can show the right attribution.

## Tests and lint

```bash
docker compose exec backend pytest
docker compose exec backend sh -c "ruff check . && ruff format --check ."
cd frontend && npm run lint && npm run typecheck && npm test
```

CI runs all of the above on every pull request and on every push to `main`.

Tests never call external APIs. Every HTTP request is mocked with `responses`. The Google Books and Open Library fixtures in `backend/catalog/tests/fixtures/` are trimmed real responses. To refresh them, run this from `backend/`:

```bash
GOOGLE_BOOKS_API_KEY=... .venv/bin/python scripts/record_fixtures.py
```

This writes trimmed fixtures, which you commit, and full responses to `fixtures/raw/`, which is gitignored. The API key is stripped from saved URLs and bodies.

## Layout

```
backend/   Django project (config/) and apps: accounts, catalog, tracking
frontend/  React app; all HTTP calls go through src/api/
docs/      Product requirements
```
