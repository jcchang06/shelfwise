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

## T-2: Shelf API

- **Removing a book from the shelf** deletes its `ReadingLog` rows for that user too. The frontend asks for confirmation first, and the confirmation says how many logs will be deleted.
- **Marking a book DNF keeps its logs.** Pages read before stopping still count in stats.
- **Resuming a DNF book** clears all DNF fields: `dnf_page`, `dnf_at`, `dnf_reason` and `dnf_note`. A book you're reading again must not count as a negative signal for recommendations (R-5).
- **When marking a book DNF:**
  - `dnf_reason` is required. The database enforces this too.
  - `dnf_at` defaults to today.
  - `dnf_page` defaults to the total `pages_read` across that user's logs for the book, and can't exceed `page_count` when that's known.

## T-4: Ratings

- **A rating is only allowed while the status is `finished`.** The API rejects a rating on any other status. The database only checks the 1 to 5 range.

## T-3: Page logs

- **One log row per user, book and day.** The database enforces this.
- **POSTing a log** for a book and day that already has one *adds* `pages_read` to it, so logging twice in a day accumulates.
- **PATCHing a log** *sets* that day's total.
- **Logging pages on a `want_to_read` book** moves it to `reading` and sets `started_at` to the log date if it's empty.
