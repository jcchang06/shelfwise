# API fixtures

Trimmed Google Books and Open Library response bodies used by the catalog tests.

- Regenerate from real responses with `scripts/record_fixtures.py` (see its docstring).
  It also saves full responses to `raw/`, which is gitignored and must not be committed.
- The first committed versions were hand-written in the same trimmed shape, with obviously
  fake IDs (`gbFixture0001`, `OL0000001W`), so tests could run before the first recording.
- Tests over these files check invariants (every result parses, ISBNs are 13 digits,
  covers are https), not specific titles, so a fresh recording shouldn't break them.
  Edge cases use small inline payloads in the tests instead.
