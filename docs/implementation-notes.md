# Implementation notes

Decisions made while building, which aren't in the PRD. These are the source of truth for the steps they name. Requirement IDs refer to `docs/PRD.md`.

## Data model (decided Nov 16, 2026)

- **Partial publish dates.** `Book.published_date` stores the earliest day that matches what the API gave, so `"2014"` becomes `2014-01-01` and `"2014-03"` becomes `2014-03-01`. `published_date_precision` records whether that was a year, month or day. Parsing is done by `catalog.dates.parse_partial_date`. The UI shows `published_date_display`.
- **External IDs.** `google_books_id` and `open_library_key` are both unique but nullable. `isbn_13` is indexed but not unique, because Google Books can return two volume IDs for the same ISBN.
- **Series numbers** are decimals, so novellas like 2.5 fit.
- **Deleting books.** A `Book` can't be deleted while any shelf entry or reading log points at it. Deleting a user removes their shelf and logs.

## T-1: Auth (built Nov 16, 2026)

- **Endpoints**, all under `/api/auth/`:
  - `register/` (POST, open to anyone): returns the user plus a token pair, so you're logged in right after signing up
  - `token/` (POST): log in with email and password
  - `token/refresh/` (POST): exchange a refresh token for a new access token
  - `me/` (GET, needs a token)
- **Emails are stored fully lowercased** and matched without regard to case at login. Lowercasing happens in `UserManager.normalize_email` and again in `User.save()`, so admin forms are covered too. There's no database constraint on lowercase email, so this needed no migration.
- **Turning off sign-up:** setting `ALLOW_SIGNUP=false` makes registration return 403. Set it in production once your account exists.
- **Rate limit:** sign-up, login and refresh share an `auth` limit set by `AUTH_THROTTLE_RATE` (default 10 per minute).
- **Token lifetimes:** access tokens last 15 minutes and refresh tokens 7 days. Both are set by environment variables.
- **Refresh token rotation is on** (`ROTATE_REFRESH_TOKENS`). Each `POST /api/auth/token/refresh/` returns a new refresh token along with the access token, so daily use keeps sliding the 7-day window forward instead of forcing a weekly re-login. The frontend must save the new refresh token from every refresh response.
- **No blacklist in v1, so old refresh tokens stay valid until they expire.** Rotation issues new tokens but doesn't revoke the old ones. A leaked refresh token works for up to 7 days after it was issued, even if newer ones exist. A test documents this.
- **No server-side logout.** The frontend logs out by discarding its tokens.
- **Possible later upgrade:** add simplejwt's `token_blacklist` app, which is a migration, with `BLACKLIST_AFTER_ROTATION = True`, plus a `POST /api/auth/logout/` that blacklists the refresh token. That would revoke used and logged-out tokens. Worth doing before a public beta.

## C-1 / C-2: Book search and catalog save (decided Nov 16, 2026)

- **Sources.** Search tries Google Books first. It falls back to Open Library when Google raises an error, times out, is over quota or returns no results. An empty answer from Google still beats an error from Open Library. The code is in `catalog/services/`.
- **Google request parameters:** `printType=books`, `langRestrict=$BOOK_SEARCH_LANGUAGE` (default `en`), and 20 results per page. A query that is an ISBN-10 or ISBN-13 is sent as `isbn:` to both APIs.
- **Timeouts and retries:** calls made during a user request get one retry (GET only, on 429 and 5xx) with 3s connect / 5s read timeouts. Background jobs will pass `retries=3`.
- **Google quota:** a 429, or a 403 with a `*LimitExceeded` reason, sets `google_books:quota_exhausted` in the shared database cache until the next midnight Pacific. While it's set, calls skip Google entirely.
- **Caching:** Django's database cache, which needs `createcachetable`. Search pages are cached for 24 hours. Google volumes and Open Library works are cached for 7 days. Failures are never cached. Tests use locmem.
- **Cleaning the data:**
  - **Descriptions:** block tags become line breaks, then `strip_tags`, then `html.unescape`.
  - **Google genres:** categories are split on `/`, "General" is dropped, and duplicates are removed.
  - **Open Library genres:** subjects are filtered for catalog noise and capped at 10.
  - **Covers:** forced to https.
- **Saving (`get_or_create_book`):**
  1. A book with the same source ID is returned without calling the API.
  2. Otherwise, the oldest book with the same ISBN-13 is reused. Only its empty fields and missing source ID are filled in.
  3. Otherwise, a new book is created.
- **Choosing an ISBN-13:**
  - **The problem:** Open Library's search `isbn` list mixes every edition in no useful order. Project Hail Mary's list starts with a Spanish edition, `9788418037016`.
  - **The rule:** when `BOOK_SEARCH_LANGUAGE` is `en`, the first ISBN-13 starting with `9780`, `9781` or `9798` wins. `9791…` is France, Korea or Italy, so it's deliberately excluded. If none match, or the language is anything else, the first valid ISBN-13 is used.
  - **Scope:** the rule applies to both sources, and the code is in `normalize.first_isbn_13`.
- **Duplicates can still happen across sources.** ISBN matching only merges a Google book and an Open Library book when both carry the *same* ISBN-13. When the sources choose different editions, for example two English editions with different ISBNs, or a book where one source has no ISBN, the same work becomes two catalog rows. Matching by normalized title plus first author is planned for the Phase 2 Goodreads import, where it's needed anyway. Existing duplicates can be merged then.
- **Matching authors:**
  - **By key first:** if the source gives an Open Library author key, match on that.
  - **Then by name:** otherwise match on the normalized name, picking the oldest match. Normalizing means lowercasing, turning periods into spaces, collapsing spaces, then joining runs of single-letter initials. "J.R.R. Tolkien", "J. R. R. Tolkien" and "JRR Tolkien" all become `jrr tolkien`. A lone middle initial stays put, so "Ursula K. Le Guin" becomes `ursula k le guin`.
  - **Filling in a key:** a keyless author whose name matches gets the key.
  - **Different keys:** an author with a different key is treated as a different person.
- **Author lookup cost:** the name match scans the authors table using a Postgres expression. If the C-3 seed makes this slow, add an indexed `name_normalized` column, which needs a migration.
- **Open Library User-Agent:** `OPEN_LIBRARY_USER_AGENT` (default `Shelfwise/0.1 (+https://github.com/jcchang06/shelfwise)`).
- **Endpoints**, all requiring login:
  - **`GET /api/books/search/?q=&page=`**
    - `q` must be 2 to 200 characters after trimming, and `page` must be 1 to 10.
    - The response is `{source, page, next_page, results[]}`. Each result carries `book_id` when it's already in the catalog.
    - `next_page` is null unless the page was full. The endpoint uses a page number rather than DRF pagination, because results don't come from a database queryset.
    - Rate limited per user by `BOOK_SEARCH_THROTTLE_RATE` (30 per minute).
    - Returns 503 if both sources are down.
  - **`POST /api/books/ {source, source_id}`**
    - Returns 201 for a new book and 200 if it's already in the catalog.
    - Returns 404 if the source has no such book, and 503 if the source is unreachable or Google is over quota.
    - `source_id` is checked against a strict pattern (Google: `[A-Za-z0-9_-]{1,32}`; Open Library: `OL\d+W`) because it goes into the API URL path.
  - **`GET /api/books/{id}/`** returns one book, with its authors in credit order.
- **Open Library save** makes two calls: `works/{key}.json` for the description, and `search.json?q=key:/works/{key}` for authors, ISBN, page count and year.

## T-2 / T-4 / T-6: Shelf API (decided Nov 16, 2026)

The rules live in `tracking/services.py` (`apply_shelf_changes`). The serializers only check types.

### Endpoints

All are under `/api/shelf/`, all require login, and all are filtered to `request.user`. Another user's entry returns 404.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/shelf/?status=&book=&ordering=` | Paginated list. `ordering` is one of `-updated_at` (default), `title`, `-finished_at`, `-created_at` |
| POST | `/api/shelf/` | Add `{book_id}` or `{source, source_id}`, the second form saving to the catalog first. Optional `status` (default `want_to_read`) and fields. Returns 201, or **409 with the existing entry's `id`** if the book is already on the shelf |
| GET / PATCH / DELETE | `/api/shelf/{id}/` | PATCH only, no PUT. DELETE returns 204 |

- **Each entry includes `pages_logged` and `reading_log_count`.** `pages_logged` covers only the current read (see T-3); `reading_log_count` covers every log for the book.
- **Removing a book** is a plain DELETE that also deletes the user's `ReadingLog` rows for that book. The frontend asks for confirmation first and uses `reading_log_count` in the message.

### Status changes

Side effects only happen when the status actually changes. Values sent in the request always win over these defaults.

| Change | Side effects |
| --- | --- |
| `finished` → `reading` | `started_at` = today, **overwriting** the first read's start, because a re-read is a new read |
| `want_to_read` → `reading` | `started_at` = today only if empty |
| `dnf` → `reading` | `started_at` is **kept**, because resuming continues the same read. Filled with today only if empty |
| any → `finished` | `finished_at` = today, **overwriting** an earlier date, so a re-read marked finished again gets the new date |
| any → `dnf` | **rating cleared**, because stars and a DNF don't mix. `finished_at` is kept. `dnf_at` = today. `dnf_page` = pages logged in the current read (see T-3), capped at `page_count`, or null if there are none. `dnf_reason` is required |
| `dnf` → any | all DNF fields cleared (`dnf_page`, `dnf_at`, `dnf_reason`, `dnf_note`). Logs are kept |
| `finished` → `reading` / `want_to_read` | **rating and `finished_at` kept.** A re-read mustn't erase a 5★ that drives recommendations and auto-follow |

### Validation (400, with every broken rule reported at once)

- **Only editable fields may be sent.** `POST /api/shelf/` and `PATCH /api/shelf/{id}/` reject unknown and read-only fields with a 400 (`{field: ["This field can't be set here."]}`), rather than silently ignoring them as DRF does by default. The editable fields are `status`, `rating`, `review`, `started_at`, `finished_at`, `dnf_page`, `dnf_at`, `dnf_reason` and `dnf_note`, plus `book_id` or `source` + `source_id` on POST. Read-only fields such as `id`, `book`, `pages_logged`, `reading_log_count`, `created_at` and `updated_at` must not be sent back. **The frontend must send only the fields it means to change**, never a whole entry from a GET.
- **Rating (T-4)** can only be **set or changed** when the status after the request is `finished`.
  - Re-sending the current value is fine, so a form can send its rating field unchanged.
  - Sending `null` while moving to `dnf` is also fine.
  - A kept rating can't be changed or cleared during a re-read until the book is finished again.
- **Reviews** are allowed on any status.
- **DNF fields** are only accepted when the status after the request is `dnf`. Blank values are accepted as no-ops.
- **`dnf_reason`** is required for `dnf` and can't be blanked. The database enforces this too.
- **`dnf_page`** must be no more than the book's `page_count` when that's known. The default worked out from logs is capped rather than rejected.
- **Dates** (`started_at`, `finished_at`, `dnf_at`) can't be after today.
- **`started_at` must be on or before `finished_at`**, but this is only checked when the status after the request is `finished`. During a re-read, `finished_at` is still the previous read's date.
- **"Today"** is `timezone.localdate()` in `TIME_ZONE` (an environment variable, default `America/Los_Angeles`). Timestamps are still stored in UTC.

### Notes for later phases

- **T-5 stats:** a re-read in progress has status `reading` but keeps its old `finished_at`. "Books finished per year" should count `status = finished` by `finished_at`, not every row with a `finished_at`. v1 doesn't keep a history of each read.
- **R-2 and N-1:** a kept rating on a re-read still counts as "rated 4★+". DNF books never have a rating.

## T-3: Page logs (decided Nov 16, 2026)

The rules live in `tracking/reading_logs.py` (`log_pages`, `update_log`).

### Endpoints

All are under `/api/logs/`, all require login, and all are filtered to `request.user`. Another user's log returns 404. Unknown and read-only fields are rejected, as on the shelf endpoints.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/logs/?book=&from=&to=` | Paginated, newest day first |
| POST | `/api/logs/` `{book_id, pages_read, log_date?}` | `log_date` defaults to today. If that book and day already have a log, `pages_read` is **added** to it. Returns 201 for a new row, 200 when added to an existing one |
| PATCH | `/api/logs/{id}/` `{pages_read?, log_date?}` | **Sets** the day's total, or moves the log to another day |
| DELETE | `/api/logs/{id}/` | 204. Shelf status and dates are unchanged |

**Responses** to POST and PATCH include the log plus a short shelf entry, `shelf_entry: {id, status, started_at, pages_logged}`, so the UI can update progress and show "moved to Reading" without a second request. `shelf_entry` is null for a log with no shelf entry, which can only happen for logs created in the admin. GET responses return the log fields only.

**Errors** come back as 400 `{field: [message]}`. When a PATCH tries to move a log onto a taken day, the response also has `conflict_id`, the other log's `id` **as an integer**. That response is built directly, because DRF's `ValidationError` would turn it into a string.

### Rules

- **One row per user, book and day.** The database enforces this. Same-day POSTs for one book can't overwrite each other, because the shelf entry row is locked for the duration of the update.
- **The book must be on your shelf.** Otherwise the response is 400 "Add this book to your shelf first."
- **`pages_read`** must be from 1 to `MAX_PAGES_PER_DAY` (environment variable, default 2000). The limit applies to the day's total *after* adding. To clear a day, DELETE the log.
- **`log_date`** can't be after today (in `TIME_ZONE`).
- **PATCH moving a log onto a day that already has one** for that book returns 400 with the existing log's `id`. The UI tells you to edit that day instead. Days are never merged.
- **What happens to the shelf entry:**

| Shelf status when logging | Effect |
| --- | --- |
| `want_to_read` | moves to `reading`; `started_at` = the log's date if empty (POST only) |
| `reading`, `finished`, `dnf` | no status change. Logging past days is allowed, and resuming a DNF book is a deliberate shelf PATCH |

- **Backfilling moves `started_at` back.** This applies to a POST, or a PATCH that changes `log_date`. When the log's date is earlier than the entry's `started_at`, `started_at` moves back to that date, **unless** the date is on or before the *previous read's* `finished_at`, in which case the log belongs to an earlier read and `started_at` stays.
  - **"Previous read's `finished_at`"** means a `finished_at` earlier than `started_at`, which only happens during a re-read. For a finished first read (`started_at` ≤ `finished_at`), a backfill before the start still moves `started_at` back.
  - **`started_at` never moves forward automatically.** It doesn't when a log is deleted or moved to a later day, and it isn't invented for a `reading`, `finished` or `dnf` entry that has none.

### The current read (affects T-2 too)

- **`pages_logged`** on shelf and log responses, and **the DNF page default**, count only logs dated on or after the entry's `started_at`, or all logs if `started_at` is empty. After a re-read, progress starts again from zero instead of going past 100%, and a DNF on the second read doesn't include the first read's pages.
- **`reading_log_count`** still counts *every* log for the book, because removing the book deletes all of them.

## Frontend foundation (decided Nov 16, 2026)

- **Routes:**
  - `/login` is public. There's no sign-up page in Phase 1, because production has sign-up turned off.
  - Everything else sits behind `RequireAuth` and `AppShell` (skip link, navigation, `<main id="main">`).
  - Logged-out visitors go to `/login` and come back to the page they asked for after logging in.
  - Unknown paths show a not-found page.
- **Tokens** (`src/api/tokens.ts`):
  - **Access token:** **memory only**.
  - **Refresh token:** **`localStorage`**. Every storage call is wrapped in try/catch, so a blocked-storage browser still works for the life of the tab.
  - **Why not httpOnly cookies:** the frontend and API are on different `onrender.com` subdomains. `onrender.com` is a public suffix, so a refresh cookie would be third-party and blocked by Safari and Chrome. Revisit with a custom domain.
  - **Limiting XSS risk:** a strict CSP on the static site, no third-party scripts, and React's escaping.
- **Refresh** (`src/api/client.ts`):
  - **On a 401,** one **shared** refresh runs for all waiting requests, the **rotated** refresh token is saved, and the request is retried once.
  - **After a reload,** with no access token yet, the client refreshes *before* the first request instead of spending a round trip on a guaranteed 401.
  - **A rejected refresh** (400 or 401) clears the tokens and calls the session-expired handler. The `AuthProvider` clears the query cache and the login page shows "Your session expired."
  - **A network failure during refresh** keeps the tokens.
- **Errors** (`src/api/errors.ts`):
  - **`ApiError`** has `status` (0 for network or timeout), `body` and `kind` (`http` | `network` | `timeout`).
  - **`fieldErrors()`** turns `{field: [msg]}` into one message per field.
  - **`formError()`** returns `detail`, `non_field_errors`, a 429, network, timeout or 5xx message, or null when field errors cover everything.
  - **`conflictId()`** returns the 409 `id` or the log `conflict_id`.
  - **Forms** link each field's error with `aria-describedby` and `aria-invalid`, plus an error summary with `role="alert"`.
- **Cold starts:** `trackRequest()` marks any request pending for 3+ seconds. `ServerWakingBanner` sits outside the routes, so it also shows **on `/login` and while a stored session is restored**: "Waking up the server — this can take up to a minute." Requests time out after 90 seconds.
- **Data loading:** TanStack Query. 4xx responses are never retried, network errors and 5xx are retried once, and data is fresh for 30 seconds. Tests mock the API with MSW, and any request without a handler fails the test.

