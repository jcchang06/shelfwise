# API fixtures

Trimmed Google Books and Open Library response bodies used by the catalog tests.

- **Recorded** from the real APIs with `scripts/record_fixtures.py` (see its docstring). The query was "project hail mary", plus its ISBN and a query with no results. The API key is stripped from URLs and scrubbed from bodies.
- **`raw/`** holds the full responses, written by the same script. It's gitignored and must never be committed.
- **The tests check general properties, not specific titles.** They check that every result parses, ISBNs are 13 digits, covers are https and no HTML is left. The `TestRecordedResponses` classes also compare each raw field with its parsed version. So a fresh recording shouldn't break the tests. Edge cases use small inline payloads in the tests instead.
