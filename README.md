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
```

- API health check: http://localhost:8000/api/health/
- Frontend: http://localhost:5173

## Tests and lint

```bash
docker compose exec backend pytest
docker compose exec backend sh -c "ruff check . && ruff format --check ."
cd frontend && npm run lint && npm run typecheck && npm test
```

CI runs all of the above on every push.

## Layout

```
backend/   Django project (config/) and apps: accounts, catalog, tracking
frontend/  React app; all HTTP calls go through src/api/
docs/      Product requirements
```
