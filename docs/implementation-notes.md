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
- **Google quota:** only the daily limit (a `dailyLimitExceeded` reason, a "per day" message, or an older-style 403 with a `*LimitExceeded` reason) sets `google_books:quota_exhausted` in the shared database cache until the next midnight Pacific. While it's set, calls skip Google entirely. Any other 429 is a short-term rate limit; see "Measuring against the real export" below.
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
    - The response is `{source, page, next_page, results[]}`. Each result carries `book_id` when it's already in the catalog, and `shelf: {id, status}` when it's on the caller's shelf (otherwise null).
    - **`book_id` and `shelf` are never cached.** The source results come from the shared 24h cache, while these two depend on the current catalog and on the user, so they're computed per request after the cache read, in one extra query for `shelf`. A test searches, adds the book, then searches again: the second search is served from the cache and still shows the new `book_id` and `shelf`.
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
- **`dnf_reason` is optional (T-6).** Leaving it out, or sending `""`, while the book is or becomes `dnf` saves `not_specified`, so a DNF row never has an empty reason. The database enforces that, and a second constraint (`user_book_dnf_reason_valid`) allows only the known reasons. `not_specified` has weight 0 in `DNF_REASON_WEIGHTS`, so it never lowers similar books (R-5); a test checks that every reason has a weight.
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

## T-5: Dashboard stats (decided Nov 16, 2026)

The rules live in `tracking/stats.py`, one function per section, combined by `stats_for()`. Each call makes about 5 grouped queries.

### Endpoint

**`GET /api/stats/?year=`** requires login and covers only your data. It returns all sections at once, because on the free tier separate requests would each queue behind a cold start. `year` defaults to the current year in `TIME_ZONE`, and must be from 1900 to the current year, otherwise 400.

Response: `{year, totals: {pages, finished, dnf, average_rating}, pages_per_month, books_per_year, genre_mix, rating_distribution}`.

### Counting rules

| Section | Counts | Period |
| --- | --- | --- |
| `pages_per_month` | every log, by `log_date`, 12 rows with zeros included. `dnf_pages` is the part logged on books *currently* DNF; it's included in `pages` because those pages were read | `year` |
| `books_per_year` | `finished` = status `finished`, by the year of `finished_at`. `dnf` = status `dnf`, by the year of `dnf_at`. Entries **without that date** go in a final `{"year": null}` row, labelled "Date unknown" in the UI, so the totals still match the shelf after a Goodreads import | all years; ignores `year` |
| `genre_mix` | finished and DNF books dated in `year`. Each genre counted once per book, merged regardless of case, with the most common spelling shown. `STATS_EXCLUDED_GENRES` (default `Fiction,Nonfiction`, case-insensitive) is left out. Top 8, then "Other". Books with no genres left after that are skipped | `year` |
| `rating_distribution` | rated books whose `finished_at` is in `year`, 1 to 5 stars, zeros included. Because it goes by `finished_at`, a re-read in progress keeps its stars here. DNF books never have a rating | `year` |

- **Undated entries:** only `books_per_year` has the "Date unknown" row. The other sections need a date to place a book in a year.
- **Re-reads:** a re-read in progress (status `reading`, with an old `finished_at`) isn't counted as finished. v1 keeps no history of each read, so a book finished twice counts once, in the year of its latest finish.
- **`totals.finished` and `totals.dnf`** come from `year`'s row in `books_per_year`. **`average_rating`** is worked out from `rating_distribution`, rounded to one decimal, or null when nothing is rated.
- **Accessibility:** charts need a text alternative (PRD). The frontend builds it from these numbers; the API doesn't return prose.

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

## Dashboard (built Nov 16, 2026)

- **Layout:** **"Log today's pages" comes first**, because it's the daily action and it's what a phone shows above the fold. Then the year picker, the totals and the four T-5 charts.
- **Phone-first:** the cards are full width (2 columns from 48rem), and inputs are 16px (so iOS doesn't zoom) with `inputMode="numeric"` and 44px touch targets.
- **Quick log** (one card per book on Reading):
  - shows "Today: N pages", from `GET /api/logs/?from=<today>&to=<today>`
  - type a number and press Enter; the date is always today
  - the input **clears after a successful log**
  - logging the same day again adds to it, and progress and "Today" update
  - past days are logged on the book page
- **Charts:** Chart.js through react-chartjs-2, **lazy-loaded** (`DashboardCharts` chunk, about 55 KB gzipped), so other pages never download it. The build confirms the main bundle doesn't contain it.
  - **Colors:** the dataviz skill's reference palette, slots 1–2. Blue is finished/read and orange is DNF, stored as CSS tokens `--series-1` and `--series-2` with their own light and dark steps. Both pairs were validated against our surfaces (`#ffffff` and `#1c1917`): color-blind ΔE 24.7 light and 26.8 dark, both ≥ 3:1 contrast. Chart.js reads the tokens at render time and again when the system theme changes.
  - **Marks:** bars at most 24px thick, a 4px rounded data end (only the outermost segment of a stack), a 2px surface-colored gap between stacked segments, hairline grids, one tooltip covering every series, a legend for two series and none for one.
  - **Text alternatives:** each chart is a `<figure>` with a written summary (`charts/summaries.ts`) as its caption and as the canvas's label, plus a "Show the numbers" table. Empty data shows a message instead of empty axes.
- **Year picker:** `?year=` in the URL, defaulting to this year. It offers the years in `books_per_year` plus the current year. The previous year's numbers stay on screen while a new year loads.

## Phase 2: Goodreads import, I-1 to I-4 (decided Nov 16, 2026)

Code lives in the `imports` app. Your real export is **never committed**. `*.csv` is gitignored everywhere, and the only exception is `backend/imports/tests/fixtures/synthetic_*.csv`: made-up books in Goodreads' exact format.

### Parsing and mapping (PR 1: `imports/csv_parser.py`)
- **The file is checked first.** It must be UTF-8 (a BOM is fine), at most `IMPORT_MAX_FILE_BYTES` (5 MB), have at most `IMPORT_MAX_ROWS` (10,000) rows, and include the Goodreads header columns. A file that fails gets a clear `ImportFileError` and **nothing is saved**.
- **The CSV is never stored.** Only the columns we use become `ImportRow`s. Private Notes, Owned Copies and similar columns are never read.
- **Field mapping:**
  - **ISBN:** `ISBN13`, or `ISBN` converted to 13 digits. The `="…"` wrapping is removed.
  - **Series:** a trailing "(Series, #N)" or "(Series #N)" is removed from the title for matching and saved as series name and number. Ranges like "#1-3" are left in the title.
  - **Year:** the original publication year if present, otherwise the year published.
  - **Review:** cleaned with the same code as descriptions.
- **Status:** `read` → finished, `currently-reading` → reading, `to-read` → want to read.
  - **A custom shelf named `dnf` or `did-not-finish`** (any case, exact name) means **DNF, whichever exclusive shelf the row is on**.
  - **An unknown exclusive shelf** becomes want to read, with a note.
- **Ratings:** `My Rating` 0 means unrated. A rating is kept **only for finished books**. Any other status, DNF included, drops the rating, with a note.
- **Bad rows** (no Book Id or title, or the same Book Id twice in one file) become `failed` rows with the reason, and count as processed.

### Matching (PR 2: `imports/matching.py`)

Matching tries the cheapest source first:
1. **The catalog, by ISBN-13** (the oldest book with it).
2. **The catalog, by first author plus normalized title.** Authors use the existing name normalization. Titles use `normalize_title`: the main title before ":", trailing "(…)" or "[…]" removed, accents stripped, "&" read as "and", punctuation removed, lowercase.
3. **Open Library, by ISBN, in batches.**
4. **Google Books, by title plus author,** within the budget.

- **Open Library's rules,** checked Nov 2026 at openlibrary.org/developers/api:
  - **1 request per second** for clients that don't include a contact email in the User-Agent (ours doesn't), and 3 per second with one.
  - **Don't make "hundreds of single-book requests"; use `search.json` for batches.**
- **What we do about it:**
  - **ISBNs are looked up 40 per request** (`q=isbn:(… OR …)`, via `prefetch_isbns`), only for ISBNs not already in the catalog.
  - **Every Open Library call is throttled** to `OPEN_LIBRARY_REQUESTS_PER_SECOND` (default 1, shared by the whole process).
  - **To get 3 per second,** add a contact to `OPEN_LIBRARY_USER_AGENT` and raise the setting. We don't put an email there by default.
- **Vetting ISBN hits:** some Open Library ISBNs are attached to the wrong work. In testing, a fake ISBN came back as an unrelated Spanish book. A hit is used only if `titles_compatible` (equal titles, one a prefix of the other, or at least half the words shared). Otherwise the row moves on to title plus author, and the note explains what happened.
- **Title-plus-author matches are strict:** a result needs an exact normalized title **and** the row's first author among its authors. Near misses become unmatched rather than being guessed.
- **No single-book requests:** external hits are saved straight from the batch or search result (`catalog.save_book_result`), never through a follow-up `get_volume` or `get_work`.
  - **The cost:** books saved from Open Library this way have **no description**. Descriptions should be filled in by a throttled scheduled job **before Phase 3**, because TF-IDF needs them. The PRD already assigns metadata lookups for new books to scheduled jobs.
- **Google budget:** `spend_google_call()` counts one call against `IMPORT_GOOGLE_DAILY_BUDGET` **before** each title search. It's counted conservatively, so a search served from the cache still counts. The counter is per Pacific day and lives in the shared cache. When the budget runs out, or Google's own quota flag is set, matching raises `MatchPausedError`: the row stays pending and the import pauses until the next day.
- **Duplicates:** `manage.py merge_duplicate_books --dry-run` prints the merge plan and a **plan token**.
  - **Merging needs `--apply <token>`,** and it refuses if the catalog has changed since the dry run. Running it with neither option refuses too, so nothing can be merged without a dry run first.
  - **Groups are books with the same normalized title and first author.** The oldest book is kept. Books with no author are never grouped.
  - **A group is never merged automatically** when one user has shelf entries or logs on more than one of its books; it's reported instead.
  - **What a merge does:** shelf entries, logs and import rows are moved to the kept book, its empty fields are filled from the duplicate, and the duplicate is deleted.

### Processing (I-2, PR 3: `imports/processing.py`, `imports/apply.py`)
- **One resumable function,** `process_import_batch(import_id)`, does the work:
  - **It stops after `IMPORT_BATCH_SECONDS`** (20), well inside gunicorn's 60-second timeout.
  - **It saves after every row,** so an interruption just means the next batch resumes.
  - **It prefetches ISBNs once per batch,** up to 200 rows.
  - **A lock in the shared cache** stops two callers from processing the same import at once. The second caller gets `ImportBusyError`, and the API answers **409**.
- **It's run by:**
  - **The import page,** which calls `POST /api/imports/{id}/process/` repeatedly while it's open.
  - **`manage.py run_import <id>`,** which loops until the import is done or paused.
  - **`manage.py run_pending_imports`,** run by the **nightly job** (`.github/workflows/jobs-nightly.yml`, 10:00 UTC = 02:00 PST). It handles every pending, running or paused import, oldest first, within `--max-minutes` (20). If one import pauses on the budget it stops, because the others would pause too.
  - **A Celery task, local Docker only.** The `worker` service sets `IMPORTS_USE_CELERY=true`, and a new upload is handed to it. **Celery is only in `requirements-dev.txt`.** Production never installs or imports it; a production-only virtualenv was checked: `manage.py check`, the import views and `run_pending_imports` all work.
- **The nightly job's repository secrets** are `DATABASE_URL` and `GOOGLE_BOOKS_API_KEY`. The setup is in README → Deploy → Nightly jobs, using `gh secret set`, which prompts without echoing. The job fails fast, naming any secret that's missing.
- **The upload is kept in memory only.** By default, Django writes uploads larger than 2.5 MB to a temporary file on disk. `FILE_UPLOAD_HANDLERS` is set to the memory handler alone, with `FILE_UPLOAD_MAX_MEMORY_SIZE = IMPORT_MAX_FILE_BYTES`. Larger uploads are rejected as too large, based on `CONTENT_LENGTH`.
- **When an import finishes,** created, updated and skipped rows are deleted, and the stored counters become the record. Unmatched rows (I-4) and failed rows, which keep their reasons, stay.
- **Applying a match to the shelf** goes through `apply_shelf_changes` with **explicit** values, so no "today" defaults sneak in:
  - **A finished book with no Goodreads date stays undated,** and is counted under "Date unknown" in the stats.
  - **A currently-reading book gets no invented start date.**
  - **A date in the future is a rule error,** and the row fails.
  - **The shelf entry's `created_at` is set to Goodreads' "Date Added",** so "Added …" on the shelf is accurate.
  - **An empty series on the catalog book is filled from Goodreads.**

### Re-imports (I-3)
- **`GoodreadsLink(user, goodreads_book_id → user_book, synced_at)`** is unique per user and Goodreads ID. Two Goodreads editions can link to one shelf entry.
- **A linked entry is updated only if it's unchanged in Shelfwise since the last sync** (`user_book.updated_at <= link.synced_at`). Otherwise the row is `skipped` with "changed in Shelfwise".
- **A shelf entry that existed before the import** (added by hand) is linked, and only its **empty** fields are filled in.
- **Imported DNFs get the reason `not_specified`** and no note, because Goodreads has no DNF reason. **The import summary shows how many imported DNFs (entries with a Goodreads link) still have `not_specified`, with a link to the DNF shelf**, so you can set real ones (they affect R-5). The API field is still called `placeholder_dnf_count`.
- **Earlier imports** used the placeholder `other` + "Imported from Goodreads". Migration `tracking.0003` moves exactly that pair to `not_specified` and clears the note. It uses `QuerySet.update()`, so `updated_at` is unchanged and those entries don't count as "changed in Shelfwise" on a re-import. Reversing it restores the placeholder for linked entries.

### Unmatched rows (I-4, PR 4: `imports/resolution.py`)
- **`GET /api/imports/{id}/rows/?state=unmatched|failed`** lists the rows that need attention. Each row has its Goodreads title, author, ISBN, status, rating, date and note (why it didn't match), plus **`search_query`** ("title first-author") to pre-fill the search box.
- **`POST …/rows/{row}/resolve/`** takes `{book_id}`, or `{source, source_id}` from a search result. The latter may call the book API, the same user-initiated exception as adding from search.
  - **It applies the row with the same rules as automatic matching** (`apply_match`): create, link and fill, or skip, with the match method `manual`.
  - **Only `unmatched` rows can be resolved.** Anything else returns **409**.
- **`POST …/rows/{row}/dismiss/`** marks a row `dismissed`, which counts as skipped.
- **Counts stay correct in both phases of an import:**
  - **A finished import** adjusts its stored counts in place, using `F()` expressions, and **deletes** the resolved or dismissed row (privacy). A row that fails stays, with its reason.
  - **An import still running or paused** keeps the row's new state and recalculates its counts from the rows. Finishing deletes created, updated, skipped **and dismissed** rows.

### Import page (PR 5: frontend)
- **`/import`:** the upload form, which checks for a `.csv` of at most 5 MB before sending and explains how to export from Goodreads and that the file is never stored. Below it, past imports. **Import** is in the navigation.
- **`/import/:id`:** while the import is pending or running, `useImportRunner` calls `POST /process/` **back to back**, about 20 seconds each, and updates the progress bar ("N of M rows").
  - **A 409** means the nightly job or the local Celery worker holds the import: "Another process is working on this import…". The runner waits `BUSY_RETRY_MS` (5 seconds), refreshes the import and tries again.
  - **A pause** shows the reason, "It will continue automatically tonight", and a **try again now** button.
  - **Closing the page** just stops the runner; the nightly job finishes the rest.
  - **There's no "already running" guard,** because StrictMode runs effects twice in development. A duplicate run hits the server's lock (409) and waits.
- **When it's done,** a summary shows the counts, plus "**N imported DNFs have no reason yet**" with a link to `/shelf?status=dnf`.
- **Books that need a match:** each one shows its Goodreads details and the reason. **Find a match** opens a search pre-filled with `search_query`, with Google attribution, a "View on …" link per result and **Use this book**, which resolves with `{book_id}` or `{source, source_id}`. **Dismiss** skips the row. Failed rows are listed with their reasons in a `<details>`.
- **Uploads** go through `apiPostForm`, and the client no longer sets `Content-Type` for `FormData`, so the browser adds the multipart boundary itself.

### Measuring against the real export (PR 6)

`manage.py goodreads_match_report <csv>` runs the real matching pipeline over an export **without touching any shelf** and prints the match rate against the **90% gate**, with counts by method and unmatched reasons by category.
- **It prints aggregates only by default.** `--show-unmatched` lists titles, for local tuning only; never paste them anywhere.
- **Matched books are saved to the catalog,** so a later real import of the same file is mostly catalog hits.

Running it on your real export (433 rows) turned up four problems, now fixed:
1. **Ratings were silently dropped.** Real exports write `My Rating` as `"5.0"`, and `Number of Pages` as `"320.0"`. `parse_int` now accepts a trailing `.0`, and still rejects `4.5`, negative numbers and text. 65 ratings and 421 page counts came back. The synthetic fixture now uses the decimal form, and there are regression tests.
2. **Every 429 from Google was treated as "daily quota used up"** and blocked Google until midnight Pacific. Google returns 429 for its **per-minute** limit too. That happened after about 130 quick calls, and the same request worked a moment later. `_limit_kind` reads the error body:
   - **Only an explicit daily limit** (`dailyLimitExceeded`, or a message mentioning "per day") sets the all-day flag.
   - **Any other 429 is a `RateLimitedError`.** Search falls back to Open Library for that request only.
   - **In imports,** a rate limit raises `MatchRetryLaterError`: the batch ends early, the row stays pending, and the import stays `running`, so the next batch carries on.
   - **Import calls to Google** are now spaced to `IMPORT_GOOGLE_REQUESTS_PER_SECOND` (default 1).
3. **The Open Library User-Agent was fixed when the session was created.** The cached HTTP session kept the User-Agent it started with, so later changes to the setting were ignored. It only showed up in tests when they ran in a particular order. It's now sent with each request.
4. **Matching tuning:**
   - **A trailing note after an author's name is ignored** when comparing a result to a row, for example "RuNyx (Novelist)". This uses a separate `_author_key`, so the shared `normalize_author_name` still matches its database twin.
   - **Google by ISBN:** when Open Library doesn't know an ISBN, matching makes **one budgeted Google lookup by ISBN**, accepted if the titles are compatible.
   - **Open Library by title and author:** when Google has no exact title-and-author match, matching tries **Open Library's title and author search**, which is throttled, uses no Google budget, and has the same exact-match rule.

## Phase 5 backlog

Everything deferred so far, in one place, to pick up in Phase 5 (polish) or sooner if it becomes urgent. Each item links back to where it was decided.

### Security

- **Token blacklist and server-side logout** (T-1). Add simplejwt's `token_blacklist` app, which is a migration, with `BLACKLIST_AFTER_ROTATION = True`, plus `POST /api/auth/logout/`. Today an old refresh token stays valid until it expires (7 days). Do this before any public beta.
- **Raise HSTS** (Deploy). `DJANGO_HSTS_SECONDS` defaults to 1 day. Raise it (for example to 1 year) once production has been stable for a while. Keep subdomains and preload off while on `onrender.com`.
- **Refresh token in an httpOnly cookie** (Frontend foundation). This isn't possible while the frontend and API are on different `onrender.com` subdomains, because `onrender.com` is a public suffix, so the cookie would be third-party and blocked. It becomes possible with a **custom domain** serving both, for example `app.` and `api.` under one domain. A domain is also what the PRD needs for emailing anyone other than me.

### Data and features

- **History of each read** (T-2, T-5). v1 keeps one set of dates per book, so a re-read overwrites `started_at` and `finished_at`, and a book finished twice counts once, in its latest year. A `reads` table would give accurate re-read stats.
- **Indexed `name_normalized` on `Author`** (C-1 / C-2). Author name matching scans the table with a Postgres expression. Add the indexed column, which is a migration, if the C-3 catalog seed makes saves slow.
- **Reading streak** (Dashboard). Consecutive days with at least one reading log, for the goal-setter persona. It's not part of T-5, so the Phase 1 dashboard shows totals only. It can be worked out from `ReadingLog.log_date` in `TIME_ZONE`, added to `/api/stats/`, and shown as a stat tile.
- **Sign-up page** (Frontend foundation). Production has sign-up turned off (`ALLOW_SIGNUP=false`) and v1 has one user. Add the page only if a public beta happens.

### Tooling

- **Upgrade to Vitest 4.** `npm audit` still reports one moderate advisory in `@vitest/mocker` 3.x ([GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9), [GHSA-qxg6-89mg-rqv8](https://github.com/advisories/GHSA-qxg6-89mg-rqv8)), fixed only in Vitest 4.1.12+. It's dev tooling, not in the production bundle, and our plain `vitest run` with jsdom doesn't use the affected mocker plugin, so it isn't urgent. When upgrading:
  - check that `@testing-library/jest-dom` and the MSW setup still work
  - remove the `tinypool` override in `frontend/package.json` if Vitest 4 no longer needs it

### Planned for another phase, not Phase 5

- **Merging the same book saved from both sources** (C-1 / C-2). ISBN matching misses editions with different ISBNs. Matching by normalized title plus first author is planned for the **Phase 2** Goodreads import, along with merging any existing duplicates.
