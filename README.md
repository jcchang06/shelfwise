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

Copy `.env.example` to `.env`, then set `DJANGO_SECRET_KEY` in it to a long random string.

```bash
cp .env.example .env
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
| GET | `/api/stats/?year=` | token | Dashboard numbers for a year: pages per month, books per year, genre mix, ratings |

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

## Deploy

The API runs on a free Render web service, set up from [`render.yaml`](render.yaml), with a free Neon Postgres database. Both cost $0. On the free plan:
- **The service sleeps after 15 minutes idle**, and the first request after that takes about a minute.
- **There's no pre-deploy step, shell or one-off job.** So migrations run in the build command, and you create your account from your own machine.

Do these steps once, in this order.

1. **Google Cloud (recommended).** Restrict your API key to the Books API only, under APIs & Services → Credentials → your key → API restrictions. IP restriction isn't possible, because Render's outbound addresses change.

2. **Neon.**
   1. Create a project called `shelfwise` with **Postgres 16** in **AWS US West 2 (Oregon)**, the same region as the Render service.
   2. Copy the **direct** connection string, not the `-pooler` one: `postgresql://…@ep-….us-west-2.aws.neon.tech/neondb?sslmode=require`.

3. **Merge to `main`**, so `render.yaml` is there.

4. **Set up the Neon database from your machine.** Run these from `backend/` in zsh:

   ```zsh
   read -rs "DATABASE_URL?Paste Neon URL: "; export DATABASE_URL; echo
   .venv/bin/python manage.py dbinfo
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py createcachetable
   .venv/bin/python manage.py createsuperuser
   unset DATABASE_URL
   ```

   - **The URL never reaches your shell history:** `read -rs` doesn't echo the paste and keeps it out of history, and `unset` clears it at the end.
   - **The exported `DATABASE_URL` overrides the one in your local `.env`.** Settings load `.env` with `overwrite=False`, so a variable already in the environment wins. `config/tests/test_settings_env.py` proves this.
   - **`dbinfo` must print the `ep-….neon.tech` host.** If it prints `localhost`, stop: the variable wasn't exported.
   - **`createsuperuser`** creates your login, with admin access.
   - **The commands have no inline `#` comments**, because interactive zsh doesn't treat `#` as a comment by default (`INTERACTIVE_COMMENTS` is off) and would pass the words as arguments.

5. **Render.**
   1. Go to Dashboard → New → **Blueprint** → choose this repository. Render reads `render.yaml`.
   2. Render then asks for three values. Enter `DATABASE_URL` (the Neon URL) and `GOOGLE_BOOKS_API_KEY`.
   3. Enter `CORS_ALLOWED_ORIGINS` as `http://localhost:5173` until the frontend is deployed.

   Everything else is in `render.yaml`:
   - `DJANGO_SECRET_KEY` is generated by Render.
   - `DJANGO_DEBUG=false` and `TIME_ZONE=America/Los_Angeles` are set.
   - `ALLOW_SIGNUP=false` keeps sign-up closed. You already created your account in step 4.

   The build log shows `Database: ep-….neon.tech…` before migrating.

6. **Check it works.**
   - `https://shelfwise-api-et8p.onrender.com/api/health/` returns `{"status":"ok"}`.
   - `POST /api/auth/token/` with your email and password returns tokens.
   - `/admin/` loads with styling.

**The live API is at `https://shelfwise-api-et8p.onrender.com`.** The service is named `shelfwise-api` in `render.yaml`; Render added `-et8p` to the hostname because `shelfwise-api` was taken.

**After that:**
- **Deploys happen automatically** when CI passes on `main`, and only for changes under `backend/` or to `render.yaml`. Migrations run during the build, so keep them backwards-compatible: if a deploy fails after migrating, the old code keeps running against the new schema.

### Frontend (static site)

The `shelfwise` static site in `render.yaml` builds `frontend/` and publishes `frontend/dist`. It's free, served from Render's CDN, and doesn't sleep. In `render.yaml`:
- **`NODE_VERSION`** is set to `22`, because new services default to Node 24.
- **`VITE_API_BASE_URL`** is set to `https://shelfwise-api-et8p.onrender.com/api`. A production build without an https URL fails.
- **A single-page-app rewrite** sends `/*` to `/index.html`.
- **Security and caching headers** are set (listed below).

1. **Merge to `main`.** The Blueprint sync creates the new static site; there's nothing to enter. Check Dashboard → Blueprints if it doesn't appear.
2. **Note the site's URL**, for example `https://shelfwise.onrender.com`. Render may add a suffix, as it did for the API.
3. **Allow it in the API's CORS settings.** In the **API** service (`shelfwise-api`), go to Environment and set `CORS_ALLOWED_ORIGINS` to `https://<frontend-host>,http://localhost:5173`, keeping localhost for `npm run dev:live`. Saving redeploys the API.
4. **Check it works:**
   - log in on the live site
   - reload `/dashboard` directly, which checks the rewrite
   - look at the browser console for CSP or CORS errors

**If the Blueprint sync rejects `routes` or `headers`,** remove them from `render.yaml` and add the same rules in the dashboard under the static site → **Redirects/Rewrites** and → **Headers**:

| Kind | Source / path | Destination / name | Value |
| --- | --- | --- | --- |
| Rewrite | `/*` | `/index.html` | |
| Header | `/assets/*` | `Cache-Control` | `public, max-age=31536000, immutable` |
| Header | `/*` | `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://books.google.com https://*.googleusercontent.com https://covers.openlibrary.org https://archive.org https://*.archive.org; connect-src 'self' https://shelfwise-api-et8p.onrender.com; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'` |
| Header | `/*` | `X-Content-Type-Options` | `nosniff` |
| Header | `/*` | `Referrer-Policy` | `same-origin` |
| Header | `/*` | `X-Frame-Options` | `DENY` |
| Header | `/*` | `Strict-Transport-Security` | `max-age=86400` |

**If the API's URL ever changes,** update `VITE_API_BASE_URL` and the CSP's `connect-src` together in `render.yaml`.

## Layout

```
backend/   Django project (config/) and apps: accounts, catalog, tracking
frontend/  React app; all HTTP calls go through src/api/
docs/      Product requirements
```
