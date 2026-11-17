"""Reading Open Library data dumps (C-3): https://openlibrary.org/developers/dumps

Formats (checked against the 2026-10-31 dump):

- works / authors: 5 tab-separated columns: type, key, revision, last_modified, JSON.
- reading-log: work key, edition key (or \\N), shelf ("Want to Read", "Currently Reading",
  "Already Read", "Stopped Reading"), date.
- ratings: work key, edition key (or \\N), rating 1-5, date.

The works dump is about 4 GB compressed (~40 million works), so lines are filtered by
key before any JSON is parsed, and work keys are held as integers ("OL82563W" -> 82563)
to keep the popularity counts small.
"""

import gzip
import json
import shutil
import subprocess
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# A reader stopping is a DNF: it doesn't make a work popular.
COUNTED_SHELVES = frozenset({"Want to Read", "Currently Reading", "Already Read"})


class DumpError(Exception):
    """A dump file is missing or isn't in the expected format."""


def find_dump(directory: Path, name: str) -> Path:
    """The newest ol_dump_<name>_<date>.txt.gz (or _latest) in directory."""
    matches = sorted(directory.glob(f"ol_dump_{name}_*.txt.gz"))
    if not matches:
        raise DumpError(f"No ol_dump_{name}_*.txt.gz in {directory}")
    return matches[-1]


@contextmanager
def _lines(path: Path) -> Iterator[Iterator[str]]:
    """Decompressed lines. Uses the gzip program when there is one, so decompression runs
    in its own process, in parallel with the parsing here."""
    gzip_program = shutil.which("gzip")
    if gzip_program:
        # A fixed program and flags; the only argument is a dump path we chose.
        process = subprocess.Popen(  # noqa: S603
            [gzip_program, "-dc", str(path)],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1 << 20,
        )
        try:
            yield iter(process.stdout)  # type: ignore[arg-type]
        finally:
            process.stdout.close()  # type: ignore[union-attr]
            process.kill()
            process.wait()
    else:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            yield iter(handle)


def key_id(key: str, kind: str = "W") -> int | None:
    """ "/works/OL82563W" or "OL82563W" -> 82563; None if it isn't that kind of key."""
    short = key.rsplit("/", 1)[-1]
    if not (short.startswith("OL") and short.endswith(kind)):
        return None
    digits = short[2:-1]
    return int(digits) if digits.isdigit() else None


def work_key(identifier: int) -> str:
    return f"OL{identifier}W"


def reading_log_counts(path: Path) -> Counter[int]:
    """Readers per work: Want to Read + Currently Reading + Already Read entries."""
    counts: Counter[int] = Counter()
    with _lines(path) as lines:
        for line in lines:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or parts[2] not in COUNTED_SHELVES:
                continue
            if (work := key_id(parts[0])) is not None:
                counts[work] += 1
    return counts


def rating_counts(path: Path) -> Counter[int]:
    counts: Counter[int] = Counter()
    with _lines(path) as lines:
        for line in lines:
            parts = line.split("\t", 2)
            if len(parts) >= 2 and (work := key_id(parts[0])) is not None:
                counts[work] += 1
    return counts


def records(path: Path, wanted: set[int], kind: str) -> Iterator[tuple[int, dict[str, Any]]]:
    """(id, JSON record) for the works (kind "W") or authors ("A") in `wanted`. Only
    wanted lines are parsed; a malformed wanted line is skipped."""
    with _lines(path) as lines:
        for line in lines:
            parts = line.split("\t", 4)
            if len(parts) != 5:
                continue
            identifier = key_id(parts[1], kind)
            if identifier is None or identifier not in wanted:
                continue
            try:
                yield identifier, json.loads(parts[4])
            except json.JSONDecodeError:
                continue
