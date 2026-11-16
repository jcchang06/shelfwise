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
- **No server-side logout yet.** The frontend logs out by discarding its tokens. Revoking tokens on the server would need simplejwt's `token_blacklist` app, which adds a migration. Revisit it if a public beta happens.

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

- **Each entry includes `pages_logged` and `reading_log_count`.**
- **Removing a book** is a plain DELETE that also deletes the user's `ReadingLog` rows for that book. The frontend asks for confirmation first and uses `reading_log_count` in the message.

### Status changes

Side effects only happen when the status actually changes. Values sent in the request always win over these defaults.

| Change | Side effects |
| --- | --- |
| `finished` → `reading` | `started_at` = today, **overwriting** the first read's start, because a re-read is a new read |
| `want_to_read` → `reading` | `started_at` = today only if empty |
| `dnf` → `reading` | `started_at` is **kept**, because resuming continues the same read. Filled with today only if empty |
| any → `finished` | `finished_at` = today, **overwriting** an earlier date, so a re-read marked finished again gets the new date |
| any → `dnf` | **rating cleared**, because stars and a DNF don't mix. `finished_at` is kept. `dnf_at` = today. `dnf_page` = total pages logged, capped at `page_count`, or null if there are no logs. `dnf_reason` is required |
| `dnf` → any | all DNF fields cleared (`dnf_page`, `dnf_at`, `dnf_reason`, `dnf_note`). Logs are kept |
| `finished` → `reading` / `want_to_read` | **rating and `finished_at` kept.** A re-read mustn't erase a 5★ that drives recommendations and auto-follow |

### Validation (400, with every broken rule reported at once)

- **Rating (T-4)** can only be **set or changed** when the status after the request is `finished`.
  - Re-sending the current value is fine, so a client can PATCH a whole object back.
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

## T-3: Page logs

- **One log row per user, book and day.** The database enforces this.
- **POSTing a log** for a book and day that already has one *adds* `pages_read` to it, so logging twice in a day accumulates.
- **PATCHing a log** *sets* that day's total.
- **Logging pages on a `want_to_read` book** moves it to `reading` and sets `started_at` to the log date if it's empty.
