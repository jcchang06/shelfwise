# Shelfwise

A personal reading tracker with content-based recommendations and new-release email digests. The full product spec is in `docs/PRD.md`: read it before starting any feature, and treat its requirement IDs (T-1, C-2, R-5 …) as the source of truth for scope. Decisions made during the build, such as API behavior for T-2 and T-3, are in `docs/implementation-notes.md`. Read the section for a step before starting it.

Version 1 has exactly one user (me), must cost $0/month to host, and doubles as a portfolio project, so code quality, tests and a clear README matter as much as features.

## Current phase

**Phase 2: Goodreads CSV import (I-1 to I-4) in progress.** Phase 1 features are built and deployed. I'm doing Phase 2 in parallel with my week of daily use of Phase 1 (its gate) and will send small fixes as I find them.

**Phase 3 (recommendations) is blocked** until I've used the app for about a week and the fixes I found are done. Don't start it until I say so.

Phase order (see `docs/PRD.md` → Milestones):
1. MVP tracker: auth, book search, shelf (incl. DNF), page logs, ratings, dashboard
2. Goodreads CSV import
3. Recommendations (TF-IDF)
4. Release alerts (daily digest email)
5. Polish

## Stack (decided, don't change without asking)

- **Backend:** Python 3.12, Django 5, Django REST Framework, `djangorestframework-simplejwt` for JWT auth
- **Database:** PostgreSQL. Local: Docker Compose. Production: Neon (connection via `DATABASE_URL`, parse with `dj-database-url`)
- **Frontend:** React + Vite + TypeScript, Chart.js (via `react-chartjs-2`), React Router
- **Jobs:** plain Django management commands. Locally they may also run through Celery + Redis in Docker Compose; in production they run from GitHub Actions cron. Every job must work as `python manage.py <command>` with no Celery dependency.
- **ML (Phase 3):** scikit-learn TF-IDF + cosine similarity
- **Email (Phase 4):** Resend over SMTP via Django's email backend. Email only, no Discord/Slack in v1, but send through a small `NotificationChannel` interface so other channels can be added later.
- **Hosting:** Render free web service (API) + Render static site (frontend) + Neon free Postgres
- **CI:** GitHub Actions: lint + tests on every push

## Repo layout

```
shelfwise/
├── CLAUDE.md
├── docs/PRD.md
├── docker-compose.yml        # postgres, redis, backend, frontend (dev)
├── .github/workflows/        # ci.yml; later jobs-daily.yml, jobs-nightly.yml
├── backend/
│   ├── manage.py
│   ├── config/               # settings (base/dev/prod or env-driven), urls, celery.py
│   ├── accounts/             # users, auth, email-alert preference
│   ├── catalog/              # books, authors, book_authors; services/google_books.py, services/open_library.py
│   ├── tracking/             # user_books, reading_logs, stats.py
│   ├── imports/              # Phase 2
│   ├── recommendations/      # Phase 3
│   └── notifications/        # Phase 4
└── frontend/
    └── src/{api,pages,components}
```

## Data model rules

- `Book`: `google_books_id` (unique, nullable), `open_library_key` (nullable), `isbn_13`, title, description, `genres` (JSON list), `page_count`, `published_date`, `cover_url`, **`series_name`, `series_number`** (nullable; create the columns in Phase 1 even though series features are P2).
- `Author` ↔ `Book` many-to-many through `BookAuthor`.
- `UserBook`: one row per (user, book), unique together. `status` is a `TextChoices`: `want_to_read`, `reading`, `finished`, `dnf`. Fields: `rating` (1–5, nullable), `review`, `started_at`, `finished_at`, and DNF fields `dnf_page`, `dnf_at`, `dnf_reason` (`TextChoices`: `writing_style`, `pacing`, `content`, `not_my_genre`, `not_in_the_mood`, `other`), `dnf_note`. A DNF book can move back to `reading`.
- `ReadingLog`: user, book, `log_date`, `pages_read`.
- Every queryset over user data (shelf, reading logs, and later recommendations, followed authors and alerts) must be filtered to `request.user`. Never return another user's data. The catalog (`Book`, `Author`) is shared and not per-user, but its endpoints still require login.
- DNF weights for recommendations live in settings (`DNF_REASON_WEIGHTS = {"writing_style": 1.0, "not_my_genre": 1.0, "pacing": 0.5, "content": 0.5, "not_in_the_mood": 0.0, "other": 0.5}`), not hard-coded in the engine.

## External APIs

- Use only official APIs: Google Books (`GOOGLE_BOOKS_API_KEY`, 1,000 requests/day) and Open Library (no key). **Never scrape** Goodreads or any website.
- Wrap each API in a service module with timeouts, retries with backoff, and response caching. Tests must mock all HTTP calls (use `responses` or `requests-mock`); tests never hit the network.
- Prefer doing slow external calls in jobs, not inside request handlers. Exception: book search (C-1) is user-initiated and may call Google Books directly, with caching.

## Conventions

- Settings from environment variables only (`django-environ` or `os.environ`). Keep `.env.example` updated with every variable; never commit `.env` or secrets.
- Python: `ruff` for lint + format, type hints on service functions, `pytest` + `pytest-django` + `factory_boy`. Target 70%+ backend coverage.
- Frontend: ESLint + Prettier, TypeScript strict, small components, all API calls go through `src/api/`.
- API: REST, JSON, versioned under `/api/`. Paginate list endpoints.
- Accessibility: keyboard-navigable UI, labels on inputs, charts get a text summary.
- Keep migrations small and committed. Don't edit old migrations.

## Commands

(Keep this section accurate.) Versions are pinned in `.python-version` (3.12) and `.nvmrc` (22).

```bash
cp .env.example .env                      # once; then set DJANGO_SECRET_KEY
docker compose up                         # full dev stack: API :8000, frontend :5173
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createcachetable   # once per database (DB cache)
docker compose exec backend python manage.py run_import <id>   # process one Goodreads import
docker compose exec backend python manage.py run_pending_imports  # what the nightly job runs
docker compose exec backend python manage.py merge_duplicate_books --dry-run  # then --apply <token>
docker compose exec backend python manage.py makemigrations <app>
docker compose exec backend pytest        # runs with coverage, fails under 70%
docker compose exec backend sh -c "ruff check . && ruff format --check ."

# Backend without Docker for the app (Postgres still from compose: docker compose up -d postgres)
cd backend && uv venv -p 3.12 .venv && uv pip install -r requirements-dev.txt
.venv/bin/pytest

# Frontend
cd frontend && npm run dev                # or: lint, format, format:check, typecheck, test, build
```

## How to work with me

- Work in small steps: one requirement or one layer at a time. After each step, run tests and lint, then summarize what changed and what's next.
- Before a large change (new app, new dependency, schema change), explain the plan in a few lines and wait for my OK.
- Write tests alongside code, not at the end.
- Commit and push to GitHub as you go (see Git workflow below).
- If something in `docs/PRD.md` is ambiguous or seems wrong, ask instead of guessing, and suggest the PRD change.
- Explain non-obvious decisions briefly in code comments or the PR/commit message; I'll use them in interviews.

## Git workflow

The repo is on GitHub at `https://github.com/jcchang06/shelfwise` (`origin`, default branch `main`, public so GitHub Actions minutes are free). Use `git` and the `gh` CLI.

- **First-time setup:** if `git remote -v` shows no `origin`, run `gh auth status`. If logged in as `jcchang06`, make the initial commit on `main` (`chore: add CLAUDE.md and PRD`) and run `gh repo create jcchang06/shelfwise --public --source=. --remote=origin --push`. If not logged in, stop and ask me to run `gh auth login`. If the repo already exists on GitHub, add it as `origin` instead of creating it.

- **Branch per step:** start each step from an up-to-date `main` on a branch named after it, e.g. `feat/t2-shelf-dnf`, `chore/scaffold`, `fix/search-cache`.
- **Commit when a step is green:** after tests and lint pass, stage only the files for that step and commit with a conventional message that names the requirement ID: `feat(tracking): add DNF status and reason (T-2, T-6)`. Several small commits per branch are fine.
- **Push and open a PR:** `git push -u origin <branch>`, then `gh pr create --fill --base main`. The PR description says what changed, which requirement IDs it covers, how it was tested, and any follow-ups. Then tell me the PR link.
- **I merge.** Don't merge PRs, push directly to `main`, or delete branches unless I ask. After I say it's merged: `git checkout main && git pull`.
- **Never:** force-push, rewrite pushed history, commit `.env` or any secret/API key, commit `node_modules`, `__pycache__`, build output or uploaded CSVs. Check `git status` and the staged diff before every commit.
- If CI fails on a PR, fix it on the same branch and push again.
